"""Durable review execution (W08; scenarios S19, S20, S26, S27, S29).

A run is a DAG of collection nodes. Every node outcome is checkpointed to a :class:`RunStore`, so
another process can resume from the store alone. ``completed`` means collection finished; it says
nothing about the legal review being complete.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from sion_regulation.review.model import (
    CollectionResult,
    CollectionStatus,
    ErrorKind,
    ExecutionStatus,
    NextTask,
    UnresolvedItem,
    canonical_digest,
)
from sion_regulation.review.sources import RetryPolicy

Executor = Callable[["RunNode"], CollectionResult]


class IdempotencyConflict(ValueError):
    """The same idempotency key arrived with a different payload."""


class RunNotFound(KeyError):
    pass


class RunInFlight(ValueError):
    """Another worker holds the run, or it changed since it was read; retry later (HTTP 409)."""


class RunNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    deps: list[str] = Field(default_factory=list)
    provider: str = Field(min_length=1)
    contract: str = ""
    request: dict[str, Any] = Field(default_factory=dict)
    input_digest: str = ""
    status: ExecutionStatus = ExecutionStatus.QUEUED
    started_at: datetime | None = None
    finished_at: datetime | None = None
    artifacts: list[str] = Field(default_factory=list)
    collection: CollectionStatus | None = None
    error_kind: ErrorKind | None = None
    failure: str | None = None
    attempts: int = 0
    next_retry_at: datetime | None = None
    missing: list[str] = Field(default_factory=list)
    reused_from_revision: int | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    idempotency_key: str
    payload_digest: str
    project_id: str
    proposal_revision: str
    run_revision: int = 1
    status: ExecutionStatus = ExecutionStatus.QUEUED
    nodes: dict[str, RunNode] = Field(default_factory=dict)
    results: dict[str, CollectionResult] = Field(default_factory=dict)
    late_results: list[CollectionResult] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    failure: str | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None


class RunDAG:
    """Validated node set: known dependencies, no cycle, stable digests."""

    def __init__(self, nodes: Iterable[RunNode]) -> None:
        self.nodes: dict[str, RunNode] = {}
        for node in nodes:
            if node.node_id in self.nodes:
                raise ValueError(f"duplicate node: {node.node_id}")
            # Only the definition is taken over: state fields of a submitted node are ignored.
            self.nodes[node.node_id] = RunNode(
                node_id=node.node_id,
                deps=list(node.deps),
                provider=node.provider,
                contract=node.contract,
                request=dict(node.request),
                input_digest=canonical_digest(
                    {"provider": node.provider, "contract": node.contract, "request": node.request}
                ),
            )
        self.order()

    def order(self) -> list[str]:
        done: list[str] = []
        remaining = {key: set(node.deps) for key, node in self.nodes.items()}
        for key, deps in remaining.items():
            unknown = deps - set(self.nodes)
            if unknown:
                raise ValueError(f"{key} depends on unknown nodes: {sorted(unknown)}")
        while remaining:
            ready = sorted(key for key, deps in remaining.items() if deps <= set(done))
            if not ready:
                raise ValueError(f"dependency cycle among: {sorted(remaining)}")
            done.extend(ready)
            for key in ready:
                del remaining[key]
        return done


class RunStore(Protocol):
    def save(self, record: RunRecord) -> None: ...

    def load(self, run_id: str, revision: int | None = None) -> RunRecord: ...

    def find_by_key(self, key: str) -> RunRecord | None: ...

    def revisions(self, run_id: str) -> list[int]: ...


class InMemoryRunStore:
    """Reference store; each record is copied in and out, as a database row would be."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[int, RunRecord]] = {}
        self._keys: dict[str, str] = {}

    def save(self, record: RunRecord) -> None:
        self._rows.setdefault(record.run_id, {})[record.run_revision] = record.model_copy(deep=True)
        self._keys.setdefault(record.idempotency_key, record.run_id)

    def load(self, run_id: str, revision: int | None = None) -> RunRecord:
        rows = self._rows.get(run_id)
        if not rows:
            raise RunNotFound(run_id)
        chosen = max(rows) if revision is None else revision
        if chosen not in rows:
            raise RunNotFound(f"{run_id}@{revision}")
        return rows[chosen].model_copy(deep=True)

    def find_by_key(self, key: str) -> RunRecord | None:
        run_id = self._keys.get(key)
        return self.load(run_id) if run_id else None

    def revisions(self, run_id: str) -> list[int]:
        return sorted(self._rows.get(run_id, {}))


def idempotency_key(project_id: str, revision: str, payload: Any) -> str:
    return canonical_digest({"project": project_id, "revision": revision, "payload": payload})


def _utcnow() -> datetime:
    return datetime.now(UTC)


_ACTIVE = frozenset({ExecutionStatus.QUEUED, ExecutionStatus.RUNNING})


class RunEngine:
    """Executes runs from the store alone.

    A worker holds a lease on the run and on each node it started (owner token plus an expiry from
    the injectable clock). Only a RUNNING node whose lease expired or was released is requeued, and
    a run whose lease is live is never executed or resumed by another caller (S26, S27). Every
    write that depends on what was read happens under one lock, compare-and-set, so a cancelled or
    newer revision is never overwritten (S29). ``lease_seconds`` must exceed the slowest provider
    call: there is no heartbeat while an executor runs.
    """

    def __init__(
        self,
        store: RunStore,
        executors: Mapping[str, Executor],
        *,
        concurrency: Mapping[str, int] | None = None,
        retry: RetryPolicy | None = None,
        clock: Callable[[], datetime] = _utcnow,
        lease_seconds: float = 900.0,
    ) -> None:
        self.store = store
        self.executors = dict(executors)
        self.retry = retry or RetryPolicy()
        self.clock = clock
        self.lease = timedelta(seconds=lease_seconds)
        limits = concurrency or {}
        self._limits = {
            name: threading.BoundedSemaphore(limits.get(name, 1)) for name in self.executors
        }
        self._commit = threading.Lock()

    # ------------------------------------------------------------------ leases

    def _live(self, owner: str | None, expires: datetime | None) -> bool:
        return owner is not None and expires is not None and expires > self.clock()

    def in_flight(self, record: RunRecord) -> bool:
        """Queued or running with a live lease: another worker is still on it."""

        return record.status in _ACTIVE and self._live(record.lease_owner, record.lease_expires_at)

    def _take(self, record: RunRecord, owner: str) -> None:
        record.lease_owner = owner
        record.lease_expires_at = self.clock() + self.lease

    @staticmethod
    def _holds(record: RunRecord, owner: str, revision: int) -> bool:
        return record.run_revision == revision and record.lease_owner == owner

    def _release(self, run_id: str, owner: str, revision: int) -> None:
        with self._commit:
            record = self.store.load(run_id)
            if not self._holds(record, owner, revision):
                return
            record.lease_owner = None
            record.lease_expires_at = None
            self.store.save(record)

    def _release_node(self, run_id: str, node_id: str, owner: str, revision: int) -> None:
        """An interrupted worker gives up its node; it stays RUNNING until a worker requeues it."""

        with self._commit:
            record = self.store.load(run_id)
            node = record.nodes[node_id]
            if record.run_revision != revision or node.lease_owner != owner:
                return
            node.lease_owner = None
            node.lease_expires_at = None
            self.store.save(record)

    # ------------------------------------------------------------------ lifecycle

    def create(
        self,
        project_id: str,
        proposal_revision: str,
        payload: Any,
        dag: RunDAG,
        *,
        key: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> RunRecord:
        """Create a run, or return the existing one for the same key and payload (S26)."""

        digest = canonical_digest(payload)
        run_key = key or idempotency_key(project_id, proposal_revision, payload)
        existing = self.store.find_by_key(run_key)
        if existing is not None:
            if existing.payload_digest != digest:
                raise IdempotencyConflict(f"key {run_key} was used with a different payload")
            return existing
        record = RunRecord(
            run_id="run:" + canonical_digest([run_key, digest])[:24],
            idempotency_key=run_key,
            payload_digest=digest,
            project_id=project_id,
            proposal_revision=proposal_revision,
            nodes={key_: node.model_copy(deep=True) for key_, node in dag.nodes.items()},
            context=context or {},
        )
        self.store.save(record)
        return record

    def cancel(self, run_id: str) -> RunRecord:
        with self._commit:
            record = self.store.load(run_id)
            if record.status is ExecutionStatus.COMPLETED:
                return record  # nothing is left to stop
            record.status = ExecutionStatus.CANCELLED
            record.lease_owner = None
            record.lease_expires_at = None
            for node in record.nodes.values():
                if node.status in _ACTIVE:
                    node.status = ExecutionStatus.CANCELLED
            self.store.save(record)
            return record

    def attach_output(
        self, run_id: str, revision: int, expected: ExecutionStatus, output: dict[str, Any]
    ) -> RunRecord:
        """Store ``output`` on that revision only if it is still as evaluated (S29).

        A revision that was cancelled, re-executed or already given an output in the meantime is
        returned unchanged; the caller reports what is stored.
        """

        with self._commit:
            record = self.store.load(run_id, revision)
            if record.status is not expected or record.status in _ACTIVE:
                return record
            if record.status is ExecutionStatus.CANCELLED or record.output is not None:
                return record
            record.output = output
            record.failure = None
            self.store.save(record)
            return record

    def mark_failed(
        self, run_id: str, revision: int, expected: ExecutionStatus, reason: str
    ) -> RunRecord:
        """A revision whose evaluation failed reads as failed, not as an output-less success."""

        with self._commit:
            record = self.store.load(run_id, revision)
            if record.status is not expected or record.output is not None:
                return record
            if record.status in _ACTIVE or record.status is ExecutionStatus.CANCELLED:
                return record
            record.status = ExecutionStatus.FAILED
            record.failure = reason
            self.store.save(record)
            return record

    def resume(
        self,
        run_id: str,
        *,
        changed_requests: Mapping[str, dict[str, Any]] | None = None,
        retry_blocked: bool = False,
        expected_revision: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> RunRecord:
        """Open the next revision and run what is left.

        Completed nodes with an unchanged input are reused. ``retry_blocked`` also retries AUTH and
        SCHEMA failures, for use after an operator fixed the cause. ``context`` replaces the context
        of the new revision only. The previous revision stays readable exactly as it was. A run in
        flight, or one that moved past ``expected_revision``, raises :class:`RunInFlight`.
        """

        with self._commit:
            record = self.store.load(run_id)
            if record.status is ExecutionStatus.CANCELLED:
                raise ValueError("a cancelled run is not resumed; start a new run")
            if expected_revision is not None and record.run_revision != expected_revision:
                raise RunInFlight(
                    f"run {run_id} moved to revision {record.run_revision}; reload and retry"
                )
            if self.in_flight(record):
                raise RunInFlight(f"run {run_id} revision {record.run_revision} is still in flight")
            previous = record.run_revision
            record.run_revision = previous + 1
            record.status = ExecutionStatus.QUEUED
            record.output = None
            record.failure = None
            record.lease_owner = None
            record.lease_expires_at = None
            if context is not None:
                record.context = context
            changed = dict(changed_requests or {})
            stale = self._downstream(record, set(changed))
            for node in record.nodes.values():
                if node.node_id in changed:
                    node.request = changed[node.node_id]
                    node.input_digest = canonical_digest(
                        {
                            "provider": node.provider,
                            "contract": node.contract,
                            "request": node.request,
                        }
                    )
                if node.status is ExecutionStatus.COMPLETED and node.node_id not in stale:
                    node.reused_from_revision = node.reused_from_revision or previous
                    continue
                blocked = node.error_kind in {ErrorKind.AUTH, ErrorKind.SCHEMA}
                if blocked and not retry_blocked and node.node_id not in changed:
                    continue
                self._reset(node)
                record.results.pop(node.node_id, None)
            self.store.save(record)
        return self.execute(run_id)

    @staticmethod
    def _downstream(record: RunRecord, changed: set[str]) -> set[str]:
        stale = set(changed)
        grew = True
        while grew:
            grew = False
            for node in record.nodes.values():
                if node.node_id not in stale and stale & set(node.deps):
                    stale.add(node.node_id)
                    grew = True
        return stale

    @staticmethod
    def _reset(node: RunNode) -> None:
        node.status = ExecutionStatus.QUEUED
        node.collection = None
        node.error_kind = None
        node.failure = None
        node.next_retry_at = None
        node.missing = []
        node.reused_from_revision = None
        node.lease_owner = None
        node.lease_expires_at = None

    def execute(self, run_id: str) -> RunRecord:
        """Run ready nodes wave by wave until nothing more can start.

        A run another worker holds is returned as it is, still QUEUED or RUNNING.
        """

        owner = uuid4().hex
        with self._commit:
            record = self.store.load(run_id)
            if record.status is ExecutionStatus.CANCELLED or self.in_flight(record):
                return record
            revision = record.run_revision
            for node in record.nodes.values():
                if node.status is ExecutionStatus.RUNNING and not self._live(
                    node.lease_owner, node.lease_expires_at
                ):
                    # Its worker died (lease expired) or was interrupted (lease released).
                    node.status = ExecutionStatus.QUEUED
                    node.lease_owner = None
                    node.lease_expires_at = None
            record.status = ExecutionStatus.RUNNING
            self._take(record, owner)
            self.store.save(record)

        try:
            while True:
                record = self.store.load(run_id)
                if record.status is ExecutionStatus.CANCELLED:
                    return record
                if not self._holds(record, owner, revision):
                    return record  # another worker took over an expired lease
                ready = self._ready(record)
                if not ready:
                    return self._finish(run_id, owner, revision)
                with ThreadPoolExecutor(max_workers=len(ready)) as pool:
                    futures = [
                        pool.submit(self._run_node, run_id, node, owner, revision) for node in ready
                    ]
                for future in futures:
                    future.result()  # re-raise an interruption; its checkpoints are already stored
        except BaseException:
            self._release(run_id, owner, revision)
            raise

    @staticmethod
    def _ready(record: RunRecord) -> list[RunNode]:
        done = {
            key for key, node in record.nodes.items() if node.status is ExecutionStatus.COMPLETED
        }
        return [
            node
            for key, node in sorted(record.nodes.items())
            if node.status is ExecutionStatus.QUEUED and set(node.deps) <= done
        ]

    def _run_node(self, run_id: str, node: RunNode, owner: str, revision: int) -> None:
        executor = self.executors.get(node.provider)
        if executor is None:
            result = CollectionResult(
                node_id=node.node_id,
                provider=node.provider,
                status=CollectionStatus.UNSUPPORTED,
                error=f"no executor for provider {node.provider}",
            )
            self._checkpoint(run_id, node.node_id, result, owner, revision, claimed=False)
            return
        with self._commit:
            record = self.store.load(run_id)
            if record.status is ExecutionStatus.CANCELLED:
                return
            live = record.nodes[node.node_id]
            if (
                not self._holds(record, owner, revision)
                or live.status is not ExecutionStatus.QUEUED
            ):
                return
            live.status = ExecutionStatus.RUNNING
            live.started_at = self.clock()
            live.attempts += 1
            live.lease_owner = owner
            live.lease_expires_at = live.started_at + self.lease
            self._take(record, owner)
            self.store.save(record)
        stored = False
        try:
            with self._limits[node.provider]:
                try:
                    result = executor(node)
                except TimeoutError as exc:
                    result = self._failed(node, ErrorKind.TIMEOUT, str(exc))
                except (OSError, ValueError, RuntimeError) as exc:
                    result = self._failed(node, ErrorKind.TRANSIENT, str(exc))
            self._checkpoint(run_id, node.node_id, result, owner, revision)
            stored = True
        finally:
            if not stored:
                self._release_node(run_id, node.node_id, owner, revision)

    @staticmethod
    def _failed(node: RunNode, kind: ErrorKind, message: str) -> CollectionResult:
        return CollectionResult(
            node_id=node.node_id,
            provider=node.provider,
            status=CollectionStatus.FAILED,
            error_kind=kind,
            error=message,
        )

    def _checkpoint(
        self,
        run_id: str,
        node_id: str,
        result: CollectionResult,
        owner: str,
        revision: int,
        *,
        claimed: bool = True,
    ) -> None:
        with self._commit:
            record = self.store.load(run_id)
            node = record.nodes[node_id]
            lost = not self._holds(record, owner, revision) or (
                claimed and node.lease_owner != owner
            )
            if record.status is ExecutionStatus.CANCELLED or lost:
                # S29: a response that lands after cancellation, or after another worker took
                # over or opened a newer revision, is history, not a result.
                record.late_results.append(result)
                self.store.save(record)
                return
            node.finished_at = self.clock()
            node.collection = result.status
            node.artifacts = [item.evidence_id for item in result.evidence]
            node.lease_owner = None
            node.lease_expires_at = None
            record.results[node_id] = result
            self._apply(node, result)
            self._take(record, owner)
            self.store.save(record)

    def _apply(self, node: RunNode, result: CollectionResult) -> None:
        capped = result.result_limit is not None and len(result.items) >= result.result_limit
        if result.status is CollectionStatus.FAILED:
            node.status = ExecutionStatus.FAILED
            node.error_kind = result.error_kind
            node.failure = result.error
            kind = result.error_kind or ErrorKind.TRANSIENT
            delay = self.retry.next_delay(kind, node.attempts, result.retry_after_seconds)
            node.next_retry_at = None if delay is None else self.clock() + timedelta(seconds=delay)
            node.missing = [f"{node.provider}: {kind.value}"]
        elif result.status is CollectionStatus.TRUNCATED or result.next_page or capped:
            node.status = ExecutionStatus.PARTIAL
            node.collection = CollectionStatus.TRUNCATED
            node.missing = [f"{node.provider}: next page {result.next_page or 'unknown'}"]
        elif result.status in {CollectionStatus.FOUND, CollectionStatus.EMPTY}:
            node.status = ExecutionStatus.COMPLETED
        else:
            node.status = ExecutionStatus.PARTIAL
            node.missing = [f"{node.provider}: {result.status.value}"]

    def _finish(self, run_id: str, owner: str, revision: int) -> RunRecord:
        with self._commit:
            record = self.store.load(run_id)
            if record.status is ExecutionStatus.CANCELLED or not self._holds(
                record, owner, revision
            ):
                return record
            record.lease_owner = None
            record.lease_expires_at = None
            statuses = [node.status for node in record.nodes.values()]
            if all(status is ExecutionStatus.COMPLETED for status in statuses):
                record.status = ExecutionStatus.COMPLETED
            elif all(status is ExecutionStatus.FAILED for status in statuses):
                record.status = ExecutionStatus.FAILED
            else:
                record.status = ExecutionStatus.PARTIAL
            for node in record.nodes.values():
                if node.status is ExecutionStatus.QUEUED:
                    waiting = [
                        dep
                        for dep in node.deps
                        if record.nodes[dep].status is not ExecutionStatus.COMPLETED
                    ]
                    node.missing = [f"blocked by {dep}" for dep in waiting]
            self.store.save(record)
            return record


def missing_ledger(record: RunRecord) -> tuple[list[UnresolvedItem], list[NextTask]]:
    """Turn every incomplete node into an unresolved item with an owned next task."""

    items: list[UnresolvedItem] = []
    tasks: list[NextTask] = []
    for node in record.nodes.values():
        if node.status is ExecutionStatus.COMPLETED:
            continue
        kind: Any = "collection_failed"
        role: Any = "data_operator"
        if node.error_kind is ErrorKind.AUTH:
            role = "ops_admin"
        elif node.error_kind is ErrorKind.SCHEMA:
            kind = "quarantined"
        elif node.collection is CollectionStatus.TRUNCATED:
            kind = "truncated"
        elif node.collection is CollectionStatus.UNSUPPORTED:
            kind = "unsupported_source"
        detail = "; ".join(node.missing) or f"{node.node_id}: {node.status.value}"
        item_id = "gap:" + canonical_digest([record.run_id, node.node_id])[:16]
        task_id = "task:" + item_id[4:]
        items.append(UnresolvedItem(item_id=item_id, kind=kind, detail=detail, task_id=task_id))
        tasks.append(
            NextTask(
                task_id=task_id,
                role=role,
                reason=detail,
                target=f"node {node.node_id}",
                resolves=[item_id],
            )
        )
    return items, tasks


@dataclass(slots=True)
class OutboxEntry:
    key: str
    payload: dict[str, Any]
    delivered: bool = False


class ReviewOutbox:
    """Idempotent hand-off between stores; there is no global transaction (section 15)."""

    def __init__(self) -> None:
        self._entries: dict[str, OutboxEntry] = {}

    def enqueue(self, key: str, payload: dict[str, Any]) -> None:
        existing = self._entries.get(key)
        if existing is not None:
            if existing.payload != payload:
                raise IdempotencyConflict(f"outbox key {key} was used with a different payload")
            return
        self._entries[key] = OutboxEntry(key, payload)

    def pending(self) -> list[OutboxEntry]:
        return [entry for entry in self._entries.values() if not entry.delivered]

    def drain(self, handler: Callable[[OutboxEntry], None]) -> int:
        delivered = 0
        for entry in self.pending():
            handler(entry)
            entry.delivered = True
            delivered += 1
        return delivered
