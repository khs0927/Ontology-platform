"""Real NVIDIA LLM text-to-SQL vs 16 synthetic PostgreSQL goldens.

Model inputs consist only of the five columns in a project-scoped CI view and
fictional labels. The NVIDIA model generates SQL; actual PostgreSQL executes
it as a restricted read-only user. No production data, keys, generated SQL,
responses or query rows are printed or recorded.
"""

from __future__ import annotations

import json
import os
import re
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import psycopg

MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
SOURCE = "sion_nv_pilot.verified_project_objects"
PROJECT_A = "00000000-0000-0000-0000-0000000000a1"
PROJECT_B = "00000000-0000-0000-0000-0000000000b1"
CASES = (
    ("all", "How many authorized objects are in this data?", 2),
    ("concepts", "How many objects have object_type Concept?", 2),
    ("part-of", "How many entries have relationship_type PART_OF?", 2),
    ("distinct-objects", "How many distinct object_name values are visible?", 2),
    ("unique-projects", "How many distinct project_id values are visible?", 1),
    ("project-a", "How many objects belong to Project A?", 2),
    ("project-b-private", "How many objects belong to Project B?", 0),
    ("door-101", "How many objects are named Door-101?", 1),
    ("door-102", "How many objects are named Door-102?", 1),
    ("rejected-excluded", "How many objects are named Door-Rejected?", 0),
    ("unverified-excluded", "How many objects are named Door-No-Evidence?", 0),
    ("expired-excluded", "How many objects are named Door-Expired?", 0),
    ("future-excluded", "How many objects are named Door-Future?", 0),
    ("private-excluded", "How many objects are named Project-B-Private-Door?", 0),
    ("name-prefix", "How many objects have names beginning with Door-1?", 2),
    ("filtered-aggregate", "How many visible objects are specifically Door-101?", 1),
)
SCHEMA = (
    "PostgreSQL database sion_nvidia_ci. Exactly one authorized source "
    f"view: {SOURCE}(object_id UUID, object_name TEXT, object_type TEXT, "
    "project_id UUID, relationship_type TEXT). "
    "This security-barrier view already filters human-verified evidence, "
    "unexpired associations, and an authorized project. "
    f"Project A identifier is {PROJECT_A}; Project B identifier is {PROJECT_B}. "
    "All other database tables and schemas are forbidden. "
    "Representative visible sample rows are (Door-101, Concept, Project A, PART_OF) "
    "and (Door-102, Concept, Project A, PART_OF). "
    "The object_type for doors is Concept, NOT Door; never invent object_type "
    "filters when a question only names an object. "
    "Do not assume excluded records are visible. "
    "For an exact object name use case-sensitive equality; never use a "
    "partial LIKE pattern unless the user explicitly asks for a prefix. "
    "Preserve identifiers and filter literals verbatim from the question. "
    "Return JSON only: {\"sql\":\"SELECT count(*) ...\"}."
)


def report(message: str) -> None:
    print(message, flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as file:
            file.write(message.replace("|", "\\|") + "\n")


def generated_sql(key: str, question: str) -> str:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": (
                "You generate exactly one read-only PostgreSQL SELECT COUNT "
                "statement and return only a JSON object containing sql."
            )},
            {"role": "user", "content": SCHEMA + "\nQuestion: " + question},
        ],
        "chat_template_kwargs": {"enable_thinking": False},
        "temperature": 0,
        "max_tokens": 300,
        "stream": False,
    }
    req = Request(
        API_URL,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urlopen(req, timeout=45) as result:
        raw = result.read(300_001)
        if len(raw) > 300_000:
            raise ValueError("model response bound exceeded")
    response = json.loads(raw)
    text = response["choices"][0]["message"].get("content") or ""
    if not isinstance(text, str) or len(text) > 4000:
        raise ValueError("invalid model content")
    left = text.find("{")
    right = text.rfind("}")
    if left < 0 or right <= left:
        raise ValueError("model did not return JSON")
    parsed = json.loads(text[left : right + 1])
    statement = parsed.get("sql")
    if not isinstance(statement, str) or len(statement) > 1500:
        raise ValueError("model SQL invalid or too long")
    return statement


def validate_sql(sql: str) -> str:
    statement = sql.strip().rstrip(";").strip()
    if not re.match(r"(?is)^select\s", statement):
        raise ValueError("not SELECT")
    if ";" in statement or "--" in statement or "/*" in statement:
        raise ValueError("multi-statement or comment")
    if re.search(
        r"\b(insert|update|delete|drop|create|alter|grant|revoke|copy|call|do|set)\b",
        statement,
        flags=re.I,
    ):
        raise ValueError("forbidden SQL command")
    if re.search(
        r"\b(public|pg_catalog|information_schema|pg_|dblink|load_file)\b",
        statement,
        flags=re.I,
    ):
        raise ValueError("non-allowlisted source")
    normalized = statement.lower().replace('"', "")
    if SOURCE not in normalized:
        raise ValueError("missing allowlisted source")
    if not re.search(r"\bcount\s*\(", statement, flags=re.I):
        raise ValueError("expected COUNT query")
    return statement


def verify_connection(conn: psycopg.Connection) -> None:
    assert conn.execute("SELECT current_database()").fetchone()[0] == "sion_nvidia_ci"
    assert conn.execute("SELECT current_user").fetchone()[0] == "nvidia_pilot_reader"
    assert conn.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"
    assert conn.execute("SELECT count(*) FROM " + SOURCE).fetchone()[0] == 2
    try:
        conn.execute("SELECT count(*) FROM public.entities")
    except psycopg.Error as error:
        assert error.sqlstate == "42501", "unexpected access error"
    else:
        raise AssertionError("production canonical table unexpectedly readable")
    report("PASS real PostgreSQL restricted project view; raw Sion tables denied")


def run() -> None:
    if os.environ.get("GITHUB_REPOSITORY") != "khs0927/Ontology-platform":
        raise RuntimeError("CI repository gate failed")
    key = os.environ.get("NVIDIA_API_KEY", "")
    if not key.startswith("nvapi-"):
        raise RuntimeError("NVIDIA developer API key missing")
    dsn = os.environ["SION_NVIDIA_PILOT_RO_DSN"]
    if "sion_nvidia_ci" not in dsn or "nvidia_pilot_reader" not in dsn:
        raise RuntimeError("restricted synthetic database required")
    good = 0
    started = time.monotonic()
    with psycopg.connect(dsn, autocommit=True) as conn:
        verify_connection(conn)
        for label, question, expected in CASES:
            try:
                sql = validate_sql(generated_sql(key, question))
                rows = conn.execute(sql).fetchall()
                if len(rows) != 1 or len(rows[0]) != 1:
                    raise ValueError("non-scalar model SQL result")
                actual = rows[0][0]
                ok = isinstance(actual, int) and actual == expected
                report(f"Case {label}: " + ("PASS" if ok else f"WRONG_ANSWER observed={actual}, expected={expected}"))
                good += int(ok)
            except HTTPError as error:
                report(f"Case {label}: MODEL_HTTP_{error.code}; stopping.")
                break
            except (psycopg.Error, ValueError, KeyError, TypeError, IndexError, OSError):
                report(f"Case {label}: INVALID_OR_DENIED")
    report(f"Real model SQL correctness: {good}/{len(CASES)} goldens")
    report(f"Elapsed: {int(time.monotonic() - started)}s; model: {MODEL}")
    report("No model SQL, request answers, API keys or production data persisted")
    if good != len(CASES):
        raise RuntimeError("some model SQL goldens were incorrect or unavailable")


if __name__ == "__main__":
    try:
        run()
    except (RuntimeError, AssertionError, psycopg.Error) as error:
        report(f"FAIL synthetic model SQL benchmark: {type(error).__name__}")
        raise SystemExit(1) from None
