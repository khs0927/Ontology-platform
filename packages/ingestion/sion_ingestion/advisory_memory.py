"""Optional, non-canonical Hindsight memory sidecar for Sion agent sessions.

Only explicit durable decisions are retained by default. Raw transcripts,
source URIs, full working-directory paths, tool logs and secrets are excluded.
Hindsight failures never mutate or block Sion canonical persistence.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\b(?:api[_-]?key|token|password|secret)\s*[:=]\s*\S+", re.I),
    re.compile(r"authorization\s*:\s*bearer\s+\S+", re.I),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


@dataclass(frozen=True)
class HindsightConfig:
    enabled: bool = False
    base_url: str = "http://127.0.0.1:8888"
    api_key: str = field(default="", repr=False)
    bank_prefix: str = "sion-project"
    timeout_seconds: float = 20.0
    reflect_enabled: bool = False
    client_version: str = "0.10.2"

    def __post_init__(self):
        if not self.enabled:
            return
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Hindsight base_url must be absolute http(s)")
        if parsed.username or parsed.password:
            raise ValueError("credentials must not be embedded in Hindsight URL")
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = parsed.hostname.lower() == "localhost"
        if not loopback:
            if parsed.scheme != "https":
                raise ValueError("remote Hindsight requires https")
            if not self.api_key.strip():
                raise ValueError("remote Hindsight requires an API key")
        if not self.bank_prefix.strip():
            raise ValueError("Hindsight bank_prefix must be non-empty")
        if not 1 <= self.timeout_seconds <= 120:
            raise ValueError("Hindsight timeout must be between 1 and 120 seconds")
        if self.client_version != "0.10.2":
            raise ValueError("Sion Hindsight adapter is reviewed against client v0.10.2")

    @classmethod
    def from_env(cls) -> "HindsightConfig":
        enabled = os.getenv("SION_HINDSIGHT_ENABLED", "").strip().lower() in {
            "1", "true", "yes", "on",
        }
        reflect_enabled = os.getenv("SION_HINDSIGHT_REFLECT_ENABLED", "").strip().lower() in {
            "1", "true", "yes", "on",
        }
        timeout = float(os.getenv("SION_HINDSIGHT_TIMEOUT", "20"))
        return cls(
            enabled=enabled,
            base_url=os.getenv("SION_HINDSIGHT_URL", "http://127.0.0.1:8888").strip(),
            api_key=os.getenv("SION_HINDSIGHT_API_KEY", ""),
            bank_prefix=os.getenv("SION_HINDSIGHT_BANK_PREFIX", "sion-project").strip(),
            timeout_seconds=timeout,
            reflect_enabled=reflect_enabled,
        )


@dataclass(frozen=True)
class AdvisoryMemoryCandidate:
    bank_id: str
    document_id: str
    content: str
    context: str
    metadata: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateBatch:
    candidates: tuple[AdvisoryMemoryCandidate, ...]
    skipped_sensitive: int = 0
    skipped_empty: int = 0


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9._-]+", "-", value.lower().strip()).strip("-")
    return result or "unscoped"


def _project_label(session: Any) -> str:
    cwd = str(getattr(session, "cwd", "") or "").strip()
    if not cwd:
        return "unscoped"
    return _slug(Path(cwd).name)


def bank_id_for_project(project_label: str, prefix: str = "sion-project") -> str:
    label = _slug(project_label)
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()[:20]
    return f"{_slug(prefix)}::{digest}"


def _contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)


def prepare_advisory_candidates(
    sessions: Iterable[Any],
    *,
    bank_prefix: str = "sion-project",
) -> CandidateBatch:
    """Convert only explicit durable decisions into memory candidates.

    Session title, raw transcript, source_uri, full cwd, tools and device path
    are deliberately not copied into memory content or metadata.
    """
    candidates: list[AdvisoryMemoryCandidate] = []
    skipped_sensitive = 0
    skipped_empty = 0

    for session in sessions:
        provider = _slug(str(getattr(session, "provider", "unknown") or "unknown"))
        project = _project_label(session)
        bank_id = bank_id_for_project(project, bank_prefix)
        created_at = str(getattr(session, "created_at", "") or "")
        decisions = getattr(session, "decisions", []) or []

        for index, raw in enumerate(decisions):
            decision = str(raw or "").strip()
            if not decision:
                skipped_empty += 1
                continue
            if _contains_secret(decision):
                skipped_sensitive += 1
                continue
            stable = hashlib.sha256(
                f"{provider}\0{project}\0{decision}".encode("utf-8")
            ).hexdigest()
            candidates.append(
                AdvisoryMemoryCandidate(
                    bank_id=bank_id,
                    document_id=f"sion-decision-{stable}",
                    content=decision,
                    context="Sion agent decision; advisory memory only",
                    metadata={
                        "provider": provider,
                        "project": project,
                        "created_at": created_at,
                        "canonical": "false",
                        "memory_role": "advisory",
                    },
                )
            )

    return CandidateBatch(
        candidates=tuple(candidates),
        skipped_sensitive=skipped_sensitive,
        skipped_empty=skipped_empty,
    )


def _default_client_factory(config: HindsightConfig):
    try:
        from hindsight_client import Hindsight
    except ImportError as exc:
        raise RuntimeError(
            "Hindsight memory is enabled but hindsight-client is not installed; "
            "install hindsight-client==0.10.2"
        ) from exc
    return Hindsight(
        base_url=config.base_url,
        api_key=config.api_key or None,
        timeout=config.timeout_seconds,
        user_agent="sion-ontology-platform/0.1.0",
    )


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    if hasattr(value, "to_dict"):
        return _jsonable(value.to_dict())
    return str(value)


class HindsightAdvisoryMemory:
    """Best-effort advisory memory boundary.

    Recall/reflect results are never promoted to Sion canonical entities or
    relations by this adapter.
    """

    def __init__(
        self,
        config: HindsightConfig,
        *,
        client_factory: Callable[[HindsightConfig], Any] | None = None,
    ):
        self.config = config
        self._client_factory = client_factory or _default_client_factory
        self._client: Any | None = None

    @classmethod
    def from_env(cls) -> "HindsightAdvisoryMemory":
        return cls(HindsightConfig.from_env())

    def _client_or_raise(self):
        if not self.config.enabled:
            raise RuntimeError("Hindsight advisory memory is disabled")
        if self._client is None:
            self._client = self._client_factory(self.config)
        return self._client

    def preview(self, sessions: Iterable[Any]) -> dict[str, Any]:
        batch = prepare_advisory_candidates(
            sessions,
            bank_prefix=self.config.bank_prefix,
        )
        return {
            "status": "READY" if self.config.enabled else "DISABLED",
            "candidate_count": len(batch.candidates),
            "skipped_sensitive": batch.skipped_sensitive,
            "skipped_empty": batch.skipped_empty,
            "banks": sorted({row.bank_id for row in batch.candidates}),
            "canonical_mutation": False,
            "advisory": True,
        }

    def retain_sessions(self, sessions: Iterable[Any]) -> dict[str, Any]:
        batch = prepare_advisory_candidates(
            sessions,
            bank_prefix=self.config.bank_prefix,
        )
        if not self.config.enabled:
            return {
                "status": "DISABLED",
                "retained": 0,
                "candidate_count": len(batch.candidates),
                "skipped_sensitive": batch.skipped_sensitive,
                "skipped_empty": batch.skipped_empty,
                "failures": [],
                "canonical_mutation": False,
                "advisory": True,
            }

        client = self._client_or_raise()
        retained = 0
        failures: list[dict[str, str]] = []
        for candidate in batch.candidates:
            try:
                client.retain(
                    bank_id=candidate.bank_id,
                    content=candidate.content,
                    context=candidate.context,
                    document_id=candidate.document_id,
                )
                retained += 1
            except Exception as exc:
                failures.append(
                    {
                        "document_id": candidate.document_id,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        status = "SUCCESS" if not failures else ("PARTIAL" if retained else "DEGRADED")
        return {
            "status": status,
            "retained": retained,
            "candidate_count": len(batch.candidates),
            "skipped_sensitive": batch.skipped_sensitive,
            "skipped_empty": batch.skipped_empty,
            "failures": failures,
            "canonical_mutation": False,
            "advisory": True,
        }

    def recall(self, project_label: str, query: str) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("recall query must be non-empty")
        client = self._client_or_raise()
        bank_id = bank_id_for_project(project_label, self.config.bank_prefix)
        result = client.recall(bank_id=bank_id, query=query)
        return {
            "status": "SUCCESS",
            "bank_id": bank_id,
            "result": _jsonable(result),
            "canonical": False,
            "may_update_sion": False,
            "advisory": True,
        }

    def reflect(self, project_label: str, query: str) -> dict[str, Any]:
        if not self.config.reflect_enabled:
            return {
                "status": "BLOCKED",
                "reason": "Hindsight reflect is disabled by default",
                "canonical": False,
                "may_update_sion": False,
                "advisory": True,
            }
        if not query.strip():
            raise ValueError("reflect query must be non-empty")
        client = self._client_or_raise()
        bank_id = bank_id_for_project(project_label, self.config.bank_prefix)
        result = client.reflect(bank_id=bank_id, query=query)
        return {
            "status": "SUCCESS",
            "bank_id": bank_id,
            "result": _jsonable(result),
            "canonical": False,
            "may_update_sion": False,
            "advisory": True,
        }
