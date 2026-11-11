"""Provider contracts, failure taxonomy and site resolution (W03/W04; S01, S02, S19, S20, S31).

Nothing here talks to a network. Real adapters implement :class:`Provider`; fixtures replay stored
JSON. Provider capability is declared data: having a key does not imply a working API grant.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from sion_regulation.review.model import (
    CollectionResult,
    CollectionStatus,
    ErrorKind,
    ParcelPart,
    Site,
)


@runtime_checkable
class Provider(Protocol):
    name: str
    contract: str
    capabilities: frozenset[str]

    def fetch(self, request: Mapping[str, Any]) -> CollectionResult: ...


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    """Declared supply range. ``historical`` False means no past-date query is available."""

    capability: str
    historical: bool = False
    max_concurrency: int = 2
    quota_per_minute: int | None = None


@dataclass(slots=True)
class ProviderRegistry:
    _providers: dict[str, Provider] = field(default_factory=dict)
    _profiles: dict[str, list[ProviderProfile]] = field(default_factory=dict)

    def register(self, provider: Provider, profiles: Sequence[ProviderProfile]) -> None:
        if provider.name in self._providers:
            raise ValueError(f"provider {provider.name} is already registered")
        undeclared = {profile.capability for profile in profiles} - provider.capabilities
        if undeclared:
            raise ValueError(f"profile names undeclared capabilities: {sorted(undeclared)}")
        self._providers[provider.name] = provider
        self._profiles[provider.name] = list(profiles)

    def get(self, name: str) -> Provider:
        return self._providers[name]

    def concurrency(self, name: str) -> int:
        limits = [profile.max_concurrency for profile in self._profiles.get(name, [])]
        return min(limits) if limits else 1

    def for_capability(self, capability: str, *, historical: bool = False) -> list[Provider]:
        """Providers offering a capability; a current-only source never serves a past date."""

        return [
            self._providers[name]
            for name in sorted(self._profiles)
            for profile in self._profiles[name]
            if profile.capability == capability and (profile.historical or not historical)
        ]


def classify_http(status: int) -> ErrorKind | None:
    """Map an HTTP status to the failure taxonomy; ``None`` means not a failure."""

    if status < 400:
        return None
    if status == 429:
        return ErrorKind.RATE_LIMITED
    if status in {401, 403}:
        return ErrorKind.AUTH
    if status in {408, 504}:
        return ErrorKind.TIMEOUT
    if status >= 500:
        return ErrorKind.TRANSIENT
    return ErrorKind.SCHEMA


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded retry. AUTH and SCHEMA never retry: repeating cannot help and may lock the key."""

    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0

    def next_delay(
        self, kind: ErrorKind, attempt: int, retry_after: float | None = None
    ) -> float | None:
        """Seconds to wait after failed attempt number ``attempt``, or ``None`` to stop."""

        if kind not in {ErrorKind.TRANSIENT, ErrorKind.RATE_LIMITED, ErrorKind.TIMEOUT}:
            return None
        if attempt >= self.max_attempts:
            return None
        if kind is ErrorKind.RATE_LIMITED and retry_after is not None:
            return float(retry_after)
        return min(self.base_delay_seconds * 2 ** (attempt - 1), self.max_delay_seconds)


def fetch_with_retry(
    provider: Provider,
    request: Mapping[str, Any],
    policy: RetryPolicy,
    sleep: Callable[[float], None],
) -> tuple[CollectionResult, int]:
    """Fetch under ``policy``; returns the last result and the attempts used."""

    attempt = 0
    while True:
        attempt += 1
        result = provider.fetch(request)
        if result.status is not CollectionStatus.FAILED or result.error_kind is None:
            return result, attempt
        delay = policy.next_delay(result.error_kind, attempt, result.retry_after_seconds)
        if delay is None:
            return result, attempt
        sleep(delay)


class FixtureProvider:
    """Replays ``{request_key: result}``; an unknown key is UNSUPPORTED, not an empty result."""

    def __init__(
        self,
        name: str,
        contract: str,
        capabilities: frozenset[str],
        responses: Mapping[str, Mapping[str, Any]],
    ) -> None:
        self.name = name
        self.contract = contract
        self.capabilities = capabilities
        self._responses = dict(responses)

    @classmethod
    def from_file(
        cls, name: str, contract: str, capabilities: frozenset[str], path: Path
    ) -> FixtureProvider:
        return cls(name, contract, capabilities, json.loads(path.read_text(encoding="utf-8")))

    def fetch(self, request: Mapping[str, Any]) -> CollectionResult:
        key = str(request.get("key"))
        node_id = str(request.get("node_id", key))
        raw = self._responses.get(key)
        if raw is None:
            return CollectionResult(
                node_id=node_id, provider=self.name, status=CollectionStatus.UNSUPPORTED
            )
        return CollectionResult.model_validate({"node_id": node_id, "provider": self.name, **raw})


def resolve_site(
    address_results: Sequence[Mapping[str, Any]],
    *,
    address: str | None = None,
    jurisdiction_code: str | None = None,
) -> Site:
    """Resolve address matches. Several distinct parcels stay unresolved candidates (S01).

    Each record is ``{"pnu": ..., "parts": [...]}``. A parcel crossing zones keeps one
    :class:`ParcelPart` per part so later steps never use only the first hit (S02).
    """

    by_pnu: dict[str, Mapping[str, Any]] = {}
    for record in address_results:
        pnu = record.get("pnu")
        if pnu:
            by_pnu.setdefault(str(pnu), record)
    if len(by_pnu) != 1:
        return Site(address=address, candidates=[dict(item) for item in address_results])

    pnu, record = next(iter(by_pnu.items()))
    raw_parts = record.get("parts") or [{"part_id": pnu}]
    parts = [ParcelPart.model_validate({"pnu": pnu, **part}) for part in raw_parts]
    return Site(
        address=address,
        pnus=[pnu],
        parts=parts,
        jurisdiction_code=jurisdiction_code or record.get("jurisdiction_code"),
        resolved=True,
    )
