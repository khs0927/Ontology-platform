"""Two-call NVIDIA Developer API pilot, strictly bounded and synthetic-only.

Never touches real Sion tables or runs a query against an external database.
Only test data below is sent to NVIDIA; no model text or secrets enter logs.
No retry, fallback endpoint, billing API, credential write or deployment.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
import ssl

API = "https://integrate.api.nvidia.com/v1"
EXPECTED = ("nvidia/nemotron-3.5-lightning-30b-a3b",
            "nvidia/nemotron-3-super-120b-a12b",
            "nvidia/nemotron-3.5-super-vl-120b-a12b")
MAX_CALLS = 2
MAX_OUTPUT = (256, 160)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def client():
    return build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))


def report(line: str) -> None:
    print(line)
    dest = os.getenv("GITHUB_STEP_SUMMARY")
    if dest:
        with open(dest, "a", encoding="utf-8") as file:
            file.write(line.replace("|", "\\|") + "\n")


def request_json(opener, path: str, key: str, payload: dict | None = None) -> dict:
    method = "POST" if payload is not None else "GET"
    data = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
    req = Request(API + path, data=data, method=method, headers={
        "Authorization": "Bearer " + key,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "sion-synthetic-ontology-two-call-ci/1.0",
    })
    with opener.open(req, timeout=25) as res:
        raw = res.read(350_001)
        if len(raw) > 350_000:
            raise ValueError("response size bound exceeded")
        return json.loads(raw)


def choose_model(models: dict) -> str | None:
    items = models.get("data")
    if not isinstance(items, list):
        return None
    ids = {item.get("id") for item in items if isinstance(item, dict)}
    return next((model for model in EXPECTED if model in ids), None)


def extract_object(s: str) -> dict:
    if not isinstance(s, str) or len(s) > 3000:
        raise ValueError("not a bounded text answer")
    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object returned")
    obj = json.loads(s[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("non-object JSON")
    return obj


def ontology_valid(obj: dict) -> bool:
    terms = obj.get("terms")
    links = obj.get("relationships")
    if not isinstance(terms, list) or not isinstance(links, list):
        return False
    allowed = {"door_name", "project_name", "verification_state"}
    found = set()
    for term in terms:
        if not isinstance(term, dict):
            return False
        name = term.get("name")
        cols = term.get("mapped_columns")
        if name not in {"Door", "Project"} or not isinstance(cols, list):
            return False
        if not cols or not set(cols) <= allowed or not all(isinstance(x, str) for x in cols):
            return False
        if name == "Door" and "door_name" not in cols:
            return False
        if name == "Project" and "project_name" not in cols:
            return False
        found.add(name)
    rel_ok = any(isinstance(x, dict)
                 and x.get("source") == "Door"
                 and x.get("target") == "Project"
                 and x.get("type") == "PART_OF"
                 for x in links)
    return found == {"Door", "Project"} and rel_ok


def synthetic_database():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE approved_door_view (door_name TEXT, project_name TEXT, verification_state TEXT)")
    conn.executemany("INSERT INTO approved_door_view VALUES (?, ?, ?)", [
        ("Door-101", "Project A", "human_verified"),
        ("Door-102", "Project A", "human_verified"),
    ])
    conn.execute("CREATE TABLE private_rows (door_name TEXT, project_name TEXT)")
    conn.executemany("INSERT INTO private_rows VALUES (?, ?)", [
        ("Door-Rejected", "Project A"),
        ("Project-B-Private-Door", "Project B"),
    ])
    return conn


def safe_sql_count(sql: str) -> int:
    if not isinstance(sql, str) or len(sql) > 1000:
        raise ValueError("invalid SQL payload")
    if not re.match(r"^\s*SELECT\b", sql, flags=re.I):
        raise ValueError("not a SELECT")
    # Only SELECT, read of the approved synthetic view, and COUNT are authorized.
    # This is a hard privilege boundary, not a regex-only SQL validator.
    conn = synthetic_database()
    attempts = [0]

    def permit(action, table, field, database, trigger):
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ and table == "approved_door_view" and field in {
            "door_name", "project_name", "verification_state", ""
        }:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and str(field).lower() == "count":
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    def limit_instructions():
        attempts[0] += 1
        return 1 if attempts[0] >= 100 else 0

    conn.set_authorizer(permit)
    conn.set_progress_handler(limit_instructions, 1000)
    try:
        row = conn.execute(sql).fetchall()
        if len(row) != 1 or len(row[0]) != 1 or type(row[0][0]) is not int:
            raise ValueError("expected exactly one count result")
        return row[0][0]
    finally:
        conn.close()


def self_test() -> None:
    assert safe_sql_count(
        "SELECT COUNT(*) FROM approved_door_view WHERE project_name = 'Project A'"
        " AND verification_state = 'human_verified'"
    ) == 2
    for dangerous in (
        "DELETE FROM approved_door_view",
        "SELECT count(*) FROM private_rows",
        "SELECT count(*) FROM sqlite_master",
        "SELECT load_extension('x')",
        "SELECT count(*) FROM approved_door_view; DROP TABLE approved_door_view",
    ):
        try:
            safe_sql_count(dangerous)
        except (sqlite3.DatabaseError, ValueError):
            pass
        else:
            raise AssertionError("unsafe query accepted")
    assert ontology_valid({"terms": [
        {"name": "Door", "mapped_columns": ["door_name"]},
        {"name": "Project", "mapped_columns": ["project_name"]},
    ], "relationships": [{"source": "Door", "target": "Project", "type": "PART_OF"}]})
    assert not ontology_valid({"terms": [
        {"name": "Door", "mapped_columns": ["private_rows.secret"]}
    ], "relationships": []})
    report("PASS offline synthetic ontology validator and SQL privilege boundaries.")


def infer(opener, model: str, key: str, prompt: str, max_tokens: int) -> tuple[dict, dict]:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content":
                      "Return a single valid JSON object only. Never write to any database."},
                     {"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
        "stream": False,
    }
    obj = request_json(opener, "/chat/completions", key, payload)
    choices = obj.get("choices", [])
    if not choices or not isinstance(choices[0], dict):
        raise ValueError("missing choices")
    message = choices[0].get("message", {}) or {}
    answer = message.get("content") or ""
    if not answer:
        report("INFERENCE_DIAGNOSTIC: no visible content; finish_reason=" + str(choices[0].get("finish_reason", "unknown"))[:30])
    return extract_object(answer), obj.get("usage", {})


def live() -> int:
    key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not key:
        report("SKIP: GitHub Actions NVIDIA_API_KEY secret missing; no inference.")
        return 0
    if not key.startswith("nvapi-") or len(key) < 25:
        report("STOP: invalid secret format; no inference.")
        return 2
    opener = client()
    try:
        catalog = request_json(opener, "/models", key)
    except HTTPError as err:
        report(f"STOP: NVIDIA model catalog HTTP {err.code}; no inference.")
        return 0
    except (ValueError, OSError, URLError) as err:
        report(f"STOP: model listing {type(err).__name__}; no inference.")
        return 0
    model = choose_model(catalog)
    if not model:
        report("SKIP: none of the three reviewed synthetic-test model IDs available; no inference.")
        return 0

    report("NVIDIA synthetic two-call pilot; approved model: " + model)
    report("Guardrails: 2 calls maximum, output budgets 256+160 tokens, synthetic-only, no retry.")
    ontology_prompt = (
        "Make a DRAFT ontology from this artificial schema only: "
        "approved_door_view(door_name TEXT, project_name TEXT, "
        "verification_state TEXT). Rows: (Door-101, Project A, human_verified), "
        "(Door-102, Project A, human_verified). "
        "Return JSON exactly with keys terms (list of objects name and "
        "mapped_columns) and relationships (list of source,target,type). "
        "Create terms Door mapped_columns [door_name] and Project "
        "mapped_columns [project_name], linked Door PART_OF Project. "
        "Do not claim human certification."
    )
    sql_prompt = (
        "Using ONLY the synthetic table approved_door_view"
        "(door_name,project_name,verification_state), answer the question: "
        "'How many human-verified doors belong to Project A?' "
        "Return JSON {\"sql\":\"...\"} with one SELECT COUNT(*) from "
        "approved_door_view filtering project_name='Project A' AND "
        "verification_state='human_verified'. Do not use any other tables."
    )
    used = 0
    started = time.monotonic()
    try:
        used += 1
        onto, u1 = infer(opener, model, key, ontology_prompt, MAX_OUTPUT[0])
        ontology_ok = ontology_valid(onto)
        report("Draft ontology generated: " + ("PASS" if ontology_ok else "SCHEMA_FAIL"))
        if not ontology_ok:
            report("STOP: ontology validation failed; second inference not sent.")
            return 1
        used += 1
        answer, u2 = infer(opener, model, key, sql_prompt, MAX_OUTPUT[1])
        result = safe_sql_count(answer.get("sql"))
        report("Natural language -> SQL -> isolated SQL execution: "
               + ("PASS (count=2)" if result == 2 else "WRONG_ANSWER"))
        usage = sum(x.get("total_tokens", 0) for x in (u1, u2) if isinstance(x, dict))
        report(f"Calls: {used}/{MAX_CALLS}; reported total tokens: {usage}; elapsed: {int(time.monotonic()-started)}s")
        report("No model output, key, or real Sion data was logged or stored.")
        return 0 if result == 2 else 1
    except HTTPError as err:
        # Never log the response body; 402 is a bounded credit-stop, not a charge.
        report(f"STOP: inference HTTP {err.code}, calls attempted {used}/{MAX_CALLS}; no retry.")
        return 0 if err.code in (401, 402, 403, 404, 429) else 1
    except (ValueError, OSError, URLError, sqlite3.DatabaseError, TypeError) as err:
        report(f"FAIL: {type(err).__name__}; calls attempted {used}/{MAX_CALLS}; no retry.")
        return 1


if __name__ == "__main__":
    self_test()
    sys.exit(live() if "--live" in sys.argv else 0)
