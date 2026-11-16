"""Regression tests for the run lifecycle (S26, S27, S29).

A run is driven by one worker at a time under a lease; retries and resumes while it is in flight
neither re-run providers nor write into another revision; outputs are attached compare-and-set so a
cancelled revision keeps no conclusion; a rejected supplement opens no revision and a failed
evaluation reads as failed. All values are synthetic fixtures.
"""

# ruff: noqa: E402

from __future__ import annotations

import threading
from datetime import timedelta
from typing import Any

import pytest

# The minimal ".[test]" install has no archontos/greenlet; skip like test_review_scenarios.
pytest.importorskip("sion_regulation.review.workflow", exc_type=ImportError)

from sion_regulation.review.runs import RunInFlight
from test_review_scenarios import (
    NOW,
    CollectionResult,
    CollectionStatus,
    ExecutionStatus,
    Fact,
    FactStatus,
    InMemoryRunStore,
    RunDAG,
    RunEngine,
    RunNode,
    _result,
    fact,
    request,
    workflow_with,
)


def claim(value: Any, fact_id: str = "c1") -> Fact:
    return fact(
        "land.flag",
        value,
        status=FactStatus.ASSERTED,
        method="user_claim",
        evidence_ids=[],
        fact_id=fact_id,
    )


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> Any:
        return self.now


def _blocking() -> tuple[list[str], threading.Event, threading.Event, Any]:
    calls: list[str] = []
    started, release = threading.Event(), threading.Event()

    def slow(node: RunNode) -> CollectionResult:
        calls.append(node.node_id)
        started.set()
        assert release.wait(5)
        return _result(node, CollectionStatus.FOUND)

    return calls, started, release, slow


# ------------------------------------------------------------------ in-flight runs (S26, S27)


def test_retry_while_in_flight_returns_status_without_re_executing() -> None:
    calls, started, release, slow = _blocking()
    store = InMemoryRunStore()
    flow = workflow_with(store=store, executors={"p": slow})
    req = request(requested_sources=[RunNode(node_id="n", provider="p")], idempotency_key="k")
    first: list[dict[str, Any]] = []
    worker = threading.Thread(target=lambda: first.append(flow.start_review(req)))
    worker.start()
    assert started.wait(5)
    retried = flow.start_review(req)
    assert retried["execution_status"] == ExecutionStatus.RUNNING.value
    release.set()
    worker.join(5)
    assert calls == ["n"]
    record = store.load(first[0]["run_id"])
    assert record.nodes["n"].attempts == 1 and record.output is not None


def test_resume_is_refused_while_the_latest_revision_is_in_flight() -> None:
    calls, started, release, slow = _blocking()
    store = InMemoryRunStore()
    flow = workflow_with(store=store, executors={"p": slow})
    req = request(requested_sources=[RunNode(node_id="n", provider="p")])
    first: list[dict[str, Any]] = []
    worker = threading.Thread(target=lambda: first.append(flow.start_review(req)))
    worker.start()
    assert started.wait(5)
    run_id = next(iter(store._rows))
    try:
        with pytest.raises(RunInFlight):
            flow.resume_review(run_id, project_id="proj-1")
        with pytest.raises(RunInFlight):
            flow.engine.resume(run_id)
    finally:
        release.set()
        worker.join(5)
    assert calls == ["n"] and store.revisions(run_id) == [1]
    assert first[0]["run_revision"] == 1 and store.load(run_id, 1).output is not None
    assert issubclass(RunInFlight, ValueError)  # the API maps ValueError on resume to 409


def test_only_expired_node_leases_are_requeued() -> None:
    clock = Clock()
    store = InMemoryRunStore()
    calls: list[str] = []

    def executor(node: RunNode) -> CollectionResult:
        calls.append(node.node_id)
        return _result(node, CollectionStatus.FOUND)

    engine = RunEngine(store, {"p": executor}, clock=clock, lease_seconds=60)
    run_id = engine.create("proj", "r1", {}, RunDAG([RunNode(node_id="n", provider="p")])).run_id
    record = store.load(run_id)
    # A worker in another process started the node and still holds both leases.
    record.status = ExecutionStatus.RUNNING
    record.lease_owner = "other"
    record.lease_expires_at = NOW + timedelta(seconds=60)
    node = record.nodes["n"]
    node.status = ExecutionStatus.RUNNING
    node.attempts = 1
    node.lease_owner = "other"
    node.lease_expires_at = NOW + timedelta(seconds=60)
    store.save(record)

    assert engine.execute(run_id).status is ExecutionStatus.RUNNING
    assert calls == [] and store.load(run_id).nodes["n"].lease_owner == "other"

    clock.now = NOW + timedelta(seconds=61)  # that worker died: its leases expired
    done = engine.execute(run_id)
    assert done.status is ExecutionStatus.COMPLETED and calls == ["n"]
    assert done.nodes["n"].attempts == 2 and done.nodes["n"].lease_owner is None
    assert done.lease_owner is None


def test_superseded_worker_result_does_not_land_in_the_newer_revision() -> None:
    clock = Clock()
    store = InMemoryRunStore()
    started, release = threading.Event(), threading.Event()

    def executor(node: RunNode) -> CollectionResult:
        if not started.is_set():
            started.set()
            assert release.wait(5)
            return _result(node, CollectionStatus.EMPTY, items=[{"stale": True}])
        return _result(node, CollectionStatus.FOUND, items=[{"fresh": True}])

    engine = RunEngine(store, {"p": executor}, concurrency={"p": 2}, clock=clock, lease_seconds=60)
    run_id = engine.create("proj", "r1", {}, RunDAG([RunNode(node_id="n", provider="p")])).run_id
    worker = threading.Thread(target=lambda: engine.execute(run_id))
    worker.start()
    assert started.wait(5)
    clock.now = NOW + timedelta(seconds=61)  # the first worker's lease lapsed
    resumed = engine.resume(run_id)
    release.set()
    worker.join(5)
    assert resumed.run_revision == 2
    latest = store.load(run_id)
    assert latest.run_revision == 2 and latest.status is ExecutionStatus.COMPLETED
    assert latest.results["n"].items == [{"fresh": True}]
    assert [item.items for item in latest.late_results] == [[{"stale": True}]]


# ------------------------------------------------------------------ output attach (S29)


def test_cancel_during_evaluation_keeps_the_run_cancelled() -> None:
    store = InMemoryRunStore()
    flow = workflow_with(
        store=store, executors={"p": lambda n: _result(n, CollectionStatus.TRUNCATED)}
    )
    original = flow._evaluate
    cancelled: list[str] = []

    def evaluate(record: Any) -> dict[str, Any]:
        cancelled.append(flow.cancel_review(record.run_id, project_id="proj-1")["execution_status"])
        return original(record)

    flow._evaluate = evaluate  # type: ignore[method-assign]
    output = flow.start_review(request(requested_sources=[RunNode(node_id="n", provider="p")]))
    assert cancelled == [ExecutionStatus.CANCELLED.value]
    assert output["execution_status"] == ExecutionStatus.CANCELLED.value
    stored = store.load(output["run_id"])
    assert stored.status is ExecutionStatus.CANCELLED and stored.output is None


def test_output_is_not_attached_to_a_revision_that_changed() -> None:
    store = InMemoryRunStore()
    flow = workflow_with(store=store)
    run_id = flow.start_review(request())["run_id"]
    record = store.load(run_id)
    assert flow.engine.attach_output(run_id, 1, record.status, {"forged": True}).output == (
        record.output
    )
    cancelled = flow.engine.attach_output(run_id, 1, ExecutionStatus.PARTIAL, {"forged": True})
    assert cancelled.output == record.output


# ------------------------------------------------------------------ resume and failures


def test_rejected_supplement_opens_no_revision_and_rewrites_none() -> None:
    store = InMemoryRunStore()
    flow = workflow_with(store=store)
    run_id = flow.start_review(request())["run_id"]
    first_context = store.load(run_id, 1).context
    second = flow.resume_review(run_id, project_id="proj-1", supplement=[claim(True)])
    assert second["run_revision"] == 2
    assert store.load(run_id, 1).context == first_context
    with pytest.raises(ValueError, match="c1"):
        flow.resume_review(run_id, project_id="proj-1", supplement=[claim(False)])
    assert store.revisions(run_id) == [1, 2]
    assert flow.get_review(run_id, project_id="proj-1") == second
    third = flow.resume_review(run_id, project_id="proj-1")
    assert third["run_revision"] == 3 and third["summary"] is not None
    assert flow.save_work(run_id, project_id="proj-1").run_revision == 3


def test_failed_evaluation_marks_the_revision_failed() -> None:
    store = InMemoryRunStore()
    flow = workflow_with(store=store)

    def broken(_record: Any) -> dict[str, Any]:
        raise RuntimeError("synthetic evaluation fault")

    original = flow._evaluate
    flow._evaluate = broken  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        flow.start_review(request())
    run_id = next(iter(store._rows))
    stored = store.load(run_id)
    assert stored.status is ExecutionStatus.FAILED and stored.output is None
    assert "synthetic evaluation fault" in (stored.failure or "")
    read = flow.get_review(run_id, project_id="proj-1")
    assert read["execution_status"] == ExecutionStatus.FAILED.value and read["failure"]
    with pytest.raises(ValueError, match="no output"):
        flow.save_work(run_id, project_id="proj-1")

    flow._evaluate = original  # type: ignore[method-assign]
    recovered = flow.resume_review(run_id, project_id="proj-1")
    assert recovered["run_revision"] == 2
    assert recovered["execution_status"] == ExecutionStatus.COMPLETED.value
    assert store.load(run_id, 1).status is ExecutionStatus.FAILED


# ------------------------------------------------------------------ races on start and resume


def test_second_resume_before_the_first_takes_its_lease_is_refused() -> None:
    store = InMemoryRunStore()
    flow = workflow_with(
        store=store, executors={"p": lambda n: _result(n, CollectionStatus.TRUNCATED)}
    )
    run_id = flow.start_review(request(requested_sources=[RunNode(node_id="n", provider="p")]))[
        "run_id"
    ]
    original = flow.engine.execute
    second: list[BaseException] = []

    def execute(rid: str, **kwargs: Any) -> Any:
        # Revision 2 exists but execute() has not run yet: a second resume arrives now.
        if not second:
            try:
                flow.resume_review(rid, project_id="proj-1")
            except RunInFlight as exc:
                second.append(exc)
            else:
                second.append(AssertionError("second resume was accepted"))
        return original(rid, **kwargs)

    flow.engine.execute = execute  # type: ignore[method-assign]
    first = flow.resume_review(run_id, project_id="proj-1")
    assert len(second) == 1 and isinstance(second[0], RunInFlight)  # the API answers 409
    assert first["run_revision"] == 2
    assert store.revisions(run_id) == [1, 2]
    assert store.load(run_id, 2).status is not ExecutionStatus.QUEUED


def test_concurrent_first_start_with_one_key_calls_the_provider_once() -> None:
    calls: list[str] = []
    started, release = threading.Event(), threading.Event()

    def slow(node: RunNode) -> CollectionResult:
        calls.append(node.node_id)
        started.set()
        release.wait(5)
        return _result(node, CollectionStatus.FOUND)

    store = InMemoryRunStore()
    flow = workflow_with(store=store, executors={"p": slow})
    req = request(requested_sources=[RunNode(node_id="n", provider="p")], idempotency_key="k")
    barrier = threading.Barrier(2)
    real_find = store.find_by_key
    saved_by_a = threading.Event()

    def find(key: str) -> Any:
        found = real_find(key)
        try:
            barrier.wait(0.5)  # both callers looked the key up before either saved
        except threading.BrokenBarrierError:
            return found  # lookups are serialised: no race window
        if threading.current_thread().name == "B":
            saved_by_a.wait(5)  # B saves only once A's worker is inside the provider
        return found

    store.find_by_key = find  # type: ignore[method-assign]
    out: dict[str, Any] = {}
    a = threading.Thread(name="A", target=lambda: out.__setitem__("A", flow.start_review(req)))
    b = threading.Thread(name="B", target=lambda: out.__setitem__("B", flow.start_review(req)))
    a.start()
    b.start()
    assert started.wait(5)
    saved_by_a.set()
    b.join(1)
    release.set()
    a.join(5)
    b.join(5)
    assert calls == ["n"]
    record = store.load(out["A"]["run_id"])
    assert record.nodes["n"].attempts == 1 and record.late_results == []
    assert out["A"]["run_id"] == out["B"]["run_id"]


def test_start_retry_after_a_failed_evaluation_keeps_the_revision_failed() -> None:
    store = InMemoryRunStore()
    flow = workflow_with(store=store)
    original = flow._evaluate
    failing = [True]

    def evaluate(record: Any) -> dict[str, Any]:
        if failing[0]:
            raise RuntimeError("transient evaluation fault")
        return original(record)

    flow._evaluate = evaluate  # type: ignore[method-assign]
    req = request()
    with pytest.raises(RuntimeError):
        flow.start_review(req)
    run_id = next(iter(store._rows))
    failing[0] = False
    retried = flow.start_review(req)
    assert retried["execution_status"] == ExecutionStatus.FAILED.value
    stored = store.load(run_id)
    assert stored.status is ExecutionStatus.FAILED and stored.output is None
    assert "transient evaluation fault" in (stored.failure or "")
    assert store.revisions(run_id) == [1]
    with pytest.raises(ValueError, match="no output"):
        flow.save_work(run_id, project_id="proj-1")
