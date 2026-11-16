"""Regression tests for saving review work and scoping run keys (S26, S27, S29).

A dry run queues nothing; the outbox key covers every field of its payload; a cancelled run is not
saved; the receipt is hashed over exactly the object handed back for storage; a caller's
idempotency key is scoped to its project. All values are synthetic fixtures.
"""

from __future__ import annotations

import pytest
from sion_regulation.review.model import canonical_digest
from test_review_scenarios import (
    ExecutionStatus,
    ReviewOutbox,
    RunNode,
    proposal,
    request,
    workflow_with,
)


def test_dry_run_save_queues_nothing() -> None:
    outbox = ReviewOutbox()
    flow = workflow_with(outbox=outbox)
    run_id = flow.start_review(request())["run_id"]
    preview = flow.save_work(run_id, project_id="proj-1", notes="a", dry_run=True)
    assert outbox.pending() == []
    assert flow.save_work(run_id, project_id="proj-1", notes="a") == preview
    assert len(outbox.pending()) == 1


def test_outbox_key_covers_the_notes_it_carries() -> None:
    outbox = ReviewOutbox()
    flow = workflow_with(outbox=outbox)
    run_id = flow.start_review(request())["run_id"]
    first = flow.save_work(run_id, project_id="proj-1", notes="a")
    # Different notes are a different payload under a different key, not a key conflict.
    assert flow.save_work(run_id, project_id="proj-1", notes="b") == first
    assert flow.save_work(run_id, project_id="proj-1", notes="b") == first
    assert sorted(entry.payload["notes"] for entry in outbox.pending()) == ["a", "b"]


def test_cancelled_run_is_not_saved() -> None:
    outbox = ReviewOutbox()
    flow = workflow_with(outbox=outbox)
    nodes = [RunNode(node_id="n", provider="no-executor")]
    output = flow.start_review(request(requested_sources=nodes))
    assert output["execution_status"] == "partial"
    cancelled = flow.cancel_review(output["run_id"], project_id="proj-1")
    assert cancelled["execution_status"] == ExecutionStatus.CANCELLED.value
    with pytest.raises(ValueError, match="cancelled"):
        flow.save_work(output["run_id"], project_id="proj-1")
    with pytest.raises(ValueError, match="cancelled"):
        flow.prepare_work(output["run_id"], project_id="proj-1")
    assert outbox.pending() == []


def test_receipt_is_hashed_over_the_returned_output() -> None:
    flow = workflow_with()
    run_id = flow.start_review(request())["run_id"]
    receipt, output = flow.prepare_work(run_id, project_id="proj-1")
    assert canonical_digest(output) == receipt.digest
    assert flow.verify_receipt(receipt)


def test_caller_idempotency_keys_are_scoped_per_project() -> None:
    flow = workflow_with()
    mine = flow.start_review(request(idempotency_key="k1"))
    other = flow.start_review(
        request(idempotency_key="k1", the_proposal=proposal(project_id="proj-2"))
    )
    assert other["project_id"] == "proj-2" and other["run_id"] != mine["run_id"]
    assert flow.start_review(request(idempotency_key="k1")) == mine
