from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import ipaddress
import os
import re
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


class HindsightMemoryError(RuntimeError):
    pass


HINDSIGHT_API_PROFILE = "v0.10.2"

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|passwd)"
    r"(\\s*[:=]\\s*)([^\\s,;]+)"
)
_SECRET_PREFIXES = (
    re.compile(r"\\bsk-[A-Za-z0-9_-]{16,}\\b"),
    re.compile(r"\\bgh[pousr]_[A-Za-z0-9]{20,}\\b"),
    re.compile(r"\\bgithub_pat_[A-Za-z0-9_]{20,}\\b"),
    re.compile(r"\\bcfat_[A-Za-z0-9_-]{20,}\\b"),
    re.compile(r"\\bapikey_[A-Za-z0-9_-]{20,}\\b"),
)


def _redact_obvious_secrets(value: str) -> str:
    redacted = _SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        value,
    )
    for pattern in _SECRET_PREFIXES:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def _env_true(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class HindsightConfig:
    base_url: str
    bank_id: str
    api_key: str | None = field(default=None, repr=False)
    timeout_seconds: float = 20.0
    api_profile: str = HINDSIGHT_API_PROFILE
    allow_remote_egress: bool = False

    def __post_init__(self) -> None:
        if self.api_profile != HINDSIGHT_API_PROFILE:
            raise HindsightMemoryError(
                f"Hindsight adapter profile is pinned to {HINDSIGHT_API_PROFILE}"
            )
        if not self.bank_id.strip():
            raise HindsightMemoryError("Hindsight bank_id must not be empty")
        if not 0 < self.timeout_seconds <= 120:
            raise HindsightMemoryError("Hindsight timeout must be in (0, 120]")

        parsed = urlparse(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise HindsightMemoryError(
                "Hindsight base_url must be an absolute http(s) URL without credentials, query, or fragment"
            )
        host = (parsed.hostname or "").lower()
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = host == "localhost"
        if not local:
            if parsed.scheme != "https":
                raise HindsightMemoryError("non-loopback Hindsight requires https")
            if not self.allow_remote_egress:
                raise HindsightMemoryError(
                    "remote Hindsight egress requires explicit allow_remote_egress"
                )
            if not self.api_key:
                raise HindsightMemoryError(
                    "Hindsight API key is required for a non-loopback URL"
                )

    @classmethod
    def from_env(cls) -> "HindsightConfig | None":
        base_url = os.getenv("SION_HINDSIGHT_URL", "").strip()
        bank_id = os.getenv("SION_HINDSIGHT_BANK_ID", "").strip()
        api_key = os.getenv("SION_HINDSIGHT_API_KEY", "").strip() or None

        if not base_url and not bank_id:
            return None
        if not base_url or not bank_id:
            raise HindsightMemoryError(
                "SION_HINDSIGHT_URL and SION_HINDSIGHT_BANK_ID must be configured together"
            )

        try:
            timeout = float(os.getenv("SION_HINDSIGHT_TIMEOUT", "20"))
        except ValueError as exc:
            raise HindsightMemoryError(
                "SION_HINDSIGHT_TIMEOUT must be numeric"
            ) from exc

        return cls(
            base_url=base_url.rstrip("/"),
            bank_id=bank_id,
            api_key=api_key,
            timeout_seconds=timeout,
            allow_remote_egress=_env_true("SION_HINDSIGHT_ALLOW_REMOTE"),
        )


Transport = Callable[[Request, float], Any]


def _default_transport(request: Request, timeout: float):
    return urlopen(request, timeout=timeout)


class HindsightMemoryAdapter:
    """Optional advisory-memory boundary for Hindsight.

    Hindsight is never treated as Sion or CAIR canonical state. This adapter
    intentionally retains only normalized session summaries, not full local
    transcripts, source URIs, or absolute working-directory paths.
    """

    def __init__(
        self,
        config: HindsightConfig,
        *,
        transport: Transport = _default_transport,
    ) -> None:
        self.config = config
        self._transport = transport

    @property
    def enabled(self) -> bool:
        return True

    def _url(self, suffix: str) -> str:
        bank = quote(self.config.bank_id, safe="")
        return f"{self.config.base_url.rstrip('/')}/v1/default/banks/{bank}{suffix}"

    def _request(self, suffix: str, payload: dict[str, Any]) -> Any:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "sion-ontology-platform/0.1 hindsight-advisory/v0.10.2",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        request = Request(self._url(suffix), data=body, headers=headers, method="POST")
        try:
            response = self._transport(request, self.config.timeout_seconds)
            with response:
                raw = response.read()
                status = int(getattr(response, "status", 200))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise HindsightMemoryError(
                f"Hindsight returned HTTP {exc.code}: {detail[:1000]}"
            ) from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise HindsightMemoryError(f"Hindsight request failed: {exc}") from exc

        text = raw.decode("utf-8", errors="replace")
        if status < 200 or status >= 300:
            raise HindsightMemoryError(f"Hindsight returned HTTP {status}: {text[:1000]}")
        if not text.strip():
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}

    @staticmethod
    def _session_document_id(session: Any) -> str:
        identity = "|".join(
            [
                str(getattr(session, "provider", "")),
                str(getattr(session, "device_id", "")),
                str(getattr(session, "session_id", "")),
            ]
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
        provider = str(getattr(session, "provider", "agent") or "agent").lower()
        return f"sion-agent-{provider}-{digest}"

    @staticmethod
    def _session_summary(session: Any) -> tuple[str, dict[str, str]]:
        provider = str(getattr(session, "provider", "unknown") or "unknown")
        title = str(getattr(session, "title", "") or "").strip()
        created_at = str(getattr(session, "created_at", "") or "").strip()
        cwd = str(getattr(session, "cwd", "") or "").strip()
        project = re.split(r"[\\/]", cwd.rstrip("\\/"))[-1] if cwd else ""
        tools = sorted(str(v) for v in (getattr(session, "tools", set()) or set()))
        artifacts = sorted(str(v) for v in (getattr(session, "artifacts", set()) or set()))
        decisions = [
            str(v).strip()
            for v in (getattr(session, "decisions", []) or [])
            if str(v).strip()
        ]
        device_id = str(getattr(session, "device_id", "") or "")
        device_hash = hashlib.sha256(device_id.encode("utf-8")).hexdigest()[:12] if device_id else ""

        lines = [
            "Sion advisory agent-session summary.",
            f"Provider: {provider}",
            f"Title: {title or '(untitled)'}",
        ]
        if created_at:
            lines.append(f"Created: {created_at}")
        if project:
            lines.append(f"Project: {project}")
        if tools:
            lines.append("Tools used: " + ", ".join(tools))
        if artifacts:
            lines.append("Artifacts: " + ", ".join(artifacts))
        if decisions:
            lines.append("Durable decisions/outcomes:")
            lines.extend(f"- {item}" for item in decisions)

        metadata = {
            "source": "sion-agent-bridge",
            "provider": provider,
            "project": project,
            "device_hash": device_hash,
            "canonical": "false",
            "advisory": "true",
        }
        content = _redact_obvious_secrets("\n".join(lines))
        metadata = {
            key: _redact_obvious_secrets(value)
            for key, value in metadata.items()
        }
        return content, metadata

    def retain_agent_session(self, session: Any) -> dict[str, Any]:
        content, metadata = self._session_summary(session)
        item: dict[str, Any] = {
            "content": content,
            "context": "Sion advisory agent memory; never canonical CAIR/Sion knowledge",
            "document_id": self._session_document_id(session),
            "update_mode": "replace",
            "metadata": metadata,
            "tags": ["sion-agent", str(getattr(session, "provider", "unknown")), "advisory"],
        }
        timestamp = str(getattr(session, "created_at", "") or "").strip()
        if timestamp:
            item["timestamp"] = timestamp

        result = self._request("/memories", {"items": [item], "async": False})
        return {
            "status": "SUCCESS",
            "source": "hindsight",
            "bank_id": self.config.bank_id,
            "api_profile": self.config.api_profile,
            "document_id": item["document_id"],
            "canonical": False,
            "advisory": True,
            "result": result,
        }

    def recall(
        self,
        query: str,
        *,
        types: list[str] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            raise HindsightMemoryError("recall query must not be empty")
        payload: dict[str, Any] = {"query": query.strip()}
        if types is not None:
            allowed = {"world", "experience", "observation"}
            if not types or any(value not in allowed for value in types):
                raise HindsightMemoryError(
                    "recall types must contain only world, experience, observation"
                )
            payload["types"] = types
        result = self._request("/memories/recall", payload)
        return {
            "source": "hindsight",
            "operation": "recall",
            "bank_id": self.config.bank_id,
            "api_profile": self.config.api_profile,
            "canonical": False,
            "advisory": True,
            "result": result,
        }

