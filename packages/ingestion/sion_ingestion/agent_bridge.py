from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import socket
import string
import sys
from typing import Any

from sqlalchemy.orm import Session

from sion_ingestion.map_import import (
    ImportResult,
    MapEdge,
    MapExport,
    MapNode,
    import_map_export,
)

# Environment variable through which the CLI (or any caller) injects the secret
# used to mint opaque source tokens.  bridge_cli is owned by another worker, so
# the bridge reads the key itself instead of requiring a CLI signature change.
SOURCE_TOKEN_KEY_ENV = "SION_SOURCE_TOKEN_KEY"

# Deterministic fallback so a misconfigured deployment still produces stable,
# non-reversible tokens rather than silently leaking raw paths.  Deployments
# that need cross-host token stability must set SOURCE_TOKEN_KEY_ENV.
_DEFAULT_TOKEN_KEY = b"sion-agent-bridge-default-source-token-key"

SESSION_REFERENCE_PREFIX = "urn:sion:agent-session"
SOURCE_TOKEN_PREFIX = "urn:sion:source-token"

# Transcript size ceiling shared by every reader.  Oversized transcripts are
# skipped (and reported) rather than parsed, so a single runaway log can never
# blow up memory or the DLP scanner's node budget.
MAX_TRANSCRIPT_BYTES = 5_000_000

# A transcript below this size cannot contain a usable session payload.
MIN_TRANSCRIPT_BYTES = 100

# Diagnostics statuses recorded per session during discovery.
STATUS_OK = "ok"
STATUS_OVERSIZED = "oversized_transcript"
STATUS_MALFORMED = "malformed_transcript"
STATUS_UNREADABLE = "unreadable_transcript"


def resolve_source_token_key(key: bytes | str | None = None) -> bytes:
    """Resolve the opaque-token HMAC key.

    Precedence: explicit argument, then ``SION_SOURCE_TOKEN_KEY``, then a fixed
    fallback.  The key never leaves this module and is not written to any sink.
    """
    if key is None:
        key = os.environ.get(SOURCE_TOKEN_KEY_ENV)
    if key is None or key == "":
        return _DEFAULT_TOKEN_KEY
    return key.encode("utf-8") if isinstance(key, str) else bytes(key)


def logical_source_reference(provider: str, session_id: str) -> str:
    """Build a logical, path-free reference for a discovered session.

    This is the *stable identity* written to sinks in place of the raw
    ``file:///...`` URI.  It contains no absolute path, no user name, and no
    host detail, so it survives the DLP scanner without triggering a finding
    on the key name itself.
    """
    safe_provider = re.sub(r"[^\w\-.]", "-", provider.lower().strip()) or "unknown"
    safe_session = re.sub(r"[^\w\-.]", "-", session_id.strip()) or "unknown"
    return f"{SESSION_REFERENCE_PREFIX}:{safe_provider}:{safe_session}"


def opaque_source_token(value: str, key: bytes | str | None = None) -> str:
    """Replace a raw path or locator with a deterministic opaque token.

    The token is stable for a given (key, value) pair so identity and
    deduplication survive across runs, but it cannot be reversed into the
    original absolute path or user name without the key.
    """
    if not value:
        return ""
    digest = hmac.new(resolve_source_token_key(key), value.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{SOURCE_TOKEN_PREFIX}:{digest[:32]}"


@dataclass(frozen=True)
class SessionDiagnostics:
    """Explicit, non-payload-bearing account of what discovery did with a file."""

    session_id: str
    status: str = STATUS_OK
    reason: str = ""
    size_bytes: int = 0
    records_parsed: int = 0
    records_malformed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "reason": self.reason,
            "size_bytes": self.size_bytes,
            "records_parsed": self.records_parsed,
            "records_malformed": self.records_malformed,
        }


def get_device_id() -> str:
    """Return a sanitized, unique device identifier for the current machine."""
    raw = os.environ.get("SION_DEVICE_ID") or socket.gethostname().lower()
    return re.sub(r"[^\w\-.]", "-", raw).strip("-") or "unknown-device"


def get_user_home_names() -> set[str]:
    """Return lower-cased directory names that identify the current user.

    Used to avoid writing a user name into a sink under a friendlier key such as
    a project name.  Only the names are needed; the paths never leave the process.
    """
    names: set[str] = set()
    for candidate in (os.path.expanduser("~"), os.environ.get("HOME"), os.environ.get("USERPROFILE")):
        if candidate:
            names.add(Path(candidate).name.lower())
    try:
        names.add(Path.home().name.lower())
    except (OSError, RuntimeError):
        pass
    return {name for name in names if name}


def detect_google_drive_root() -> Path | None:
    """Dynamically detect Google Drive root path across Windows, macOS, and Linux."""
    # 1. Environment variable override
    for env_k in ("SION_DRIVE_ROOT", "GOOGLE_DRIVE_ROOT"):
        val = os.environ.get(env_k)
        if val and Path(val).exists():
            return Path(val)

    home = Path.home()

    # 2. Windows drive letters
    if sys.platform == "win32":
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:/")
            if drive.exists():
                for cand in ("내 드라이브", "My Drive", "Google Drive", "GoogleDrive"):
                    p = drive / cand
                    if p.exists():
                        return p

    # 3. User home directory standard paths
    for cand in ("Google Drive", "GoogleDrive", "내 드라이브", "My Drive", "google-drive"):
        p = home / cand
        if p.exists():
            return p

    # 4. macOS CloudStorage
    if sys.platform == "darwin":
        cs = home / "Library" / "CloudStorage"
        if cs.exists():
            for p in cs.glob("GoogleDrive-*"):
                for sub in ("My Drive", "내 드라이브"):
                    if (p / sub).exists():
                        return p / sub
                return p

    return None


@dataclass
class AgentSession:
    """Normalized intermediate session representation across heterogeneous agents."""
    session_id: str
    provider: str
    title: str
    device_id: str = field(default_factory=get_device_id)
    cwd: str = ""
    created_at: str = ""
    tools: set[str] = field(default_factory=set)
    artifacts: set[str] = field(default_factory=set)
    decisions: list[str] = field(default_factory=list)
    # Raw ``file:///`` locator.  Process-local input only: it is used to mint an
    # opaque token and is never serialized into a MapExport.
    source_uri: str = ""
    diagnostics: SessionDiagnostics | None = None

    @property
    def source_reference(self) -> str:
        """Logical, path-free identity of this session, safe for any sink."""
        return logical_source_reference(self.provider, self.session_id)


class BaseAgentReader(ABC):
    """Abstract interface for agent session readers across any computer.

    Readers never swallow a parse or size failure silently: every file examined
    produces a :class:`SessionDiagnostics` entry in :attr:`diagnostics`.
    """
    provider: str = "unknown"

    def __init__(self) -> None:
        self.diagnostics: list[SessionDiagnostics] = []

    def _record(self, diagnostics: SessionDiagnostics) -> None:
        self.diagnostics.append(diagnostics)

    def reset_diagnostics(self) -> None:
        self.diagnostics.clear()

    @abstractmethod
    def discover(self, limit: int | None = None) -> list[AgentSession]:
        pass


class AntigravityReader(BaseAgentReader):
    """Discovers and parses Google Antigravity session transcripts and artifacts."""
    provider = "antigravity"

    def __init__(self, brain_dir: str | Path | None = None):
        if brain_dir is not None:
            self.brain_dirs = [Path(brain_dir)]
        else:
            home = Path.home()
            self.brain_dirs = [
                home / ".gemini" / "antigravity" / "brain",
            ]
            if sys.platform == "win32":
                local_app_data = os.environ.get("LOCALAPPDATA")
                if local_app_data:
                    self.brain_dirs.append(
                        Path(local_app_data) / "gemini" / "antigravity" / "brain"
                    )
        super().__init__()

    def discover(self, limit: int | None = None) -> list[AgentSession]:
        active_brain = next((d for d in self.brain_dirs if d.exists()), None)
        if not active_brain:
            return []

        sessions: list[AgentSession] = []
        candidates = sorted(
            [d for d in active_brain.iterdir() if d.is_dir() and d.name != "tempmediaStorage"],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )

        if limit is not None and limit > 0:
            candidates = candidates[:limit]

        device_id = get_device_id()

        for sdir in candidates:
            log_file = sdir / ".system_generated" / "logs" / "transcript.jsonl"
            if not log_file.exists():
                continue

            session_id = sdir.name
            size_bytes = log_file.stat().st_size
            if size_bytes > MAX_TRANSCRIPT_BYTES:
                # Oversized: skipped, but never silently.
                self._record(SessionDiagnostics(session_id, STATUS_OVERSIZED, f"size>{MAX_TRANSCRIPT_BYTES}", size_bytes))
                continue
            if size_bytes < MIN_TRANSCRIPT_BYTES:
                self._record(SessionDiagnostics(session_id, STATUS_MALFORMED, "below minimum size", size_bytes))
                continue

            title = f"Antigravity Session {session_id[:8]}"
            tools: set[str] = set()
            artifacts: set[str] = set()
            decisions: list[str] = []
            cwd = ""
            created_at = ""
            parsed = 0
            malformed = 0

            for art in sdir.glob("*.md"):
                artifacts.add(art.name)
                if art.name == "implementation_plan.md":
                    decisions.append(f"Plan created: {art.name}")

            try:
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            item = json.loads(line)
                        except Exception:
                            malformed += 1
                            continue
                        if not isinstance(item, dict):
                            malformed += 1
                            continue
                        parsed += 1

                        if not created_at and "created_at" in item:
                            created_at = str(item["created_at"])

                        if item.get("type") == "USER_INPUT" and title.startswith("Antigravity Session"):
                            content = item.get("content", "")
                            req_match = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", content, re.DOTALL)
                            raw_text = req_match.group(1).strip() if req_match else content.strip()
                            clean_text = raw_text.split("\n")[0][:80].strip()
                            if clean_text:
                                title = clean_text

                        for tc in item.get("tool_calls", []):
                            tname = tc.get("name")
                            if tname:
                                tools.add(tname)
                            args = tc.get("args", {})
                            if isinstance(args, dict):
                                if "Cwd" in args and not cwd:
                                    cwd = str(args["Cwd"]).strip('"')
                                if "TargetFile" in args:
                                    tfile = Path(str(args["TargetFile"]).strip('"')).name
                                    artifacts.add(tfile)
            except OSError as exc:
                self._record(SessionDiagnostics(session_id, STATUS_UNREADABLE, type(exc).__name__, size_bytes))
                continue

            status, reason = (STATUS_OK, "")
            if parsed == 0:
                status, reason = STATUS_MALFORMED, "no parseable records"
            self._record(SessionDiagnostics(session_id, status, reason, size_bytes, parsed, malformed))

            sessions.append(
                AgentSession(
                    session_id=session_id,
                    provider=self.provider,
                    device_id=device_id,
                    title=title,
                    cwd=cwd,
                    created_at=created_at or _file_timestamp(log_file),
                    tools=tools,
                    artifacts=artifacts,
                    decisions=decisions,
                    source_uri=f"file:///{log_file.as_posix()}",
                    diagnostics=SessionDiagnostics(session_id, status, reason, size_bytes, parsed, malformed),
                )
            )
        return sessions


class CodexReader(BaseAgentReader):
    """Discovers and parses OpenAI Codex session transcripts."""
    provider = "codex"

    def __init__(self, sessions_dir: str | Path | None = None):
        if sessions_dir is not None:
            self.sessions_dir = Path(sessions_dir)
        else:
            self.sessions_dir = Path.home() / ".codex" / "sessions"
        super().__init__()

    def discover(self, limit: int | None = None) -> list[AgentSession]:
        if not self.sessions_dir.exists():
            return []

        files = []
        for p in self.sessions_dir.glob("**/*.jsonl"):
            try:
                st = p.stat()
            except OSError:
                self._record(
                    SessionDiagnostics(p.stem.replace("rollout-", ""), STATUS_UNREADABLE, "stat failed")
                )
                continue
            if st.st_size > MAX_TRANSCRIPT_BYTES:
                # Recorded rather than dropped, so an oversized transcript stays visible.
                self._record(
                    SessionDiagnostics(
                        p.stem.replace("rollout-", ""), STATUS_OVERSIZED, f"size>{MAX_TRANSCRIPT_BYTES}", st.st_size
                    )
                )
                continue
            files.append((st.st_mtime, p))

        files.sort(key=lambda x: x[0], reverse=True)
        if limit is not None and limit > 0:
            files = files[:limit]

        device_id = get_device_id()
        sessions: list[AgentSession] = []

        for _, fpath in files:
            session_id = fpath.stem.replace("rollout-", "")
            try:
                size_bytes = fpath.stat().st_size
            except OSError as exc:
                self._record(SessionDiagnostics(session_id, STATUS_UNREADABLE, type(exc).__name__))
                continue
            title = f"Codex Session {session_id[:8]}"
            cwd = ""
            created_at = ""
            tools: set[str] = set()
            artifacts: set[str] = set()
            decisions: list[str] = []
            parsed = 0
            malformed = 0

            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            item = json.loads(line)
                        except Exception:
                            malformed += 1
                            continue
                        if not isinstance(item, dict):
                            malformed += 1
                            continue
                        parsed += 1

                        if item.get("type") == "session_meta":
                            payload = item.get("payload", {})
                            cwd = payload.get("cwd", "")
                            session_id = payload.get("id") or session_id
                            created_at = payload.get("timestamp", "")

                        if item.get("type") == "response_item":
                            payload = item.get("payload", {})
                            if payload.get("role") == "user" and title.startswith("Codex Session"):
                                for c in payload.get("content", []):
                                    text = c.get("text", "")
                                    first_line = text.strip().split("\n")[0][:80].strip()
                                    if first_line:
                                        title = first_line

                            if payload.get("type") == "function_call":
                                fname = payload.get("name")
                                if fname:
                                    tools.add(fname)
            except OSError as exc:
                self._record(SessionDiagnostics(session_id, STATUS_UNREADABLE, type(exc).__name__, size_bytes))
                continue

            status, reason = (STATUS_OK, "")
            if parsed == 0:
                status, reason = STATUS_MALFORMED, "no parseable records"
            diagnostics = SessionDiagnostics(session_id, status, reason, size_bytes, parsed, malformed)
            self._record(diagnostics)

            sessions.append(
                AgentSession(
                    session_id=session_id,
                    provider=self.provider,
                    device_id=device_id,
                    title=title,
                    cwd=cwd,
                    created_at=created_at or _file_timestamp(fpath),
                    tools=tools,
                    artifacts=artifacts,
                    decisions=decisions,
                    source_uri=f"file:///{fpath.as_posix()}",
                    diagnostics=diagnostics,
                )
            )
        return sessions


class ClaudeReader(BaseAgentReader):
    """Discovers and parses Anthropic Claude Code session transcripts."""
    provider = "claude"

    def __init__(self, transcripts_dir: str | Path | None = None):
        if transcripts_dir is not None:
            self.transcripts_dir = Path(transcripts_dir)
        else:
            self.transcripts_dir = Path.home() / ".claude" / "transcripts"
        super().__init__()

    def discover(self, limit: int | None = None) -> list[AgentSession]:
        if not self.transcripts_dir.exists():
            return []

        oversize: list[tuple[Path, int]] = []
        undersize: list[tuple[Path, int]] = []
        candidates: list[Path] = []
        for p in self.transcripts_dir.glob("*.jsonl"):
            try:
                size = p.stat().st_size
            except OSError:
                self._record(
                    SessionDiagnostics(p.stem.replace("ses_", ""), STATUS_UNREADABLE, "stat failed")
                )
                continue
            if size > MAX_TRANSCRIPT_BYTES:
                oversize.append((p, size))
            elif size < MIN_TRANSCRIPT_BYTES:
                undersize.append((p, size))
            else:
                candidates.append(p)

        for path, size in oversize:
            self._record(
                SessionDiagnostics(
                    path.stem.replace("ses_", ""), STATUS_OVERSIZED, f"size>{MAX_TRANSCRIPT_BYTES}", size
                )
            )
        for path, size in undersize:
            self._record(
                SessionDiagnostics(path.stem.replace("ses_", ""), STATUS_MALFORMED, "below minimum size", size)
            )

        files = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)

        if limit is not None and limit > 0:
            files = files[:limit]

        device_id = get_device_id()
        sessions: list[AgentSession] = []

        for fpath in files:
            session_id = fpath.stem.replace("ses_", "")
            try:
                size_bytes = fpath.stat().st_size
            except OSError as exc:
                self._record(SessionDiagnostics(session_id, STATUS_UNREADABLE, type(exc).__name__))
                continue
            title = f"Claude Session {session_id[:8]}"
            cwd = ""
            created_at = ""
            tools: set[str] = set()
            artifacts: set[str] = set()
            decisions: list[str] = []
            parsed = 0
            malformed = 0

            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            item = json.loads(line)
                        except Exception:
                            malformed += 1
                            continue
                        if not isinstance(item, dict):
                            malformed += 1
                            continue
                        parsed += 1

                        if not created_at and "timestamp" in item:
                            created_at = str(item["timestamp"])

                        itype = item.get("type")
                        if itype == "user" and title.startswith("Claude Session"):
                            content = item.get("content", "")
                            if isinstance(content, str):
                                first_line = content.strip().split("\n")[0][:80].strip()
                                if first_line:
                                    title = first_line

                        if itype == "tool_use":
                            tname = item.get("tool_name")
                            if tname:
                                tools.add(tname)
                            tinput = item.get("tool_input", {})
                            if isinstance(tinput, dict):
                                if "filePath" in tinput:
                                    fp = Path(tinput["filePath"])
                                    artifacts.add(fp.name)
                                    if not cwd:
                                        cwd = str(fp.parent)
                                if "command" in tinput and not cwd:
                                    cmd = str(tinput["command"])
                                    m = re.search(r'Path "([^"]+)"', cmd)
                                    if m:
                                        cwd = m.group(1)
            except OSError as exc:
                self._record(SessionDiagnostics(session_id, STATUS_UNREADABLE, type(exc).__name__, size_bytes))
                continue

            status, reason = (STATUS_OK, "")
            if parsed == 0:
                status, reason = STATUS_MALFORMED, "no parseable records"
            diagnostics = SessionDiagnostics(session_id, status, reason, size_bytes, parsed, malformed)
            self._record(diagnostics)

            sessions.append(
                AgentSession(
                    session_id=session_id,
                    provider=self.provider,
                    device_id=device_id,
                    title=title,
                    cwd=cwd,
                    created_at=created_at or _file_timestamp(fpath),
                    tools=tools,
                    artifacts=artifacts,
                    decisions=decisions,
                    source_uri=f"file:///{fpath.as_posix()}",
                    diagnostics=diagnostics,
                )
            )
        return sessions


class DeepSeekReader(BaseAgentReader):
    provider = "deepseek"
    def discover(self, limit: int | None = None) -> list[AgentSession]:
        return []


class HermesReader(BaseAgentReader):
    provider = "hermes"
    def discover(self, limit: int | None = None) -> list[AgentSession]:
        return []


class ZCodeReader(BaseAgentReader):
    provider = "zcode"
    def discover(self, limit: int | None = None) -> list[AgentSession]:
        return []


PROVIDER_REGISTRY: dict[str, type[BaseAgentReader]] = {
    "antigravity": AntigravityReader,
    "codex": CodexReader,
    "claude": ClaudeReader,
    "deepseek": DeepSeekReader,
    "hermes": HermesReader,
    "zcode": ZCodeReader,
}


def register_provider(name: str, reader_cls: type[BaseAgentReader]) -> None:
    PROVIDER_REGISTRY[name.lower()] = reader_cls


def _file_timestamp(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return "1970-01-01T00:00:00+00:00"


class AgentOntologyBridge:
    """Bridges AgentSessions into sion-core ontology nodes and edges with multi-device support.

    Source policy
    -------------
    The bridge never writes a raw absolute path or a user name into an export.
    Every locator is replaced by one of two path-free values:

    * ``source_reference`` - a logical URN built from provider + session id.  It
      carries no filesystem detail, and the key name is deliberately *not*
      ``source_uri``, which the DLP scanner treats as an unconditional
      INTERNAL finding (and therefore quarantines).
    * ``source_token`` / ``cwd_token`` - an opaque HMAC-SHA256 token, stable for
      a given key so identity and deduplication survive across runs, but not
      reversible without the key.

    ``stable_key`` construction is unchanged, so existing rows keep matching.
    """

    def __init__(self, source_token_key: bytes | str | None = None) -> None:
        self._source_token_key = resolve_source_token_key(source_token_key)
        self._home_names = get_user_home_names()

    @staticmethod
    def _slugify(text: str) -> str:
        s = re.sub(r"[^\w\-_.]", "-", text.lower().strip())
        return re.sub(r"-+", "-", s).strip("-") or "unknown"

    def _token(self, value: str) -> str:
        return opaque_source_token(value, self._source_token_key)

    def _safe_display_name(self, candidate: str, fallback: str) -> str:
        """Refuse to surface a bare user-home directory name as an entity name."""
        if not candidate or candidate.lower() in self._home_names:
            return fallback
        return candidate

    def convert_sessions_to_map_export(
        self, sessions: list[AgentSession], source_label: str = "multi-agent-bridge"
    ) -> MapExport:
        nodes: dict[str, MapNode] = {}
        edges: dict[str, MapEdge] = {}

        for sess in sessions:
            # 1. Device Node (SystemComponent)
            dev_key = f"device:{self._slugify(sess.device_id)}"
            if dev_key not in nodes:
                nodes[dev_key] = MapNode(
                    stable_key=dev_key,
                    entity_type_id="SystemComponent",
                    name=f"Device {sess.device_id}",
                    category="core",
                    properties={"device_id": sess.device_id},
                )

            # 2. Workflow Node (Session execution scoped to device)
            session_identity = self._slugify(sess.session_id)
            cwd_hash = hashlib.sha256(sess.cwd.encode("utf-8")).hexdigest()
            wf_key = f"workflow:{sess.provider}:{self._slugify(sess.device_id)}:{session_identity}:{cwd_hash}"
            nodes[wf_key] = MapNode(
                stable_key=wf_key,
                entity_type_id="Workflow",
                name=sess.title[:100],
                category="ai_automation",
                description=f"{sess.provider.capitalize()} session on {sess.device_id}",
                properties={
                    "provider": sess.provider,
                    "device_id": sess.device_id,
                    "session_id": sess.session_id,
                    "created_at": sess.created_at,
                    # Logical identity in place of the raw file:/// locator.
                    "source_reference": sess.source_reference,
                    "source_token": self._token(sess.source_uri),
                },
            )

            # Edge: Workflow -> PART_OF -> Device
            edge_dev_key = f"{wf_key}:PART_OF:{dev_key}"
            edges[edge_dev_key] = MapEdge(
                stable_key=edge_dev_key,
                source_stable_key=wf_key,
                target_stable_key=dev_key,
                relation_type_id="PART_OF",
                confidence=1.0,
                source_kind="imported",
            )

            # 3. Project Node
            if sess.cwd:
                proj_name = self._safe_display_name(Path(sess.cwd).name or "workspace", "workspace")
                proj_key = f"project:{self._slugify(proj_name)}:{hashlib.sha256(sess.cwd.encode('utf-8')).hexdigest()}"
                if proj_key not in nodes:
                    nodes[proj_key] = MapNode(
                        stable_key=proj_key,
                        entity_type_id="Project",
                        name=proj_name,
                        category="core",
                        # Opaque token replaces the raw absolute working directory.
                        properties={"cwd_token": self._token(sess.cwd)},
                    )
                edge_proj_key = f"{wf_key}:PART_OF:{proj_key}"
                edges[edge_proj_key] = MapEdge(
                    stable_key=edge_proj_key,
                    source_stable_key=wf_key,
                    target_stable_key=proj_key,
                    relation_type_id="PART_OF",
                    confidence=1.0,
                    source_kind="imported",
                )

            # 4. Tool Nodes
            for tool_name in sess.tools:
                t_slug = self._slugify(tool_name)
                tool_key = f"tool:{t_slug}"
                if tool_key not in nodes:
                    nodes[tool_key] = MapNode(
                        stable_key=tool_key,
                        entity_type_id="Tool",
                        name=tool_name,
                        category="ai_automation",
                    )
                edge_tool_key = f"{wf_key}:USES:{tool_key}"
                edges[edge_tool_key] = MapEdge(
                    stable_key=edge_tool_key,
                    source_stable_key=wf_key,
                    target_stable_key=tool_key,
                    relation_type_id="USES",
                    confidence=1.0,
                    source_kind="imported",
                )

            # 5. Artifact Nodes
            for art_name in sess.artifacts:
                art_slug = self._slugify(art_name)
                art_key = f"artifact:{art_slug}"
                if art_key not in nodes:
                    nodes[art_key] = MapNode(
                        stable_key=art_key,
                        entity_type_id="Artifact",
                        name=art_name,
                        category="data_validation",
                    )
                edge_art_key = f"{wf_key}:PRODUCES:{art_key}"
                edges[edge_art_key] = MapEdge(
                    stable_key=edge_art_key,
                    source_stable_key=wf_key,
                    target_stable_key=art_key,
                    relation_type_id="PRODUCES",
                    confidence=1.0,
                    source_kind="imported",
                )

            # 6. Decision Nodes
            for idx, dec_text in enumerate(sess.decisions):
                dec_hash = hashlib.sha256(dec_text.encode()).hexdigest()[:8]
                dec_key = f"decision:{sess.session_id[:8]}:{dec_hash}"
                if dec_key not in nodes:
                    nodes[dec_key] = MapNode(
                        stable_key=dec_key,
                        entity_type_id="Decision",
                        name=dec_text[:80],
                        category="core",
                        properties={"detail": dec_text},
                    )
                edge_dec_key = f"{dec_key}:SUPPORTS:{wf_key}"
                edges[edge_dec_key] = MapEdge(
                    stable_key=edge_dec_key,
                    source_stable_key=dec_key,
                    target_stable_key=wf_key,
                    relation_type_id="SUPPORTS",
                    confidence=0.9,
                    source_kind="imported",
                )

        return MapExport.model_validate(
            {
                "schema": "sion-map-export/v1",
                "source": source_label,
                "expected_node_count": len(nodes),
                "expected_edge_count": len(edges),
                "nodes": list(nodes.values()),
                "edges": list(edges.values()),
            }
        )

    @staticmethod
    def generate_mermaid_graph(export: MapExport, max_nodes: int = 80) -> str:
        lines = ["flowchart TD"]
        selected_nodes = export.nodes[:max_nodes]
        selected_keys = {n.stable_key for n in selected_nodes}

        for node in selected_nodes:
            safe_name = node.name.replace('"', "'").replace("\n", " ")
            nid = re.sub(r"[^\w]", "_", node.stable_key)
            if node.entity_type_id == "Project":
                lines.append(f'    {nid}[["Project: {safe_name}"]]')
            elif node.entity_type_id == "SystemComponent":
                lines.append(f'    {nid}(("{safe_name}"))')
            elif node.entity_type_id == "Workflow":
                lines.append(f'    {nid}["Workflow: {safe_name}"]')
            elif node.entity_type_id == "Tool":
                lines.append(f'    {nid}(["Tool: {safe_name}"])')
            elif node.entity_type_id == "Artifact":
                lines.append(f'    {nid}[/"Artifact: {safe_name}"/]')
            elif node.entity_type_id == "Decision":
                lines.append(f'    {nid}{{"Decision: {safe_name}"}}')
            else:
                lines.append(f'    {nid}["{node.entity_type_id}: {safe_name}"]')

        for edge in export.edges:
            if edge.source_stable_key in selected_keys and edge.target_stable_key in selected_keys:
                src_id = re.sub(r"[^\w]", "_", edge.source_stable_key)
                tgt_id = re.sub(r"[^\w]", "_", edge.target_stable_key)
                lines.append(f"    {src_id} -->|{edge.relation_type_id}| {tgt_id}")

        return "\n".join(lines)

    @staticmethod
    def export_to_postgres_sql(export: MapExport) -> str:
        sql_lines = [
            "-- =====================================================================",
            "-- Sion Core Ontology - PostgreSQL Knowledge Graph Dump",
            f"-- Generated: {datetime.now(timezone.utc).isoformat()}",
            f"-- Total Entities: {len(export.nodes)}",
            f"-- Total Relations: {len(export.edges)}",
            "-- =====================================================================",
            "BEGIN;\n",
            "-- 1. Core Entity Types",
            """INSERT INTO entity_types (id, label, parent_type_id, schema_uri, properties) VALUES
  ('Entity', 'Entity', NULL, NULL, '{}'::jsonb),
  ('Project', 'Project', 'Entity', NULL, '{}'::jsonb),
  ('Tool', 'Tool', 'Entity', NULL, '{}'::jsonb),
  ('Concept', 'Concept', 'Entity', NULL, '{}'::jsonb),
  ('Document', 'Document', 'Entity', NULL, '{}'::jsonb),
  ('Artifact', 'Artifact', 'Entity', NULL, '{}'::jsonb),
  ('Dataset', 'Dataset', 'Artifact', NULL, '{}'::jsonb),
  ('SystemComponent', 'System Component', 'Entity', NULL, '{}'::jsonb),
  ('Workflow', 'Workflow', 'Entity', NULL, '{}'::jsonb),
  ('Decision', 'Decision', 'Entity', NULL, '{}'::jsonb),
  ('Deliverable', 'Deliverable', 'Artifact', NULL, '{}'::jsonb)
ON CONFLICT (id) DO NOTHING;\n""",
            "-- 2. Core Relation Types",
            """INSERT INTO relation_types (
  id, label, inverse_type_id, source_type_id, target_type_id,
  transitive, is_symmetric, properties
) VALUES
  ('RELATED_TO', 'Related to', NULL, NULL, NULL, FALSE, TRUE, '{}'::jsonb),
  ('PART_OF', 'Part of', NULL, NULL, NULL, TRUE, FALSE, '{}'::jsonb),
  ('USES', 'Uses', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('PRODUCES', 'Produces', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('DERIVED_FROM', 'Derived from', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('REFERENCES', 'References', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('IMPLEMENTS', 'Implements', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('DEPENDS_ON', 'Depends on', NULL, NULL, NULL, TRUE, FALSE, '{}'::jsonb),
  ('CONNECTS_TO', 'Connects to', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('SUPPORTS', 'Supports', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('EXTRACTED_FROM', 'Extracted from', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('EVIDENCED_BY', 'Evidenced by', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('SUPERSEDES', 'Supersedes', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb),
  ('VERSION_OF', 'Version of', NULL, NULL, NULL, FALSE, FALSE, '{}'::jsonb)
ON CONFLICT (id) DO NOTHING;\n""",
            "-- 3. Entities",
        ]

        def _sql_str(s: str | None) -> str:
            if s is None:
                return "NULL"
            escaped = s.replace("'", "''")
            return f"'{escaped}'"

        for node in export.nodes:
            props_json = json.dumps(node.properties or {}, ensure_ascii=False).replace("'", "''")
            sql_lines.append(
                f"INSERT INTO entities (id, stable_key, entity_type_id, name, description, category, properties, created_at, updated_at) "
                f"VALUES (gen_random_uuid(), {_sql_str(node.stable_key)}, {_sql_str(node.entity_type_id)}, {_sql_str(node.name)}, "
                f"{_sql_str(node.description)}, {_sql_str(node.category)}, '{props_json}'::jsonb, NOW(), NOW()) "
                f"ON CONFLICT (stable_key) DO NOTHING;"
            )

        sql_lines.append("\n-- 4. Relations")
        for edge in export.edges:
            props_json = json.dumps(edge.properties or {}, ensure_ascii=False).replace("'", "''")
            conf = edge.confidence if edge.confidence is not None else 1.0
            sql_lines.append(
                f"INSERT INTO relations (id, stable_key, source_entity_id, target_entity_id, relation_type_id, confidence, verification_state, source_kind, properties, created_at) "
                f"SELECT gen_random_uuid(), {_sql_str(edge.stable_key)}, s.id, t.id, {_sql_str(edge.relation_type_id)}, {conf}, "
                f"{_sql_str(edge.verification_state)}, {_sql_str(edge.source_kind)}, '{props_json}'::jsonb, NOW() "
                f"FROM entities s, entities t "
                f"WHERE s.stable_key = {_sql_str(edge.source_stable_key)} AND t.stable_key = {_sql_str(edge.target_stable_key)} "
                f"ON CONFLICT (stable_key) DO NOTHING;"
            )

        sql_lines.append("\nCOMMIT;\n")
        return "\n".join(sql_lines)
