"""Review workflow composing the modules of this package (framework plan sections 12-16).

The workflow is stateless apart from its :class:`RunStore`: the request, collected facts and the
output snapshot live in the run record, so a later process can continue from the store alone. An
output snapshot is never rewritten; a resume adds a new revision. Generated text is optional (S30).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from archontos.review.aggregate import legacy_decision, summarize
from archontos.review.applicability import ReviewedRelation, assess, detect_conflicts
from archontos.review.candidates import (
    CandidatePlan,
    ChecklistProfile,
    DesignationLink,
    default_profile,
    generate_candidates,
)
from archontos.review.citations import verify_citations
from archontos.review.facts import FactStore, to_rule_facts
from archontos.review.legal import LegalCatalog
from archontos.review.model import (
    SCHEMA_VERSION,
    Applicability,
    Citation,
    Evidence,
    ExecutionStatus,
    Fact,
    FactStatus,
    Interval,
    LegalEventDates,
    Outcome,
    Proposal,
    ProvisionRef,
    ReviewScope,
    RuleEvaluationRecord,
    Site,
    UnresolvedItem,
    canonical_digest,
)
from archontos.review.rase import RaseRule, evaluate_candidate
from archontos.review.retrieval import RetrievalScope, retrieve, visible
from archontos.review.runs import (
    Executor,
    InMemoryRunStore,
    ReviewOutbox,
    RunDAG,
    RunEngine,
    RunNode,
    RunRecord,
    RunStore,
    idempotency_key,
    missing_ledger,
)

Explainer = Callable[[str, dict[str, Any]], str]


class AccessDenied(PermissionError):
    """A caller asked for material of another project; reported like a missing record."""


class ReviewRequest(BaseModel):
    """Common input fields of section 13."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    proposal: Proposal
    site: Site
    legal_event_dates: LegalEventDates
    review_scope: ReviewScope | None = None
    requested_sources: list[RunNode] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    user_laws: list[ProvisionRef] = Field(default_factory=list)
    hints: list[ProvisionRef] = Field(default_factory=list)
    idempotency_key: str | None = None


class WorkReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    work_id: str
    project_id: str
    run_id: str
    run_revision: int
    digest: str


def client_fact_problems(facts: Sequence[Fact]) -> list[str]:
    """Why caller-supplied facts cannot be accepted as they are.

    A request may state claims. It cannot state official records or evidence: those only come from
    server-side collection, otherwise a caller could manufacture a negative finding.
    """

    problems: list[str] = []
    for fact in facts:
        if fact.method not in {"user_claim", "design_observed"}:
            problems.append(f"{fact.fact_id}: method {fact.method} is reserved for collection")
        if fact.status not in {FactStatus.ASSERTED, FactStatus.UNKNOWN}:
            problems.append(
                f"{fact.fact_id}: status {fact.status.value} is reserved for collection"
            )
        if fact.evidence_ids:
            problems.append(f"{fact.fact_id}: a claim cannot cite evidence")
    return problems


def _proposal_facts(request: ReviewRequest) -> list[Fact]:
    """Design inputs are user claims in force at the governing date, not public record."""

    day = request.legal_event_dates.governing_date()
    proposal = request.proposal
    recorded = datetime.combine(request.legal_event_dates.review_date, datetime.min.time(), UTC)
    values: dict[str, Any] = {**{f"proposal.{k}": v for k, v in proposal.scale.items()}}
    values["proposal.actions"] = list(proposal.actions)
    values["proposal.uses"] = list(proposal.uses)
    return [
        Fact(
            fact_id=f"proposal:{proposal.revision}:{path}",
            path=path,
            subject=proposal.project_id,
            value=value,
            status=FactStatus.ASSERTED,
            method="user_claim",
            validity=Interval(valid_from=day),
            recorded_at=recorded,
        )
        for path, value in sorted(values.items())
    ]


class ReviewWorkflow:
    def __init__(
        self,
        catalog: LegalCatalog,
        *,
        store: RunStore | None = None,
        executors: Mapping[str, Executor] | None = None,
        links: Sequence[DesignationLink] = (),
        profile: ChecklistProfile | None = None,
        rules: Sequence[RaseRule] = (),
        conditions: Mapping[str, Mapping[str, Any]] | None = None,
        exception_facts: Mapping[str, str] | None = None,
        positions: Mapping[str, Any] | None = None,
        reviewed_relations: Sequence[ReviewedRelation] = (),
        evidence: Sequence[Evidence] = (),
        outbox: ReviewOutbox | None = None,
    ) -> None:
        self.catalog = catalog
        self.store: RunStore = store or InMemoryRunStore()
        self.engine = RunEngine(self.store, executors or {})
        self.links = list(links)
        self.profile = profile or default_profile()
        self.rules = {rule.basis.ref.key: rule for rule in rules}
        self.conditions = dict(conditions or {})  # keyed by topic
        self.exception_facts = dict(exception_facts or {})
        self.positions = dict(positions or {})  # keyed by provision key
        self.reviewed_relations = list(reviewed_relations)
        self.evidence = {item.evidence_id: item for item in evidence}
        self.outbox = outbox or ReviewOutbox()

    # ------------------------------------------------------------------ planning

    def _scope(self, request: ReviewRequest) -> ReviewScope:
        return request.review_scope or self.profile.scope()

    def _fact_store(self, request: ReviewRequest, extra: Sequence[Fact] = ()) -> FactStore:
        store = FactStore()
        for fact in (*_proposal_facts(request), *request.facts, *extra):
            store.add(fact)
        return store

    def _candidates(self, request: ReviewRequest, facts: FactStore) -> CandidatePlan:
        return generate_candidates(
            self._scope(request),
            request.site,
            request.proposal,
            facts,
            self.links,
            self.catalog,
            request.user_laws,
            request.hints,
            day=request.legal_event_dates.governing_date(),
            profile=self.profile,
        )

    def plan_review(self, request: ReviewRequest) -> dict[str, Any]:
        """Fix the scope and show what would be checked, without collecting anything."""

        plan = self._candidates(request, self._fact_store(request))
        dag = RunDAG(request.requested_sources)
        return {
            "schema_version": SCHEMA_VERSION,
            "plan_digest": canonical_digest(request.model_dump(mode="json")),
            "declared_scope": self._scope(request).model_dump(mode="json"),
            "profile_reviewed": self.profile.reviewed,
            "collection_order": dag.order(),
            "coverage_items": [item.model_dump(mode="json") for item in plan.coverage],
            "candidate_provisions": [item.model_dump(mode="json") for item in plan.candidates],
            "unresolved_items": [item.model_dump(mode="json") for item in plan.unresolved],
            "next_tasks": [item.model_dump(mode="json") for item in plan.tasks],
            "canonical": False,
            "read_only": True,
        }

    # ------------------------------------------------------------------ execution

    def start_review(self, request: ReviewRequest) -> dict[str, Any]:
        payload = request.model_dump(mode="json", exclude={"idempotency_key"})
        proposal = request.proposal
        key = request.idempotency_key or idempotency_key(
            proposal.project_id, proposal.revision, payload
        )
        record = self.engine.create(
            proposal.project_id,
            proposal.revision,
            payload,
            RunDAG(request.requested_sources),
            key=key,
            context={"request": payload},
        )
        if record.output is not None or record.status is ExecutionStatus.CANCELLED:
            return self._read(record)
        return self._complete(self.engine.execute(record.run_id))

    def resume_review(
        self,
        run_id: str,
        *,
        project_id: str,
        supplement: Sequence[Fact] = (),
        changed_requests: Mapping[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Continue with supplementary facts as a new revision; old output stays as it was."""

        record = self._owned(run_id, project_id)
        if record.status is ExecutionStatus.CANCELLED:
            raise ValueError("a cancelled run is not resumed; start a new run")
        context = dict(record.context)
        context["supplement"] = [
            *context.get("supplement", []),
            *(fact.model_dump(mode="json") for fact in supplement),
        ]
        record.context = context
        self.store.save(record)
        return self._complete(self.engine.resume(run_id, changed_requests=changed_requests))

    def cancel_review(self, run_id: str, *, project_id: str) -> dict[str, Any]:
        self._owned(run_id, project_id)
        return self._read(self.engine.cancel(run_id))

    def _complete(self, record: RunRecord) -> dict[str, Any]:
        if record.status is ExecutionStatus.CANCELLED:
            return self._read(record)
        record.output = self._evaluate(record)
        self.store.save(record)
        return record.output

    def _collected(
        self, record: RunRecord
    ) -> tuple[list[Fact], dict[str, Evidence], list[UnresolvedItem]]:
        facts: list[Fact] = []
        evidence: dict[str, Evidence] = {}
        quarantined: list[UnresolvedItem] = []
        for node_id, result in sorted(record.results.items()):
            evidence.update({item.evidence_id: item for item in result.evidence})
            for index, item in enumerate(i for i in result.items if "fact" in i):
                try:
                    facts.append(Fact.model_validate(item["fact"]))
                except ValidationError:
                    quarantined.append(
                        UnresolvedItem(
                            item_id="gap:" + canonical_digest([node_id, index, item])[:16],
                            kind="quarantined",
                            detail=f"{node_id}: 형식이 맞지 않는 사실 레코드 격리",
                        )
                    )
        facts.extend(Fact.model_validate(raw) for raw in record.context.get("supplement", []))
        return facts, evidence, quarantined

    def _evaluate(self, record: RunRecord) -> dict[str, Any]:
        request = ReviewRequest.model_validate(record.context["request"])
        collected, evidence, quarantined = self._collected(record)
        facts = self._fact_store(request, collected)
        day = request.legal_event_dates.governing_date()
        plan = self._candidates(request, facts)
        project_id = request.proposal.project_id

        findings = [
            assess(
                candidate,
                facts,
                self.catalog,
                day,
                conditions=self.conditions.get(candidate.topic),
                exception_facts=self.exception_facts,
            )
            for candidate in plan.candidates
        ]
        by_candidate = {finding.candidate_id: finding for finding in findings}

        evaluations: list[RuleEvaluationRecord] = []
        for candidate in plan.candidates:
            if by_candidate[candidate.candidate_id].status is not Applicability.APPLICABLE:
                continue
            rule = self.rules.get(candidate.ref.key)
            if rule is None:
                # An applicable provision nobody evaluated must not read as satisfied.
                evaluations.append(
                    RuleEvaluationRecord(
                        rule_version_id="none",
                        candidate_id=candidate.candidate_id,
                        outcome=Outcome.REVIEW,
                        reason="적용 조문에 검토된 규칙이 없음",
                        input_digest=canonical_digest(candidate.ref.key),
                        reviewed=False,
                    )
                )
                continue
            rule_facts, used, _missing = to_rule_facts(facts, [candidate.subject, project_id], day)
            rule_facts.setdefault("context", {})["jurisdiction"] = request.site.jurisdiction_code
            version = self.catalog.version(candidate.ref.work_id, candidate.ref.version_id)
            evaluations.append(
                evaluate_candidate(
                    rule,
                    rule_facts,
                    candidate_id=candidate.candidate_id,
                    fact_ids=used,
                    current_snapshot_hash=version.snapshot_hash if version else None,
                )
            )

        positions = {
            candidate.candidate_id: self.positions[candidate.ref.key]
            for candidate in plan.candidates
            if candidate.ref.key in self.positions
        }
        conflicts = detect_conflicts(
            plan.candidates,
            findings,
            catalog=self.catalog,
            positions=positions,
            reviewed=self.reviewed_relations,
        )
        gaps, tasks = missing_ledger(record)
        unresolved = [*plan.unresolved, *gaps, *quarantined]
        all_tasks = [*plan.tasks, *tasks]
        summary = summarize(plan.coverage, findings, evaluations, conflicts, unresolved)
        citations = self._citations(plan, {**self.evidence, **evidence}, project_id)
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": record.run_id,
            "run_revision": record.run_revision,
            "project_id": project_id,
            "proposal_revision": record.proposal_revision,
            "execution_status": record.status.value,
            "declared_scope": self._scope(request).model_dump(mode="json"),
            "profile_reviewed": self.profile.reviewed,
            "legal_event_dates": request.legal_event_dates.model_dump(mode="json"),
            "coverage_items": [item.model_dump(mode="json") for item in plan.coverage],
            "source_versions": self._source_versions(record),
            "facts": [fact.model_dump(mode="json") for fact in facts.all()],
            "candidate_provisions": [item.model_dump(mode="json") for item in plan.candidates],
            "applicability_findings": [item.model_dump(mode="json") for item in findings],
            "rule_evaluations": [item.model_dump(mode="json") for item in evaluations],
            "conflicts": [item.model_dump(mode="json") for item in conflicts],
            "unresolved_items": [item.model_dump(mode="json") for item in unresolved],
            "citations": [item.model_dump(mode="json") for item in citations],
            "next_tasks": [item.model_dump(mode="json") for item in all_tasks],
            "summary": summary.model_dump(mode="json"),
            "legacy_decision": legacy_decision(summary),
            "timing": {
                node.node_id: {
                    "started_at": node.started_at.isoformat() if node.started_at else None,
                    "finished_at": node.finished_at.isoformat() if node.finished_at else None,
                    "attempts": node.attempts,
                }
                for node in record.nodes.values()
            },
            "canonical": False,
            "read_only": True,
        }

    @staticmethod
    def _source_versions(record: RunRecord) -> list[dict[str, Any]]:
        return [
            {
                "node_id": node.node_id,
                "provider": node.provider,
                "contract": node.contract,
                "input_digest": node.input_digest,
                "collection": node.collection.value if node.collection else None,
                "artifacts": node.artifacts,
                "reused_from_revision": node.reused_from_revision,
            }
            for node in record.nodes.values()
        ]

    def _citations(
        self, plan: CandidatePlan, evidence: Mapping[str, Evidence], project_id: str
    ) -> list[Citation]:
        provisions = {provision.ref.key: provision for provision in self.catalog.provisions()}
        raw = [
            Citation(
                claim=candidate.reasons[0],
                evidence_ids=[provision.evidence_id],
                provision_key=candidate.ref.key,
            )
            for candidate in plan.candidates
            if (provision := provisions.get(candidate.ref.key)) is not None
            and provision.evidence_id is not None
        ]
        return verify_citations(raw, evidence, provisions, project_id=project_id)

    # ------------------------------------------------------------------ reads

    def _owned(self, run_id: str, project_id: str, revision: int | None = None) -> RunRecord:
        record = self.store.load(run_id, revision)
        if record.project_id != project_id:
            raise AccessDenied(run_id)
        return record

    @staticmethod
    def _read(record: RunRecord) -> dict[str, Any]:
        if record.output is not None:
            if record.status is ExecutionStatus.CANCELLED:
                return {**record.output, "execution_status": record.status.value}
            return record.output
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": record.run_id,
            "run_revision": record.run_revision,
            "project_id": record.project_id,
            "execution_status": record.status.value,
            "canonical": False,
            "read_only": True,
        }

    def get_review(
        self, run_id: str, *, project_id: str, revision: int | None = None
    ) -> dict[str, Any]:
        return self._read(self._owned(run_id, project_id, revision))

    def get_basis(self, evidence_id: str, *, project_id: str) -> dict[str, Any]:
        """Original text and position of one piece of evidence (S25: no cross-project read)."""

        item = self.evidence.get(evidence_id)
        if item is None or not visible(item, project_id):
            raise AccessDenied(evidence_id)
        provision = next(
            (p for p in self.catalog.provisions() if p.evidence_id == evidence_id), None
        )
        return {
            "evidence": item.model_dump(mode="json"),
            "provision": provision.model_dump(mode="json") if provision else None,
        }

    def explain(
        self,
        run_id: str,
        question: str,
        *,
        project_id: str,
        explainer: Explainer | None = None,
    ) -> dict[str, Any]:
        """Deterministic explanation; ``explainer`` may only add prose on top of it (S24, S30)."""

        output = self.get_review(run_id, project_id=project_id)
        basis = {
            finding["candidate_id"]
            for finding in output.get("applicability_findings", [])
            if finding["status"] == Applicability.APPLICABLE.value
        }
        candidates = output.get("candidate_provisions", [])
        request = self.store.load(run_id).context["request"]
        scope = RetrievalScope(
            project_id=project_id,
            as_of=LegalEventDates.model_validate(request["legal_event_dates"]).governing_date(),
            jurisdiction_code=request["site"].get("jurisdiction_code"),
        )
        required = [ProvisionRef.model_validate(c["ref"]) for c in candidates if c["mandatory"]]
        retrieved = retrieve(question, scope, self.catalog, self.evidence, required)
        structured: dict[str, Any] = {
            "question": question,
            "evaluation_basis": [c for c in candidates if c["candidate_id"] in basis],
            "candidates_only": [c for c in candidates if c["candidate_id"] not in basis],
            "provisions": [p.ref.key for p in retrieved.provisions],
            "citations": [c for c in output.get("citations", []) if c["verified"]],
            "unresolved_items": output.get("unresolved_items", []),
            "summary": output.get("summary"),
            "generated": None,
            "generation_error": None,
        }
        if explainer is not None:
            try:
                structured["generated"] = explainer(question, structured)
            except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
                structured["generation_error"] = type(exc).__name__
        return structured

    def compare(
        self,
        run_a: str,
        run_b: str,
        *,
        project_id: str,
        revision_a: int | None = None,
        revision_b: int | None = None,
    ) -> dict[str, Any]:
        """Differences between two stored outputs; neither is modified."""

        first = self.get_review(run_a, project_id=project_id, revision=revision_a)
        second = self.get_review(run_b, project_id=project_id, revision=revision_b)

        def keyed(output: dict[str, Any], field: str, key: str) -> dict[str, Any]:
            return {item[key]: item for item in output.get(field, [])}

        changes: dict[str, Any] = {}
        for field, key in (
            ("facts", "fact_id"),
            ("candidate_provisions", "candidate_id"),
            ("applicability_findings", "candidate_id"),
            ("rule_evaluations", "candidate_id"),
            ("unresolved_items", "item_id"),
        ):
            left, right = keyed(first, field, key), keyed(second, field, key)
            changes[field] = {
                "added": sorted(set(right) - set(left)),
                "removed": sorted(set(left) - set(right)),
                "changed": sorted(k for k in set(left) & set(right) if left[k] != right[k]),
            }
        return {
            "from": {"run_id": run_a, "run_revision": first.get("run_revision")},
            "to": {"run_id": run_b, "run_revision": second.get("run_revision")},
            "changes": changes,
        }

    def briefing(self, run_id: str, *, project_id: str, revision: int | None = None) -> str:
        """Structured Markdown briefing in the order of section 16; no model is involved."""

        output = self.get_review(run_id, project_id=project_id, revision=revision)
        return render_briefing(output)

    # ------------------------------------------------------------------ saving

    def save_work(self, run_id: str, *, project_id: str, notes: str = "") -> WorkReceipt:
        """Queue a stored output for the project and return a receipt to read back."""

        record = self._owned(run_id, project_id)
        if record.output is None:
            raise ValueError("run has no output to save")
        digest = canonical_digest(record.output)
        work_id = "work:" + canonical_digest([project_id, run_id, record.run_revision])[:24]
        receipt = WorkReceipt(
            work_id=work_id,
            project_id=project_id,
            run_id=run_id,
            run_revision=record.run_revision,
            digest=digest,
        )
        self.outbox.enqueue(
            f"{work_id}:{digest}", {**receipt.model_dump(mode="json"), "notes": notes}
        )
        return receipt

    def verify_receipt(self, receipt: WorkReceipt) -> bool:
        """A saved flag is not proof: re-read the revision and compare its digest."""

        stored = self.store.load(receipt.run_id, receipt.run_revision)
        return (
            stored.project_id == receipt.project_id
            and stored.output is not None
            and canonical_digest(stored.output) == receipt.digest
        )


def render_briefing(output: dict[str, Any]) -> str:
    summary = output.get("summary") or {}
    scope = output.get("declared_scope") or {}
    lines = [
        "# 규제 검토 브리핑",
        "",
        f"실행: {output['run_id']} rev {output['run_revision']}"
        f" ({output['execution_status']}) · 제안 revision {output.get('proposal_revision')}",
        f"검토 범위: {scope.get('profile_id')} {scope.get('profile_version')}"
        " (이 프로필 범위의 결과이며 전체 규제 검토가 아닙니다)",
        f"요약 상태: {summary.get('legacy_status')} · 사유 {summary.get('reason_codes')}",
        "",
        "## 확인된 사실",
    ]
    for fact in output.get("facts", []):
        if fact["status"] != FactStatus.UNKNOWN.value:
            lines.append(f"- {fact['subject']} {fact['path']} = {fact['value']} ({fact['status']})")
    lines += ["", "## 주요 제한과 절차"]
    findings = {f["candidate_id"]: f for f in output.get("applicability_findings", [])}
    for candidate in output.get("candidate_provisions", []):
        finding = findings.get(candidate["candidate_id"], {})
        lines.append(
            f"- [{candidate['topic']}] {candidate['ref']['work_id']}"
            f" {candidate['ref']['version_id']}: {finding.get('status', 'candidate')}"
            f" · {'; '.join(finding.get('reasons', candidate['reasons']))}"
        )
    lines += ["", "## 규칙 평가"]
    outcomes = [e for e in output.get("rule_evaluations", []) if e["outcome"]]
    lines += [
        f"- {e['rule_version_id']}: {e['outcome']} · {e.get('reason') or ''}" for e in outcomes
    ]
    if not outcomes:
        lines.append(f"- 없음 ({Outcome.REVIEW.value} 대상 규칙 미연결)")
    lines += ["", "## 예외와 충돌"]
    lines += [f"- {c['topic']}: {c['kind']} · {c['note']}" for c in output.get("conflicts", [])]
    lines += ["", "## 미확인 자료"]
    lines += [f"- {u['kind']}: {u['detail']}" for u in output.get("unresolved_items", [])]
    lines += ["", "## 다음 작업"]
    lines += [
        f"- [ ] ({t['role']}) {t['target']}: {t['reason']}" for t in output.get("next_tasks", [])
    ]
    lines += ["", "## 원문과 버전"]
    lines += [
        f"- {c['provision_key']} · 근거 {', '.join(c['evidence_ids'])}"
        for c in output.get("citations", [])
        if c["verified"]
    ]
    lines += ["", "이 자료는 검토 근거이며 허가 판단이 아닙니다."]
    return "\n".join(lines)
