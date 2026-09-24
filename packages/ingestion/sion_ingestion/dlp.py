"""Dependency-free, fail-closed data loss prevention for ingestion payloads.

The scanner intentionally returns only sanitized metadata. Secret values are never
stored in findings, decision metadata, logs, or the sanitized payload.
"""

from __future__ import annotations

import hmac
import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any


class Classification(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED_PII = "RESTRICTED_PII"
    SECRET = "SECRET"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class DLPFinding:
    """A sanitized finding. ``path`` identifies a location, never a matched value."""

    path: str
    classification: Classification
    kind: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "classification": self.classification.value,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class DLPDecision:
    allowed: bool
    action: str
    sanitized_payload: Any
    findings: tuple[DLPFinding, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "action": self.action,
            "findings": [finding.to_dict() for finding in self.findings],
            "metadata": dict(self.metadata),
        }


_REDACTIONS = {
    Classification.SECRET: "[REDACTED:SECRET]",
    Classification.RESTRICTED_PII: "[REDACTED:PII]",
    Classification.CONFIDENTIAL: "[REDACTED:CONFIDENTIAL]",
    Classification.INTERNAL: "[REDACTED:INTERNAL]",
    Classification.UNKNOWN: "[REDACTED:UNKNOWN]",
}

_PATTERNS: tuple[tuple[str, Classification, re.Pattern[str]], ...] = (
    (
        "synthetic_secret",
        Classification.SECRET,
        re.compile(r"(?i)\b(?:sion[_-]?test[_-]?secret|sk[_-]?test|fake[_-]?secret)[_-][A-Za-z0-9_./+=-]{6,}\b"),
    ),
    (
        "bearer_token",
        Classification.SECRET,
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}\b"),
    ),
    (
        "authorization",
        Classification.SECRET,
        re.compile(r"(?i)\bauthorization\s*[:=]\s*(?!bearer\b)\S+(?:[ \t]+\S+)?"),
    ),
    (
        "private_key_header",
        Classification.SECRET,
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    ),
    (
        "dsn_credential",
        Classification.SECRET,
        re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|https?)://[^\s:/@]+:[^\s/@]+@"),
    ),
    (
        "email",
        Classification.RESTRICTED_PII,
        re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    ),
    (
        "phone",
        Classification.RESTRICTED_PII,
        re.compile(r"(?<!\w)(?:\+?82[- .]?)?0?1[016789](?:[- .]?\d){8}(?!\w)"),
    ),
)


class DLPScanner:
    """Recursively classify and sanitize a JSON-like payload.

    Unsupported values, traversal failures, and configured limits produce a
    closed decision rather than propagating payload-bearing exceptions.
    """

    def __init__(
        self,
        *,
        hmac_key: bytes | str | None = None,
        cwd: str | os.PathLike[str] | None = None,
        max_depth: int = 64,
        max_nodes: int = 10_000,
        max_findings: int = 1_000,
        max_text_length: int = 1_000_000,
    ) -> None:
        if hmac_key is None:
            self._key: bytes | None = None
        else:
            self._key = hmac_key.encode("utf-8") if isinstance(hmac_key, str) else bytes(hmac_key)
        self._cwd = str(Path(cwd).resolve()) if cwd is not None else str(Path.cwd().resolve())
        self._cwd_candidates = tuple(
            dict.fromkeys((self._cwd, self._cwd.replace("\\", "/"), self._cwd.replace("/", "\\")))
        )
        self.max_depth = max_depth
        self.max_nodes = max_nodes
        self.max_findings = max_findings
        self.max_text_length = max_text_length
        self._user_homes = tuple(
            dict.fromkeys(
                str(Path(item).resolve())
                for item in (os.path.expanduser("~"), os.environ.get("HOME"), os.environ.get("USERPROFILE"))
                if item
            )
        )

    def scan(self, payload: Any) -> DLPDecision:
        findings: list[DLPFinding] = []
        counter = {"nodes": 0}
        try:
            sanitized = self._visit(payload, "$", 0, findings, counter)
            if not findings:
                return DLPDecision(True, "allowed", sanitized, (), {"scanned_nodes": counter["nodes"]})
            action = self._action(findings)
            metadata: dict[str, Any] = {
                "scanned_nodes": counter["nodes"],
                "finding_count": len(findings),
                "highest_classification": max(
                    (finding.classification for finding in findings),
                    key=self._classification_rank,
                ).value,
            }
            if self._key is None and any(
                finding.classification is Classification.RESTRICTED_PII for finding in findings
            ):
                metadata["reason"] = "pii_tokenization_key_required"
            if action == "quarantine" and self._key is not None and all(
                finding.classification is Classification.RESTRICTED_PII for finding in findings
            ):
                action = "tokenized"
                metadata["tokenized"] = True
            return DLPDecision(False, action, sanitized, tuple(findings), metadata)
        except _ScanLimit:
            return self._fail_closed("scan_limit_exceeded")
        except Exception:
            return self._fail_closed("scanner_error")

    def _fail_closed(self, reason: str) -> DLPDecision:
        return DLPDecision(
            allowed=False,
            action="quarantine",
            sanitized_payload=None,
            findings=(),
            metadata={"reason": reason, "fail_closed": True},
        )

    def _visit(
        self,
        value: Any,
        path: str,
        depth: int,
        findings: list[DLPFinding],
        counter: dict[str, int],
    ) -> Any:
        counter["nodes"] += 1
        if depth > self.max_depth or counter["nodes"] > self.max_nodes:
            raise _ScanLimit
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return self._visit_string(value, path, findings)
        if isinstance(value, list):
            return [
                self._visit(item, f"{path}[{index}]", depth + 1, findings, counter)
                for index, item in enumerate(value)
            ]
        if isinstance(value, tuple):
            return [
                self._visit(item, f"{path}[{index}]", depth + 1, findings, counter)
                for index, item in enumerate(value)
            ]
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                safe_key = json.dumps(key, ensure_ascii=True, sort_keys=True) if not isinstance(key, str) else key
                key_path = f"{path}.<key:{index}>"
                sanitized_key = self._visit_string(safe_key, key_path, findings)
                if sanitized_key != safe_key:
                    safe_key = sanitized_key
                if safe_key in result:
                    raise ValueError("sanitized key collision")
                child_path = f"{path}.{safe_key}"
                result[safe_key] = self._visit(item, child_path, depth + 1, findings, counter)
                if isinstance(safe_key, str) and safe_key.lower() == "source_uri":
                    self._append_finding(
                        findings, child_path, Classification.INTERNAL, "source_uri"
                    )
                    result[safe_key] = _REDACTIONS[Classification.INTERNAL]
            return result
        return self._add_and_redact(
            findings, path, Classification.UNKNOWN, "unsupported_value", value
        )

    def _visit_string(self, value: str, path: str, findings: list[DLPFinding]) -> str:
        if len(value) > self.max_text_length:
            raise _ScanLimit

        if path.rsplit(".", 1)[-1].lower() in {"authorization", "proxy_authorization"}:
            return self._add_and_redact(findings, path, Classification.SECRET, "authorization", value)

        sanitized = value
        matches: list[tuple[int, int, Classification, str]] = []
        for kind, classification, pattern in _PATTERNS:
            for match in pattern.finditer(value):
                matches.append((match.start(), match.end(), classification, kind))

        for home in self._user_homes:
            index = value.find(home)
            if index >= 0:
                matches.append((index, index + len(home), Classification.CONFIDENTIAL, "user_home_path"))
        for cwd in self._cwd_candidates:
            cwd_index = value.lower().find(cwd.lower())
            if cwd_index >= 0:
                matches.append((cwd_index, cwd_index + len(cwd), Classification.INTERNAL, "cwd"))
                break

        selected: list[tuple[int, int, Classification, str]] = []
        for match in sorted(matches, key=lambda item: (item[0], -item[1])):
            start, end = match[0], match[1]
            if selected and start < selected[-1][1]:
                continue
            selected.append(match)
            self._append_finding(findings, path, match[2], match[3])

        parts: list[str] = []
        cursor = 0
        for start, end, classification, _kind in selected:
            parts.append(value[cursor:start])
            parts.append(self._replacement(classification, value[start:end]))
            cursor = end
        parts.append(value[cursor:])
        return "".join(parts)

    @staticmethod
    def _classification_rank(classification: Classification) -> int:
        ranks = {
            Classification.PUBLIC: 0,
            Classification.INTERNAL: 1,
            Classification.CONFIDENTIAL: 2,
            Classification.RESTRICTED_PII: 3,
            Classification.SECRET: 4,
            Classification.UNKNOWN: 5,
        }
        return ranks[classification]

    def _add_and_redact(
        self,
        findings: list[DLPFinding],
        path: str,
        classification: Classification,
        kind: str,
        value: Any,
    ) -> str:
        self._append_finding(findings, path, classification, kind)
        return self._replacement(classification, str(value))

    def _append_finding(
        self, findings: list[DLPFinding], path: str, classification: Classification, kind: str
    ) -> None:
        if len(findings) >= self.max_findings:
            raise _ScanLimit
        findings.append(DLPFinding(path, classification, kind))

    def _replacement(self, classification: Classification, value: str) -> str:
        if classification is not Classification.RESTRICTED_PII:
            return _REDACTIONS[classification]
        if self._key is None:
            return _REDACTIONS[classification]
        digest = hmac.new(self._key, value.encode("utf-8"), sha256).hexdigest()[:24]
        return f"[PII:{digest}]"

    @staticmethod
    def _action(findings: tuple[DLPFinding, ...] | list[DLPFinding]) -> str:
        if findings and all(item.classification is Classification.RESTRICTED_PII for item in findings):
            return "quarantine"
        if any(item.classification is Classification.PUBLIC for item in findings):
            return "allowed"
        return "quarantine"


class _ScanLimit(Exception):
    pass


def scan_payload(
    payload: Any,
    *,
    hmac_key: bytes | str | None = None,
    cwd: str | os.PathLike[str] | None = None,
    max_depth: int = 64,
    max_nodes: int = 10_000,
    max_findings: int = 1_000,
    max_text_length: int = 1_000_000,
) -> DLPDecision:
    """Convenience wrapper around :class:`DLPScanner`."""

    return DLPScanner(
        hmac_key=hmac_key,
        cwd=cwd,
        max_depth=max_depth,
        max_nodes=max_nodes,
        max_findings=max_findings,
        max_text_length=max_text_length,
    ).scan(payload)
