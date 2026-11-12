"""Durable ingestion jobs on DBOS Transact (``jobs`` extra).

Ingestion is a chain of slow, failure-prone steps: parse (OCR, Docling or kordoc can take minutes),
load into the canonical graph, extract relation candidates. Running that chain inside an HTTP
request loses work on a timeout or a restart. Here each file is one **DBOS workflow** whose steps
are checkpointed in a system database; a crashed or restarted worker resumes the workflow at the
first unfinished step, and a finished step is never run twice. Workflows wait in a DBOS queue with
a per-process concurrency limit, so a batch of 500 scanned PDFs does not start 500 OCR calls.

DBOS is a library, not a server: the system database is the existing PostgreSQL in production
(``SION_JOBS_DATABASE_URL``, default ``SION_DATABASE_URL`` when that is PostgreSQL) or a local
SQLite file in development. Every step is idempotent on its own, because the loaders key rows by
stable keys, so a retried step never duplicates nodes, edges or evidence.

Steps of ``ingest_file``:

1. ``parse``      text, extractor and page count through the document parser (retried up to 3
                  times on transient errors; an unreadable file or missing parser is a skip)
2. ``load``       document + claim nodes and evidence into the canonical store (unverified)
3. ``relations``  rule-based relation candidates for review (optional)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sion_core import require

QUEUE = "sion-ingest"
APP_NAME = "sion-ingest"
TERMINAL = {"SUCCESS", "ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED"}

_state: dict[str, Any] = {"factory": None, "queue": None}


def _dbos():
    return require("dbos", extra="jobs").DBOS


def _session():
    factory = _state["factory"]
    if factory is None:
        raise RuntimeError("jobs are not configured: call sion_ingestion.jobs.start(factory)")
    return factory()


# --------------------------------------------------------------------------- workflow

def _register() -> dict[str, Any]:
    """Declare steps and the workflow once (DBOS keeps them in a process-wide registry)."""
    if "workflow" in _state:
        return _state
    DBOS = _dbos()

    @DBOS.step(name="parse", retries_allowed=True, max_attempts=3)
    def parse(path: str) -> dict[str, Any]:
        from sion_core import MissingExtra

        from sion_ingestion.document_ingest import DocumentUnreadable, extract_text

        try:
            content = extract_text(Path(path))
        except (DocumentUnreadable, MissingExtra) as exc:  # permanent: report, do not retry
            return {"unreadable": str(exc)}
        return {"text": content.text, "extractor": content.extractor, "page_count": content.page_count,
                "notes": list(getattr(content, "notes", ()) or ())}

    @DBOS.step(name="load")
    def load(path: str, parsed: dict[str, Any]) -> dict[str, Any]:
        from sion_ingestion.document_ingest import (
            ExtractedText,
            attach_document_evidence,
            build_document_export,
        )
        from sion_ingestion.map_import import import_map_export

        p = Path(path)
        content = ExtractedText(parsed["text"], parsed["extractor"], parsed["page_count"])
        export = build_document_export([p], extracted={p: content})
        with _session() as session:
            result = import_map_export(session, export)
            evidence = attach_document_evidence(session, export)
        return {"created_nodes": result.created_nodes, "created_edges": result.created_edges,
                "skipped_nodes": result.skipped_nodes, "skipped_edges": result.skipped_edges,
                "evidence_created": evidence}

    @DBOS.step(name="relations")
    def relations(path: str) -> dict[str, Any]:
        from sion_ingestion.relation_extraction import extract_relation_candidates

        with _session() as session:
            out = extract_relation_candidates(session, [Path(path)])
        return {k: out[k] for k in ("proposals", "candidates_created", "candidates_updated", "evidence_created")}

    @DBOS.workflow(name="sion.ingest_file")
    def ingest_file(path: str, extract_relations: bool = True) -> dict[str, Any]:
        parsed = parse(path)
        if "unreadable" in parsed:
            return {"path": path, "status": "skipped", "reason": parsed["unreadable"]}
        summary: dict[str, Any] = {"path": path, "extractor": parsed["extractor"], "page_count": parsed["page_count"],
                                   "notes": parsed["notes"]}
        if not parsed["text"].strip():
            return {**summary, "status": "skipped", "reason": "no extractable text"}
        summary["load"] = load(path, parsed)
        if extract_relations:
            summary["relations"] = relations(path)
        return {**summary, "status": "ingested", "verification_state": "unverified"}

    _state.update(workflow=ingest_file)
    return _state


# --------------------------------------------------------------------------- lifecycle

def system_database_url(app_database_url: str | None = None) -> str:
    explicit = os.getenv("SION_JOBS_DATABASE_URL")
    if explicit:
        return explicit
    app_url = app_database_url or os.getenv("SION_DATABASE_URL", "")
    if app_url.startswith(("postgresql", "postgres")):
        return app_url  # DBOS keeps its tables in its own schema (dbos)
    root = Path(os.getenv("SION_RUNTIME_DIR", Path(__file__).resolve().parents[3] / "runtime"))
    root.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(root / 'sion-jobs.sqlite').as_posix()}"


def start(factory, *, database_url: str | None = None, concurrency: int | None = None) -> None:
    """Launch DBOS in this process: recover unfinished workflows and start consuming the queue."""
    DBOS = _dbos()
    _register()
    _state["factory"] = factory
    if _state["queue"] is not None:
        return
    DBOS(config={"name": APP_NAME, "system_database_url": database_url or system_database_url(),
                 "application_version": "sion-ingest-1", "run_migrations": True})
    DBOS.launch()
    workers = concurrency or int(os.getenv("SION_JOBS_CONCURRENCY", "2"))
    _state["queue"] = DBOS.register_queue(QUEUE, worker_concurrency=workers)


def stop() -> None:
    if _state["queue"] is None:
        return
    _dbos().destroy(destroy_registry=False)
    _state["queue"] = None


def started() -> bool:
    return _state["queue"] is not None


# --------------------------------------------------------------------------- API helpers

def enqueue(paths: list[Path], *, extract_relations: bool = True) -> list[dict[str, str]]:
    if not started():
        raise RuntimeError("jobs are not running")
    workflow = _state["workflow"]
    return [{"job_id": _state["queue"].enqueue(workflow, str(p), extract_relations).workflow_id, "path": str(p)}
            for p in paths]


def _status_out(s) -> dict[str, Any]:
    out = {"job_id": s.workflow_id, "status": s.status, "name": s.name,
           "created_at": s.created_at, "updated_at": s.updated_at}
    if s.status == "SUCCESS":
        out["result"] = s.output
    elif s.status in TERMINAL and s.error is not None:
        out["error"] = str(s.error)
    return out


def get(job_id: str) -> dict[str, Any] | None:
    DBOS = _dbos()
    status = DBOS.get_workflow_status(job_id)
    if status is None:
        return None
    out = _status_out(status)
    out["steps"] = [{"step": st["function_name"], "error": str(st["error"]) if st["error"] else None,
                     "done": st.get("completed_at_epoch_ms") is not None}
                    for st in DBOS.list_workflow_steps(job_id)]
    return out


def wait(job_id: str, timeout: float = 60.0) -> dict[str, Any]:
    """Block until the job is finished (tests and the CLI)."""
    import time

    deadline = time.monotonic() + timeout
    while True:
        out = get(job_id)
        if out and out["status"] in TERMINAL:
            return out
        if time.monotonic() > deadline:
            raise TimeoutError(job_id)
        time.sleep(0.1)


def list_jobs(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    rows = _dbos().list_workflows(status=status, limit=limit, sort_desc=True, queue_name=QUEUE, load_input=False)
    return [_status_out(s) for s in rows]


def cancel(job_id: str) -> None:
    _dbos().cancel_workflow(job_id)


def resume(job_id: str) -> None:
    """Continue a cancelled job from where it stopped."""
    _dbos().resume_workflow(job_id)


def retry(job_id: str) -> str:
    """Re-run a failed job from its first failed step as a new job; earlier steps are reused.

    DBOS records a failed step's error like an output, so resuming would replay the error. A fork
    starts a new workflow that copies the checkpoints before ``start_step`` and runs the rest.
    """
    DBOS = _dbos()
    steps = DBOS.list_workflow_steps(job_id)
    failed = [st["function_id"] for st in steps if st["error"] is not None]
    start_step = failed[0] if failed else (max((st["function_id"] for st in steps), default=0) + 1)
    return DBOS.fork_workflow(job_id, start_step).workflow_id


def main(argv: list[str] | None = None) -> int:
    """``sion-worker``: run DBOS and the ingest queue in a dedicated process (no HTTP)."""
    import argparse
    import signal
    import threading

    from sion_api.config import load_settings
    from sion_api.db import build_engine, build_session_factory

    p = argparse.ArgumentParser(prog="sion-worker", description="Durable ingestion worker (DBOS)")
    p.add_argument("--concurrency", type=int, default=None)
    args = p.parse_args(argv)
    settings = load_settings()
    start(build_session_factory(build_engine(settings.database_url)),
          database_url=system_database_url(settings.database_url), concurrency=args.concurrency)
    done = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: done.set())
    signal.signal(signal.SIGINT, lambda *_: done.set())
    done.wait()
    stop()
    return 0
