"""Real upstream NVIDIA semantic compilation and text-to-SQL on disposable Sion data.

Every DB and credential in this script is ephemeral inside one GitHub runner.
The actual NIM key is placed in nvidia/.env by a separate protected CI step.
No persistent deployment, no Sion source data, no production access, no writes
to the canonical Sion graph. Only aggregates are printed in logs.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

BASE = "http://localhost:3000"
TIMEOUT = 1500
GOLD = 2
ALLOWLIST_VIEW = "sion_nv_pilot.verified_project_objects"
GITHUB_WORKSPACE = Path(os.environ["GITHUB_WORKSPACE"])
ENV_FILE = GITHUB_WORKSPACE / "nvidia" / ".env"


def log(message: str) -> None:
    print(message, flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as out:
            out.write(message.replace("|", r"\|") + "\n")


def cfg() -> dict[str, str]:
    return dict(
        line.partition("=")[::2] for line in ENV_FILE.read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )


def verify_catalog_source(values: dict[str, str]) -> None:
    """Prove source rows, isolation and read-only role via real psycopg."""
    import psycopg

    tests = (
        ("allowlist", "SELECT COUNT(*) FROM sion_nv_pilot.verified_project_objects", 2),
        ("rejected", "SELECT COUNT(*) FROM sion_nv_pilot.verified_project_objects WHERE object_name='Door-Rejected'", 0),
        ("other-project", "SELECT COUNT(*) FROM sion_nv_pilot.verified_project_objects WHERE object_name='Project-B-Private-Door'", 0),
    )
    try:
        with psycopg.connect(
            host="127.0.0.1", port=15432,
            dbname="sion_nvidia_ci",
            user="nvidia_pilot_reader",
            password="ci_only_test_password_0101",
            connect_timeout=10,
            autocommit=True,
        ) as conn:
            state = conn.execute("SHOW default_transaction_read_only").fetchone()
            if not state or state[0] != "on":
                raise AssertionError("synthetic source account is not read-only")
            for label, sql, expected in tests:
                actual = conn.execute(sql).fetchone()
                if not actual or actual[0] != expected:
                    raise AssertionError(f"synthetic {label} view count mismatch")
            try:
                conn.execute("SELECT COUNT(*) FROM public.entities").fetchone()
            except psycopg.Error as error:
                if error.sqlstate not in ("42501", "42P01"):
                    raise AssertionError("unexpected permissions failure") from None
            else:
                raise AssertionError("synthetic source can read restricted canonical table")
    except psycopg.Error as error:
        # SQLSTATE is an error category, not a credential or response payload.
        category = "other"
        description = str(error).casefold()
        for term, label in (
            ("too many connections", "role_connection_limit"),
            ("connection limit", "role_connection_limit"),
            ("remaining connection slots", "server_connection_limit"),
            ("connection refused", "connection_refused"),
            ("password authentication", "auth_failure"),
            ("no pg_hba", "pg_hba_denied"),
            ("timeout", "connection_timeout"),
        ):
            if term in description:
                category = label
                break
        log("FAIL synthetic PostgreSQL preflight category=" + category
            + " class=" + type(error).__name__
            + " SQLSTATE=" + str(error.sqlstate or "none"))
        raise AssertionError("synthetic source preflight failed") from None
    log("PASS synthetic PostgreSQL reader: 2 allowed rows, cross-project and rejected rows denied")


def sign_in_and_issue_token(client: httpx.Client, values: dict[str, str]) -> dict[str, str]:
    end = time.monotonic() + 150
    while time.monotonic() < end:
        try:
            resp = client.get("/", timeout=5)
            if resp.status_code in (200, 301, 302, 303, 307, 308):
                break
        except httpx.RequestError:
            pass
        time.sleep(3)
    else:
        raise RuntimeError("NVIDIA frontend did not become ready")
    resp = client.post(
        "/api/auth/sign-in/email",
        headers={"Origin": BASE},
        json={"email": values["AUTO_ONTOLOGY_ADMIN_EMAIL"],
              "password": values["AUTO_ONTOLOGY_ADMIN_PASSWORD"]},
        timeout=25,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"NVIDIA bootstrap admin authentication HTTP {resp.status_code}")
    token = client.post(
        "/api/api-tokens",
        headers={"Origin": BASE},
        json={"name": "ci-live-compiler-ephemeral", "expires_in_days": 1},
        timeout=25,
    )
    if token.status_code != 201:
        raise RuntimeError(f"NVIDIA token issue HTTP {token.status_code}")
    secret = token.json().get("token", "")
    if not isinstance(secret, str) or not secret.startswith("auto_ontology_"):
        raise RuntimeError("NVIDIA token issuance returned invalid shape")
    log("PASS real NVIDIA frontend auth and ephemeral authenticated API token")
    return {"x-api-key": secret}


def run_compile(client: httpx.Client, auth: dict[str, str]) -> dict:
    # Initial metadata ingestion starts at service boot. The official semantic
    # scheduler itself waits for the first ingestion pass, avoiding a race.
    # The public Next.js gateway exposes PUT /api/configurations/semantic-compilation,
    # which stores the flag and relays the trigger to private FastAPI. The
    # backend-only /api/semantic-compilation/trigger is deliberately not
    # published by Next.js and returns 404 on :3000.
    start = client.put(
        "/api/configurations/semantic-compilation",
        headers=auth, json={"enabled": True},
        timeout=25,
    )
    if start.status_code != 200 or start.json().get("enabled") is not True:
        raise RuntimeError(f"frontend semantic compilation enable HTTP {start.status_code}")
    log("PASS official public NVIDIA frontend compilation flag enabled and trigger dispatched")
    deadline = time.monotonic() + TIMEOUT
    last_notice = 0.0
    seen_running = False
    while time.monotonic() < deadline:
        try:
            response = client.get("/api/semantic-compilation/status", headers=auth, timeout=15)
            if response.status_code != 200:
                raise RuntimeError(f"semantic status HTTP {response.status_code}")
            status = response.json()
            if not isinstance(status, dict):
                raise ValueError("semantic status is not an object")
            seen_running = seen_running or status.get("running") is True
            if status.get("last_success_at") and status.get("calculated") is True:
                log("PASS official NVIDIA semantic compilation completed with nonempty layer")
                return status
            if status.get("last_failure_at") and not status.get("last_success_at"):
                raise RuntimeError("official NVIDIA compilation recorded a failed run")
        except (httpx.RequestError, ValueError) as exc:
            # A short service restart is possible; do not log any response bodies.
            if time.monotonic() + 40 > deadline:
                raise RuntimeError(f"no semantic completion before deadline: {type(exc).__name__}")
        if time.monotonic() - last_notice > 60:
            log("NVIDIA semantic compilation still running (status-only; no internal logs)")
            last_notice = time.monotonic()
        time.sleep(15)
    raise TimeoutError(f"semantic compilation did not complete within {TIMEOUT}s; seen_running={seen_running}")


def verify_terms(client: httpx.Client, auth: dict[str, str]) -> None:
    response = client.get("/api/terms?limit=20", headers=auth, timeout=30)
    if response.status_code != 200:
        raise AssertionError(f"compiled term list HTTP {response.status_code}")
    data = response.json()
    terms = data.get("terms") if isinstance(data, dict) else None
    if not isinstance(terms, list) or len(terms) < 1:
        raise AssertionError("official semantic compiler created no Term")
    # Generated concepts stay upstream advisory only; no promotion to Sion.
    log(f"PASS official NVIDIA ontology materialized {len(terms)} Term(s) [unverified]")


def scalar_counts(value: object) -> list[int]:
    """Validate a numerical answer without relying on fixed LLM column alias."""
    if isinstance(value, bool):
        return []
    if isinstance(value, int):
        return [value]
    if isinstance(value, float) and value.is_integer():
        return [int(value)]
    if isinstance(value, dict):
        return [number for v in value.values() for number in scalar_counts(v)]
    if isinstance(value, list):
        return [number for v in value for number in scalar_counts(v)]
    return []


def ask_official_agent(client: httpx.Client, auth: dict[str, str]) -> None:
    prompt = (
        "Count the number of approved door objects in the available source. "
        "Use only the permitted view sion_nv_pilot.verified_project_objects. "
        "Return the SQL count, not individual rows. Do not use other tables."
    )
    stream_timeout = httpx.Timeout(connect=15, read=130, write=20, pool=15)
    deadline = time.monotonic() + 900
    ended = False
    answer = None
    sql_passed = False
    count_events = 0
    with client.stream(
        "POST", "/api/chat/completions",
        headers=auth, json={"question": prompt},
        timeout=stream_timeout,
    ) as resp:
        if resp.status_code != 200:
            raise RuntimeError(f"NVIDIA official NL2SQL HTTP {resp.status_code}")
        for line in resp.iter_lines():
            if time.monotonic() >= deadline:
                raise TimeoutError("NVIDIA official text-to-SQL stream deadline reached")
            if not line.startswith("data:"):
                continue
            wire = line[5:].strip()
            if wire == "[DONE]":
                ended = True
                break
            if len(wire) > 200_000:
                raise ValueError("oversize SSE event")
            item = json.loads(wire)
            count_events += 1
            if count_events > 2000:
                raise ValueError("too many SSE events")
            typ = item.get("type")
            if typ == "error":
                raise RuntimeError("NVIDIA agent emitted error (response redacted)")
            if typ == "sql":
                candidate = str(item.get("sql", ""))
                sql_passed = ALLOWLIST_VIEW in candidate or "verified_project_objects" in candidate
            if typ == "result":
                answer = item.get("answer")
    if not ended or not isinstance(answer, dict):
        raise AssertionError("NVIDIA NL2SQL returned no final result and [DONE]")
    query = str(answer.get("sql_code", ""))
    if not query or ("verified_project_objects" not in query and not sql_passed):
        raise AssertionError("NVIDIA SQL did not reference the approved synthetic view")
    if any(x in query.casefold() for x in ("delete ", "update ", "insert ", "drop ", "public.entities", "public.relations", "public.evidence")):
        raise AssertionError("unexpected non-read-only or base table SQL")
    rows = answer.get("sql_response_from_db")
    if GOLD not in scalar_counts(rows):
        raise AssertionError("official NVIDIA agent SQL result disagrees with synthetic golden count 2")
    log("PASS real NVIDIA retrieval + official NL2SQL agent + guarded PostgreSQL execution: count=2")
    log(f"PASS official NVIDIA SSE events={count_events}, result and [DONE] observed; model/key/SQL text redacted")


def main() -> None:
    values = cfg()
    if values.get("POSTGRES_DATABASE") != "auto_ontology" or not values.get("DEFAULT_MODELS_API_KEY", "").startswith("nvapi-"):
        raise RuntimeError("wrong isolation environment or missing NIM")
    verify_catalog_source(values)
    with httpx.Client(base_url=BASE, follow_redirects=False, trust_env=False) as client:
        auth = sign_in_and_issue_token(client, values)
        run_compile(client, auth)
        verify_terms(client, auth)
        ask_official_agent(client, auth)
    log("PASS entire official NVIDIA ingestion -> semantic compilation -> Term -> NL2SQL (synthetic data)")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, AssertionError, TimeoutError, httpx.HTTPError) as error:
        # Do not print arbitrary error string; upstream can include private diagnostics.
        safe = str(error)
        if not any(word in safe.lower() for word in ("key", "secret", "token", "password", "dsn", "authorization")):
            log("FAIL official NVIDIA E2E: " + safe[:180])
        else:
            log("FAIL official NVIDIA E2E: " + type(error).__name__ + " (details redacted)")
        sys.exit(1)
