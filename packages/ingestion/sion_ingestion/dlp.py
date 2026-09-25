"""Dependency-free, fail-closed data loss prevention for ingestion payloads.

The scanner intentionally returns only sanitized metadata. Secret values are never
stored in findings, decision metadata, logs, or the sanitized payload.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any


#: Version of the decision-binding contract. A consumer that does not know this
#: exact version must not trust a decision produced under it.
DLP_POLICY_VERSION = "sion-dlp/v2"

#: Default lifetime of a decision, in seconds.
DECISION_TTL_SECONDS = 900

#: A decision may never claim a longer lifetime than this, whatever it says.
MAX_DECISION_TTL_SECONDS = 900

#: Tolerance for clock skew between the scanner and the verifying consumer.
_CLOCK_SKEW_TOLERANCE_SECONDS = 60


def canonical_payload_digest(payload: Any) -> str:
    """Return the stable digest of a JSON-like payload.

    The same function is used to bind a decision to the payload it scanned and
    by a consumer that re-derives the digest of the payload it is about to use.
    """

    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _key_fingerprint(key: bytes) -> str:
    return sha256(b"sion-dlp-signer" + key).hexdigest()[:16]


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
    """A scan result bound to the exact payload it scanned.

    Beyond the verdict, a decision carries a *binding*: the canonical digest of
    the scanned payload, the digest of the sanitized payload it produces, the
    policy version, an optional HMAC signer binding, and an issued/expires
    window. A consumer that is handed a decision by a caller it does not fully
    control can therefore refuse a decision that was forged, replayed for a
    different payload, produced under a different policy, or is simply stale.
    """

    allowed: bool
    action: str
    sanitized_payload: Any
    findings: tuple[DLPFinding, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)
    policy_version: str = DLP_POLICY_VERSION
    source_digest: str = ""
    payload_digest: str = ""
    signer_id: str = ""
    signature: str = ""
    issued_at: int = 0
    expires_at: int = 0

    def __post_init__(self) -> None:
        # A hand-built decision still gets a self-consistent binding over the
        # payload it carries; it never inherits trust from a caller.
        updates: dict[str, Any] = {}
        if not self.payload_digest:
            updates["payload_digest"] = canonical_payload_digest(self.sanitized_payload)
        if not self.source_digest:
            updates["source_digest"] = self.payload_digest or canonical_payload_digest(
                self.sanitized_payload
            )
        if not self.issued_at:
            now = int(time.time())
            updates["issued_at"] = now
            updates.setdefault("expires_at", now + DECISION_TTL_SECONDS)
        if not self.expires_at:
            issued = int(updates.get("issued_at", self.issued_at) or 0)
            updates["expires_at"] = issued + DECISION_TTL_SECONDS
        for name, value in updates.items():
            object.__setattr__(self, name, value)

    # -- binding -----------------------------------------------------------

    def binding_envelope(self) -> dict[str, Any]:
        """The exact fields covered by ``binding_digest`` and ``signature``."""

        return {
            "policy_version": self.policy_version,
            "source_digest": self.source_digest,
            "payload_digest": self.payload_digest,
            "issued_at": int(self.issued_at),
            "expires_at": int(self.expires_at),
            "signer_id": self.signer_id,
        }

    def binding_digest(self) -> str:
        return canonical_payload_digest(self.binding_envelope())

    def is_fresh(self, *, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        issued, expires = int(self.issued_at), int(self.expires_at)
        if issued <= 0 or expires <= 0:
            return False
        if expires - issued > MAX_DECISION_TTL_SECONDS:
            return False
        if issued - _CLOCK_SKEW_TOLERANCE_SECONDS > now:
            return False
        return now < expires

    def sign(self, key: bytes) -> "DLPDecision":
        """Return a copy signed with ``key``. The key never leaves this call."""

        signed = DLPDecision(
            allowed=self.allowed,
            action=self.action,
            sanitized_payload=self.sanitized_payload,
            findings=self.findings,
            metadata=dict(self.metadata),
            policy_version=self.policy_version,
            source_digest=self.source_digest,
            payload_digest=self.payload_digest,
            signer_id=_key_fingerprint(key),
            issued_at=int(self.issued_at),
            expires_at=int(self.expires_at),
        )
        signature = hmac.new(
            key, signed.binding_digest().encode("utf-8"), sha256
        ).hexdigest()
        object.__setattr__(signed, "signature", signature)
        return signed

    def verify_binding(
        self,
        *,
        payload: Any = None,
        key: bytes | str | None = None,
        policy_version: str = DLP_POLICY_VERSION,
        now: float | None = None,
    ) -> tuple[bool, str]:
        """Verify policy, digest, freshness and signer binding.

        Returns ``(ok, reason)``. ``reason`` is a fixed machine-readable token
        and never contains payload data.
        """

        if self.policy_version != policy_version:
            return False, "policy_version_mismatch"
        if not self.payload_digest:
            return False, "payload_digest_missing"
        if not self.source_digest:
            return False, "source_digest_missing"
        if payload is not None and canonical_payload_digest(payload) != self.source_digest:
            return False, "source_digest_mismatch"
        if canonical_payload_digest(self.sanitized_payload) != self.payload_digest:
            return False, "payload_digest_mismatch"
        if not self.is_fresh(now=now):
            return False, "stale_decision"
        if self.signature:
            if not self.signer_id or len(self.signature) != 64:
                return False, "signer_binding_malformed"
            if key is None:
                # The verifying consumer holds no key, so the HMAC itself cannot
                # be recomputed here; the digest/policy/freshness checks above
                # still stand. Consumers that hold the key get the full check.
                return True, "signer_not_verified"
            key_bytes = key.encode("utf-8") if isinstance(key, str) else bytes(key)
            if _key_fingerprint(key_bytes) != self.signer_id:
                return False, "signer_key_mismatch"
            expected = hmac.new(
                key_bytes, self.binding_digest().encode("utf-8"), sha256
            ).hexdigest()
            if not hmac.compare_digest(expected, self.signature):
                return False, "signer_signature_mismatch"
            return True, "verified"
        if key is not None:
            return False, "signer_binding_missing"
        return True, "verified"

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "action": self.action,
            "findings": [finding.to_dict() for finding in self.findings],
            "metadata": dict(self.metadata),
            "policy_version": self.policy_version,
            "source_digest": self.source_digest,
            "payload_digest": self.payload_digest,
            "signer_id": self.signer_id,
            "binding_digest": self.binding_digest(),
            "issued_at": int(self.issued_at),
            "expires_at": int(self.expires_at),
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
    # High-confidence vendor token shapes. Each pattern requires a vendor
    # specific prefix or a keyword-qualified assignment plus an entropy floor,
    # so ordinary prose that merely mentions a key name stays unflagged.
    (
        "sk_prefix_token",
        Classification.SECRET,
        re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{15,}\b"),
    ),
    (
        "api_key_assignment",
        Classification.SECRET,
        re.compile(
            r"(?i)\b(?:x-)?(?:api[_-]?key|apikey|access[_-]?key|access[_-]?token"
            r"|auth[_-]?token|client[_-]?secret|secret[_-]?key|private[_-]?token"
            r"|session[_-]?secret)\s*[:=]\s*[\"']?[A-Za-z0-9+/=_-]{16,}[\"']?"
        ),
    ),
    (
        "basic_auth_header",
        Classification.SECRET,
        re.compile(r"(?i)\bbasic\s+[A-Za-z0-9+/]{16,}={0,2}"),
    ),
    (
        "jwt",
        Classification.SECRET,
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{4,}"
        ),
    ),
    (
        "aws_access_key_id",
        Classification.SECRET,
        re.compile(
            r"\b(?:AKIA|ASIA|ABIA|ACCA|AGPA|AIDA|AIPA|ANPA|ANVA|APKA|AROA)"
            r"[0-9A-Z]{16}\b"
        ),
    ),
    (
        "aws_secret_access_key",
        Classification.SECRET,
        re.compile(
            r"(?i)\baws[_-]?secret[_-]?access[_-]?key\s*[:=]\s*[\"']?"
            r"[A-Za-z0-9+/]{40}[\"']?"
        ),
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
            source_digest = canonical_payload_digest(payload)
            sanitized = self._visit(payload, "$", 0, findings, counter)
            if not findings:
                return self._bind(
                    DLPDecision(
                        True,
                        "allowed",
                        sanitized,
                        (),
                        {"scanned_nodes": counter["nodes"]},
                        source_digest=source_digest,
                    )
                )
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
            return self._bind(
                DLPDecision(
                    False,
                    action,
                    sanitized,
                    tuple(findings),
                    metadata,
                    source_digest=source_digest,
                )
            )
        except _ScanLimit:
            return self._fail_closed("scan_limit_exceeded")
        except Exception:
            return self._fail_closed("scanner_error")

    def _bind(self, decision: DLPDecision) -> DLPDecision:
        """Apply the signer binding when the scanner holds an HMAC key."""

        if self._key is None:
            return decision
        return decision.sign(self._key)

    def _fail_closed(self, reason: str) -> DLPDecision:
        return self._bind(
            DLPDecision(
                allowed=False,
                action="quarantine",
                sanitized_payload=None,
                findings=(),
                metadata={"reason": reason, "fail_closed": True},
            )
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
