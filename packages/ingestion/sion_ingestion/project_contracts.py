from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any


class ProjectContractCatalogError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProjectContractCatalog:
    path: Path

    @classmethod
    def from_env(cls) -> "ProjectContractCatalog | None":
        raw = os.getenv("SION_PROJECT_CONTRACTS_PATH")
        if not raw:
            return None
        return cls(Path(raw))

    @property
    def enabled(self) -> bool:
        return self.path.is_file()

    def read(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            raise ProjectContractCatalogError(f"project contract registry not found: {self.path}")
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectContractCatalogError(f"invalid project contract registry: {exc}") from exc

        rows = payload.get("project_contracts")
        if not isinstance(rows, list):
            raise ProjectContractCatalogError("project_contracts must be a list")

        seen: set[str] = set()
        normalized: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ProjectContractCatalogError("each project contract must be an object")
            contract_id = row.get("id")
            producer = row.get("producer")
            consumers = row.get("consumers")
            if not isinstance(contract_id, str) or not contract_id:
                raise ProjectContractCatalogError("project contract id is required")
            if contract_id in seen:
                raise ProjectContractCatalogError(f"duplicate project contract id: {contract_id}")
            if not isinstance(producer, str) or not producer.startswith("khs0927/"):
                raise ProjectContractCatalogError(f"invalid producer for {contract_id}")
            if (
                not isinstance(consumers, list)
                or not consumers
                or any(not isinstance(item, str) or not item.startswith("khs0927/") for item in consumers)
            ):
                raise ProjectContractCatalogError(f"invalid consumers for {contract_id}")
            if not row.get("schema") and not row.get("contract"):
                raise ProjectContractCatalogError(f"schema or contract required for {contract_id}")
            verification = row.get("verification")
            if not isinstance(verification, dict):
                raise ProjectContractCatalogError(f"verification required for {contract_id}")
            status = verification.get("status")
            allowed_status = {
                "verified_in_ci",
                "producer_verified_consumer_pending",
                "reference_contract_verified",
                "partial_consumers_verified",
                "declared",
            }
            if status not in allowed_status:
                raise ProjectContractCatalogError(
                    f"invalid verification status for {contract_id}: {status}"
                )
            evidence = verification.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                raise ProjectContractCatalogError(
                    f"verification evidence required for {contract_id}"
                )
            if not isinstance(verification.get("real_cad_e2e"), bool):
                raise ProjectContractCatalogError(
                    f"real_cad_e2e boolean required for {contract_id}"
                )

            consumers = row.get("consumers")
            verified_consumers = row.get("verified_consumers")
            pending_consumers = row.get("pending_consumers")
            if (
                not isinstance(consumers, list)
                or not isinstance(verified_consumers, list)
                or not isinstance(pending_consumers, list)
            ):
                raise ProjectContractCatalogError(
                    f"consumer verification lists required for {contract_id}"
                )
            declared = set(consumers)
            verified = set(verified_consumers)
            pending = set(pending_consumers)
            if verified & pending:
                raise ProjectContractCatalogError(
                    f"consumer cannot be both verified and pending for {contract_id}"
                )
            if verified | pending != declared:
                raise ProjectContractCatalogError(
                    f"every consumer must be verified or pending for {contract_id}"
                )
            if status == "verified_in_ci" and pending:
                raise ProjectContractCatalogError(
                    f"verified_in_ci cannot have pending consumers for {contract_id}"
                )
            if status == "partial_consumers_verified" and (not verified or not pending):
                raise ProjectContractCatalogError(
                    f"partial consumer verification requires both sets for {contract_id}"
                )
            seen.add(contract_id)
            normalized.append(dict(row))
        return normalized

    def find(
        self,
        *,
        producer: str | None = None,
        consumer: str | None = None,
        schema: str | None = None,
        verification_status: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self.read()
        if producer is not None:
            rows = [row for row in rows if row.get("producer") == producer]
        if consumer is not None:
            rows = [row for row in rows if consumer in row.get("consumers", [])]
        if schema is not None:
            rows = [row for row in rows if row.get("schema") == schema]
        if verification_status is not None:
            rows = [
                row
                for row in rows
                if (row.get("verification") or {}).get("status") == verification_status
            ]
        return rows
