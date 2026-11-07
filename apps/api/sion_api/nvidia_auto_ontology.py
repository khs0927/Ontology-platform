"""Read-only, opt-in NVIDIA Auto Ontology federation for the Sion API.

NVIDIA owns its semantic catalog and runs any generated SQL against its *own*
configured data connections. Sion never gives this bridge a Sion DB session,
promotes candidate terms, or executes returned SQL.

API contract pinned to NVIDIA/auto-ontology c447003f72a822301e927196a4ecb5b597c308d5.
The calls deliberately target the authenticated *frontend* (:3000), not the
internal FastAPI backend (:3001), whose trusted identity header is not public auth.
"""

from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

SOURCE = "NVIDIA/auto-ontology"
UPSTREAM_REVISION = "c447003f72a822301e927196a4ecb5b597c308d5"
MAX_BYTES = 2_000_000
MAX_EVENTS = 2048
MAX_ROWS = 100


class NvidiaBridgeError(Exception):
    """Safe, credential-free error to expose at the API boundary."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class NvidiaBridgeConfig:
    base_url: str
    api_token: str
    enable_ask: bool = False
    timeout_seconds: int = 120

    @classmethod
    def from_env(cls) -> "NvidiaBridgeConfig | None":
        url = os.getenv("SION_NVIDIA_AUTO_ONTOLOGY_URL", "").strip().rstrip("/")
        token = os.getenv("SION_NVIDIA_AUTO_ONTOLOGY_API_TOKEN", "").strip()
        if not url and not token:
            return None
        if not url or not token:
            raise RuntimeError("NVIDIA federation requires URL and API token together")
        # Do not permit secret-bearing URLs, paths, DNS-less hosts or insecure
        # non-loopback HTTP. The target is admin configured, never caller supplied.
        parsed = urlsplit(url)
        try:
            port = parsed.port
        except ValueError:
            raise RuntimeError("invalid NVIDIA federation URL") from None
        hostname = parsed.hostname
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or not hostname
            or port == 0
        ):
            raise RuntimeError("invalid NVIDIA federation URL")
        is_loopback = hostname == "localhost"
        try:
            is_loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            pass
        if parsed.scheme != "https" and not (parsed.scheme == "http" and is_loopback):
            raise RuntimeError("NVIDIA federation requires HTTPS (except loopback development)")
        if parsed.scheme not in {"http", "https"}:
            raise RuntimeError("invalid NVIDIA federation URL scheme")
        raw_timeout = os.getenv("SION_NVIDIA_AUTO_ONTOLOGY_TIMEOUT_SECONDS", "120")
        try:
            timeout = int(raw_timeout)
        except ValueError:
            raise RuntimeError("invalid NVIDIA federation timeout") from None
        if not 5 <= timeout <= 300:
            raise RuntimeError("NVIDIA federation timeout must be between 5 and 300 seconds")
        return cls(
            base_url=url,
            api_token=token,
            enable_ask=os.getenv("SION_NVIDIA_AUTO_ONTOLOGY_ENABLE_ASK", "false")
            .strip()
            .lower() in {"1", "true", "yes", "on"},
            timeout_seconds=timeout,
        )


class NvidiaQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)

    @field_validator("question")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be blank")
        return value


def _check_status(status: int) -> None:
    # Never relay upstream error bodies: they can include SQL, URLs or credentials.
    if status in {401, 403}:
        raise NvidiaBridgeError(502, "NVIDIA credentials or permissions were rejected")
    if status == 429:
        raise NvidiaBridgeError(503, "NVIDIA rate limit reached")
    if status == 409:
        raise NvidiaBridgeError(503, "NVIDIA semantic layer is not ready")
    if status != 200:
        raise NvidiaBridgeError(502, "NVIDIA upstream request failed")


def _parse_rows(raw: Any) -> list[dict[str, Any]]:
    # Exact formats supported by NVIDIA's reference MCP chat.py client.
    if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], str):
        try:
            raw = json.loads(raw[0])
        except (ValueError, TypeError):
            raise NvidiaBridgeError(502, "NVIDIA returned invalid SQL rows") from None
    if isinstance(raw, dict):
        raw = [raw]
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise NvidiaBridgeError(502, "NVIDIA returned invalid SQL rows")
    return [row for row in raw if isinstance(row, dict)]


class NvidiaBridge:
    def __init__(self, config: NvidiaBridgeConfig, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self.transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.config.base_url + "/",
            headers={"x-api-key": self.config.api_token},
            timeout=httpx.Timeout(float(self.config.timeout_seconds), connect=5.0),
            transport=self.transport,
            follow_redirects=False,  # Avoid forwarding API tokens on redirects.
            trust_env=False,
        )

    async def readiness(self) -> dict[str, Any]:
        """Probe actual NVIDIA semantic compilation status without invoking an LLM.

        A compiled semantic catalog does NOT prove a connected database can run
        SQL. Database execution stays unknown until a separately approved,
        controlled live query is performed.
        """
        try:
            async with self._client() as client:
                async with client.stream("GET", "api/semantic-compilation/status") as response:
                    _check_status(response.status_code)
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_BYTES:
                            raise NvidiaBridgeError(502, "NVIDIA readiness response exceeded size limit")
            parsed = json.loads(raw)
        except NvidiaBridgeError:
            raise
        except (httpx.HTTPError, UnicodeDecodeError, ValueError):
            raise NvidiaBridgeError(502, "NVIDIA readiness response unavailable or invalid") from None
        if not isinstance(parsed, dict) or type(parsed.get("calculated")) is not bool:
            raise NvidiaBridgeError(502, "NVIDIA readiness schema did not match the pinned API")
        return {
            "source": SOURCE,
            "source_revision": UPSTREAM_REVISION,
            "canonical": False,
            "read_only": True,
            "upstream_reachable": True,
            "semantic_calculated": parsed["calculated"],
            "compilation_running": parsed.get("running") is True,
            "can_execute_sql": None,
            "reason": "Database connectivity and SQL execution were not verified by this probe",
        }

    async def terms(self, query: str | None, skip: int, limit: int) -> dict[str, Any]:
        try:
            async with self._client() as client:
                async with client.stream(
                    "GET",
                    "api/terms",
                    params={"query": query, "skip": skip, "limit": limit},
                ) as response:
                    _check_status(response.status_code)
                    collected = bytearray()
                    async for chunk in response.aiter_bytes():
                        collected.extend(chunk)
                        if len(collected) > MAX_BYTES:
                            raise NvidiaBridgeError(502, "NVIDIA glossary response exceeded size limit")
            payload = json.loads(collected)
        except NvidiaBridgeError:
            raise
        except (httpx.HTTPError, ValueError, UnicodeDecodeError):
            raise NvidiaBridgeError(502, "NVIDIA glossary response unavailable or invalid") from None

        if not isinstance(payload, dict) or not isinstance(payload.get("terms"), list):
            raise NvidiaBridgeError(502, "NVIDIA glossary schema did not match the pinned API")
        candidates: list[dict[str, Any]] = []
        for term in payload["terms"][:limit]:
            if not isinstance(term, dict):
                continue
            term_id = term.get("id")
            name = term.get("name")
            if not isinstance(term_id, str) or not isinstance(name, str) or not name.strip():
                continue
            candidates.append(
                {
                    "source_term_id": term_id,
                    "name": name,
                    "description": term.get("description") if isinstance(term.get("description"), str) else None,
                    "suggested_entity_type": "Concept",
                    "verification_state": "unverified",
                    "source_kind": "inferred",
                    # Upstream certification never equals Sion human verification.
                    "upstream_name_certified": term.get("name_certified") is True,
                    "upstream_description_certified": term.get("description_certified") is True,
                }
            )
        return {
            "source": SOURCE,
            "source_revision": UPSTREAM_REVISION,
            "canonical": False,
            "read_only": True,
            "promoted": False,
            "count": len(candidates),
            "total": payload.get("total") if isinstance(payload.get("total"), int) else None,
            "candidates": candidates,
        }

    async def ask(self, question: str) -> dict[str, Any]:
        if not self.config.enable_ask:
            raise NvidiaBridgeError(503, "NVIDIA question execution is disabled")
        answer: dict[str, Any] | None = None
        completed = False
        bytes_seen = 0
        events_seen = 0
        try:
            async with self._client() as client:
                async with client.stream(
                    "POST",
                    "api/chat/completions",
                    json={"question": question},  # No evidence, conversation or arbitrary DB selection.
                    headers={"Accept": "text/event-stream"},
                ) as response:
                    _check_status(response.status_code)
                    if "text/event-stream" not in response.headers.get("content-type", "").lower():
                        raise NvidiaBridgeError(502, "NVIDIA did not return an event stream")
                    async for line in response.aiter_lines():
                        bytes_seen += len(line.encode("utf-8"))
                        if bytes_seen > MAX_BYTES:
                            raise NvidiaBridgeError(502, "NVIDIA answer exceeded size limit")
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            completed = True
                            break
                        if not raw:
                            continue
                        events_seen += 1
                        if events_seen > MAX_EVENTS:
                            raise NvidiaBridgeError(502, "NVIDIA answer exceeded event limit")
                        try:
                            event = json.loads(raw)
                        except ValueError:
                            raise NvidiaBridgeError(502, "NVIDIA returned malformed event data") from None
                        if not isinstance(event, dict):
                            raise NvidiaBridgeError(502, "NVIDIA returned malformed event data")
                        if event.get("type") == "error":
                            raise NvidiaBridgeError(502, "NVIDIA agent could not answer")
                        if event.get("type") == "result":
                            if answer is not None or not isinstance(event.get("answer"), dict):
                                raise NvidiaBridgeError(502, "NVIDIA returned ambiguous results")
                            answer = event["answer"]
        except NvidiaBridgeError:
            raise
        except (httpx.HTTPError, UnicodeDecodeError):
            raise NvidiaBridgeError(502, "NVIDIA answer stream unavailable") from None

        if not completed or answer is None:
            raise NvidiaBridgeError(502, "NVIDIA answer stream did not complete")
        rows = _parse_rows(answer.get("sql_response_from_db") or answer.get("result"))
        result_sql = answer.get("sql_code")
        result_answer = answer.get("response")
        if not isinstance(result_sql, str) or not isinstance(result_answer, str):
            raise NvidiaBridgeError(502, "NVIDIA answer schema did not match the pinned API")
        return {
            "source": SOURCE,
            "source_revision": UPSTREAM_REVISION,
            "canonical": False,
            "read_only": True,
            "verification_state": "unverified",
            "answer": result_answer,
            "sql": result_sql,
            "rows": rows[:MAX_ROWS],
            "row_count": len(rows),
            "truncated": len(rows) > MAX_ROWS,
            "executed_by": "nvidia-auto-ontology",
            "executed_by_sion": False,
        }


def register(
    app: FastAPI,
    read_knowledge: Any,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """Mount a tiny allowlisted surface. No NVIDIA writes, resets or compiles."""
    config = NvidiaBridgeConfig.from_env()
    bridge = NvidiaBridge(config, transport) if config is not None else None
    app.state.nvidia_auto_ontology = bridge

    @app.get("/api/v1/nvidia/status", dependencies=[Depends(read_knowledge)])
    def nvidia_status() -> dict[str, Any]:
        return {
            "source": SOURCE,
            "source_revision": UPSTREAM_REVISION,
            "configured": bridge is not None,
            "ask_enabled": bool(bridge is not None and bridge.config.enable_ask),
            "canonical": False,
            "read_only": True,
            # This is configuration only, not an upstream health or SQL readiness check.
            "upstream_verified": False,
        }

    def require_bridge() -> NvidiaBridge:
        if bridge is None:
            raise HTTPException(status_code=503, detail="NVIDIA federation is not configured")
        return bridge

    @app.get("/api/v1/nvidia/readiness", dependencies=[Depends(read_knowledge)])
    async def nvidia_readiness() -> dict[str, Any]:
        try:
            return await require_bridge().readiness()
        except NvidiaBridgeError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None

    @app.get("/api/v1/nvidia/terms", dependencies=[Depends(read_knowledge)])
    async def nvidia_terms(
        query: str | None = Query(default=None, max_length=200),
        skip: int = Query(default=0, ge=0, le=10000),
        limit: int = Query(default=20, ge=1, le=50),
    ) -> dict[str, Any]:
        try:
            return await require_bridge().terms(query, skip, limit)
        except NvidiaBridgeError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None

    @app.post("/api/v1/nvidia/ask", dependencies=[Depends(read_knowledge)])
    async def nvidia_ask(payload: NvidiaQuestion) -> dict[str, Any]:
        try:
            return await require_bridge().ask(payload.question)
        except NvidiaBridgeError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
