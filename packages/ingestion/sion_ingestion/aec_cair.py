from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
import shlex
import subprocess
from typing import Any


READ_ONLY_TOOLS = frozenset(
    {
        "aec.get_object",
        "aec.query_global_memory",
        "aec.graph_backend_plan",
        "aec.graph_hydradb_preview",
    }
)


class AecCairError(RuntimeError):
    """Raised when the optional Ontology/CAIR bridge cannot return trusted context."""


@dataclass(frozen=True)
class AecCairConfig:
    command: tuple[str, ...]
    repository_root: Path
    timeout_seconds: float = 20.0

    @classmethod
    def from_env(cls) -> "AecCairConfig | None":
        root = os.getenv("SION_AEC_ONTOLOGY_ROOT")
        if not root:
            return None
        raw_command = os.getenv("SION_AEC_MCP_COMMAND", "aec-mcp")
        command = tuple(shlex.split(raw_command, posix=os.name != "nt"))
        if not command:
            raise AecCairError("SION_AEC_MCP_COMMAND must not be empty")
        timeout = float(os.getenv("SION_AEC_MCP_TIMEOUT", "20"))
        if timeout <= 0 or timeout > 120:
            raise AecCairError("SION_AEC_MCP_TIMEOUT must be in (0, 120]")
        return cls(command=command, repository_root=Path(root).expanduser().resolve(), timeout_seconds=timeout)


class AecCairAdapter:
    """Read-only federation adapter for khs0927/Ontology.

    Sion remains responsible for its own canonical database. CAIR data is queried
    through Ontology's MCP boundary and is never written into Sion implicitly.
    """

    def __init__(self, config: AecCairConfig):
        self.config = config

    @property
    def enabled(self) -> bool:
        return self.config.repository_root.is_dir()

    def call(self, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if tool not in READ_ONLY_TOOLS:
            raise AecCairError(f"tool is not allowed through the read-only CAIR adapter: {tool}")
        if not self.enabled:
            raise AecCairError(f"Ontology repository root not found: {self.config.repository_root}")

        request = "\n".join(
            [
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "sion-ontology-platform", "version": "0.1.0"}},
                    },
                    separators=(",", ":"),
                ),
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, separators=(",", ":")),
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": tool, "arguments": arguments or {}},
                    },
                    separators=(",", ":"),
                ),
                "",
            ]
        )
        command = [*self.config.command, "--root", str(self.config.repository_root)]
        try:
            completed = subprocess.run(
                command,
                input=request,
                text=True,
                capture_output=True,
                timeout=self.config.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AecCairError(f"failed to execute Ontology MCP: {exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or f"exit code {completed.returncode}"
            raise AecCairError(f"Ontology MCP failed: {detail}")

        responses: list[dict[str, Any]] = []
        for line in completed.stdout.splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AecCairError("Ontology MCP returned invalid JSON") from exc
            if isinstance(value, dict):
                responses.append(value)

        response = next((row for row in responses if row.get("id") == 2), None)
        if response is None:
            raise AecCairError("Ontology MCP returned no tool response")
        if "error" in response:
            raise AecCairError(f"Ontology MCP tool error: {response['error']}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise AecCairError("Ontology MCP returned an invalid tool result")
        structured = result.get("structuredContent")
        if not isinstance(structured, dict):
            raise AecCairError("Ontology MCP result has no structuredContent")
        if structured.get("status") == "FAILED":
            raise AecCairError(str(structured.get("error") or "Ontology MCP tool failed"))
        return structured

    def query_global_memory(self, question: str, *, top_k: int = 10, project_id: str | None = None) -> dict[str, Any]:
        if not question.strip():
            raise AecCairError("question must not be empty")
        if not 0 <= top_k <= 100:
            raise AecCairError("top_k must be between 0 and 100")
        arguments: dict[str, Any] = {"question": question, "top_k": top_k}
        if project_id:
            arguments["project_id"] = project_id
        return self.call("aec.query_global_memory", arguments)

    def get_object(self, object_id: str) -> dict[str, Any]:
        if not object_id.strip():
            raise AecCairError("object_id must not be empty")
        return self.call("aec.get_object", {"object_id": object_id})

    def graph_backend_plan(self, **requirements: bool) -> dict[str, Any]:
        allowed = {"local_only", "requires_sparql", "object_store_durability", "distributed_compute", "neo4j_protocol"}
        unknown = set(requirements) - allowed
        if unknown:
            raise AecCairError(f"unknown graph requirements: {', '.join(sorted(unknown))}")
        return self.call("aec.graph_backend_plan", requirements)
