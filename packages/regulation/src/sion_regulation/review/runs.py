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


class RunEngine:
    def __init__(
        self,
        store: RunStore,
        executors: Mapping[str, Executor],
        *,
        concurrency: Mapping[str, int] | None = None,
        retry: RetryPolicy | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.store = store
        self.executors = dict(executors)
        self.retry = retry or RetryPolicy()
        self.clock = clock
        limits = concurrency or {}
        self._limits = {
            name: threading.BoundedSemaphore(limits.get(name, 1)) for name in self.executors
        }
        self._commit = threading.Lock()

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
            for node in record.nodes.values():
                if node.status in {ExecutionStatus.QUEUED, ExecutionStatus.RUNNING}:
                    node.status = ExecutionStatus.CANCELLED
            self.store.save(record)
            return record

    def resume(
        self,
        run_id: str,
        *,
        changed_requests: Mapping[str, dict[str, Any]] | None = None,
        retry_blocked: bool = False,
    ) -> RunRecord:
        """Open the next revision and run what is left.

        Completed nodes with an unchanged input are reused. ``retry_blocked`` also retries AUTH and
        SCHEMA failures, for use after an operator fixed the cause. The previous revision stays
        readable as it was.
        """

        with self._commit:
            record = self.store.load(run_id)
            if record.status is ExecutionStatus.CANCELLED:
                raise ValueError("a cancelled run is not resumed; start a new run")
            previous = record.run_revision
            record.run_revision = previous + 1
            record.status = ExecutionStatus.QUEUED
            record.output = None
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

    def execute(self, run_id: str) -> RunRecord:
        """Run ready nodes wave by wave until nothing more can start."""

        with self._commit:
            record = self.store.load(run_id)
            if record.status is ExecutionStatus.CANCELLED:
                return record
            for node in record.nodes.values():
                if node.status is ExecutionStatus.RUNNING:  # left behind by an interrupted worker
                    node.status = ExecutionStatus.QUEUED
            record.status = ExecutionStatus.RUNNING
            self.store.save(record)

        while True:
            record = self.store.load(run_id)
            if record.status is ExecutionStatus.CANCELLED:
                return record
            ready = self._ready(record)
            if not ready:
                return self._finish(run_id)
            with ThreadPoolExecutor(max_workers=len(ready)) as pool:
                futures = [pool.submit(self._run_node, run_id, node) for node in ready]
            for future in futures:
                future.result()  # re-raise an interruption; its checkpoints are already stored

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

    def _run_node(self, run_id: str, node: RunNode) -> None:
        executor = self.executors.get(node.provider)
        if executor is None:
            result = CollectionResult(
                node_id=node.node_id,
                provider=node.provider,
                status=CollectionStatus.UNSUPPORTED,
                error=f"no executor for provider {node.provider}",
            )
            self._checkpoint(run_id, node.node_id, result)
            return
        with self._commit:
            record = self.store.load(run_id)
            if record.status is ExecutionStatus.CANCELLED:
                return
            live = record.nodes[node.node_id]
            live.status = ExecutionStatus.RUNNING
            live.started_at = self.clock()
            live.attempts += 1
            self.store.save(record)
        with self._limits[node.provider]:
            try:
                result = executor(node)
            except TimeoutError as exc:
                result = self._failed(node, ErrorKind.TIMEOUT, str(exc))
            except (OSError, ValueError, RuntimeError) as exc:
                result = self._failed(node, ErrorKind.TRANSIENT, str(exc))
        self._checkpoint(run_id, node.node_id, result)

    @staticmethod
    def _failed(node: RunNode, kind: ErrorKind, message: str) -> CollectionResult:
        return CollectionResult(
            node_id=node.node_id,
            provider=node.provider,
            status=CollectionStatus.FAILED,
            error_kind=kind,
            error=message,
        )

    def _checkpoint(self, run_id: str, node_id: str, result: CollectionResult) -> None:
        with self._commit:
            record = self.store.load(run_id)
            if record.status is ExecutionStatus.CANCELLED:
                # S29: a response that lands after cancellation is history, not a result.
                record.late_results.append(result)
                self.store.save(record)
                return
            node = record.nodes[node_id]
            node.finished_at = self.clock()
            node.collection = result.status
            node.artifacts = [item.evidence_id for item in result.evidence]
            record.results[node_id] = result
            self._apply(node, result)
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

    def _finish(self, run_id: str) -> RunRecord:
        with self._commit:
            record = self.store.load(run_id)
            if record.status is ExecutionStatus.CANCELLED:
                return record
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
