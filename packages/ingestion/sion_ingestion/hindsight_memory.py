from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


class HindsightMemoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class HindsightConfig:
    base_url: str
    bank_id: str
    api_key: str | None = None
    timeout_seconds: float = 20.0

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

        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise HindsightMemoryError(
                "SION_HINDSIGHT_URL must be an absolute http(s) URL without embedded credentials"
            )
        host = (parsed.hostname or "").lower()
        local = host in {"localhost", "127.0.0.1", "::1"}
        if not local and not api_key:
            raise HindsightMemoryError(
                "SION_HINDSIGHT_API_KEY is required for a non-loopback Hindsight URL"
            )

        timeout = float(os.getenv("SION_HINDSIGHT_TIMEOUT", "20"))
        if timeout <= 0 or timeout > 120:
            raise HindsightMemoryError("SION_HINDSIGHT_TIMEOUT must be in (0, 120]")

        return cls(
            base_url=base_url.rstrip("/"),
            bank_id=bank_id,
            api_key=api_key,
            timeout_seconds=timeout,
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
        return f"{self.config.base_url}/v1/default/banks/{bank}{suffix}"

    def _request(self, suffix: str, payload: dict[str, Any]) -> Any:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
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
        project = Path(cwd).name if cwd else ""
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
        return "\n".join(lines), metadata

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
            "canonical": False,
            "advisory": True,
            "result": result,
        }

    def reflect(self, query: str) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            raise HindsightMemoryError("reflect query must not be empty")
        result = self._request("/reflect", {"query": query.strip()})
        return {
            "source": "hindsight",
            "operation": "reflect",
            "bank_id": self.config.bank_id,
            "canonical": False,
            "advisory": True,
            "result": result,
        }
