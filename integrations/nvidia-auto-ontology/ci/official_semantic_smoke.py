"""Official NVIDIA Auto Ontology semantic ingestion/compilation + NL-to-SQL E2E.

Runs only on a temporary GitHub Actions runner with fake Sion facts, an
isolated PostgreSQL DB and a table allowlisted DB user. Unlike direct LLM
prompting, this invokes actual upstream NVIDIA ingestion and chat services.
No model output, credentials or SQL text are logged or persisted as artifacts.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

UPSTREAM = "http://localhost:3000"
COMPILE_DEADLINE_S = 960
QUESTION_TIMEOUT_S = 500
QUESTIONS = (
    ("approved-objects", "How many rows are there in the verified_project_objects view?", 2),
    ("distinct-projects", "How many distinct project_id values are in the verified_project_objects view?", 1),
)


def report(message: str) -> None:
    print(message, flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as sink:
            sink.write(message.replace("|", "\\|") + "\n")


def ci_config() -> dict[str, str]:
    if os.environ.get("GITHUB_REPOSITORY") != "khs0927/Ontology-platform":
        raise RuntimeError("unexpected GitHub repository")
    path = Path(os.environ["GITHUB_WORKSPACE"]) / "nvidia" / ".env"
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        name, _, value = line.partition("=")
        if name in {"AUTO_ONTOLOGY_ADMIN_EMAIL", "AUTO_ONTOLOGY_ADMIN_PASSWORD"}:
            values[name] = value
    if len(values) != 2:
        raise RuntimeError("CI bootstrap admin configuration unavailable")
    return values


def wait_web(client: httpx.Client) -> None:
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        try:
            response = client.get("/", timeout=6)
            if response.status_code in (200, 301, 302, 303, 307, 308):
                return
        except httpx.HTTPError:
            pass
        time.sleep(4)
    raise RuntimeError("NVIDIA frontend not ready")


def authenticated_token(client: httpx.Client, values: dict[str, str]) -> str:
    login = client.post(
        "/api/auth/sign-in/email",
        json={
            "email": values["AUTO_ONTOLOGY_ADMIN_EMAIL"],
            "password": values["AUTO_ONTOLOGY_ADMIN_PASSWORD"],
        },
        headers={"Origin": UPSTREAM},
        timeout=30,
    )
    if login.status_code != 200:
        raise RuntimeError(f"NVIDIA login HTTP {login.status_code}")
    issued = client.post(
        "/api/api-tokens",
        json={"name": "sion-real-semantic-ci", "expires_in_days": 1},
        headers={"Origin": UPSTREAM},
        timeout=30,
    )
    if issued.status_code != 201:
        raise RuntimeError(f"NVIDIA token issue HTTP {issued.status_code}")
    token = issued.json().get("token")
    if not isinstance(token, str) or not token.startswith("auto_ontology_"):
        raise RuntimeError("NVIDIA returned an invalid ephemeral API token")
    return token


def enable_compilation(client: httpx.Client) -> None:
    result = client.put(
        "/api/configurations/semantic-compilation",
        headers={"Origin": UPSTREAM},
        json={"enabled": True},
        timeout=30,
    )
    if result.status_code != 200 or result.json().get("enabled") is not True:
        raise RuntimeError(f"semantic enable HTTP {result.status_code}")
    report("PASS official NVIDIA semantic compilation enabled using admin API")


def await_compilation(client: httpx.Client, auth: dict[str, str]) -> int:
    deadline = time.monotonic() + COMPILE_DEADLINE_S
    last_state = None
    while time.monotonic() < deadline:
        response = client.get("/api/semantic-compilation/status", headers=auth, timeout=20)
        if response.status_code != 200:
            raise RuntimeError(f"semantic status HTTP {response.status_code}")
        state = response.json()
        current = (
            bool(state.get("calculated")),
            bool(state.get("running")),
            bool(state.get("last_success_at")),
            bool(state.get("last_failure_at")),
        )
        if current != last_state:
            report("Semantic status: calculated=%s running=%s successful=%s failed=%s" % current)
            last_state = current
        if state.get("last_failure_at") and not state.get("last_success_at"):
            raise RuntimeError("official NVIDIA semantic compiler reported failure")
        if state.get("last_success_at") and state.get("calculated") and not state.get("running"):
            terms = client.get("/api/terms?skip=0&limit=100", headers=auth, timeout=20)
            if terms.status_code != 200:
                raise RuntimeError(f"terms HTTP {terms.status_code}")
            body = terms.json()
            raw = body.get("terms", body.get("data", []))
            total = body.get("total", len(raw) if isinstance(raw, list) else 0)
            if not isinstance(total, int) or total < 1:
                raise RuntimeError("compiler finished but no semantic terms generated")
            report(f"PASS actual NVIDIA ingestion + semantic compilation: {total} terms")
            return total
        time.sleep(10)
    raise RuntimeError("official semantic compilation deadline reached without success")


def numeric_sql_result(raw: object) -> int:
    """Parse only the executed DB rows from NVIDIA SSE, not answer prose."""
    for _ in range(4):
        if isinstance(raw, str):
            raw = json.loads(raw)
        elif isinstance(raw, list) and len(raw) == 1:
            raw = raw[0]
        else:
            break
    if isinstance(raw, dict) and len(raw) == 1:
        number = next(iter(raw.values()))
        if isinstance(number, int) and not isinstance(number, bool):
            return number
        if isinstance(number, str) and number.isdigit():
            return int(number)
    raise ValueError("SQL result is not a single integer aggregate")


def ask_official(
    client: httpx.Client, auth: dict[str, str], question: str, expected: int
) -> bool:
    with client.stream(
        "POST",
        "/api/chat/completions",
        headers=auth,
        json={"question": question, "target_db": "sion_nvidia_ci"},
        timeout=httpx.Timeout(QUESTION_TIMEOUT_S, connect=20),
    ) as response:
        if response.status_code != 200:
            raise RuntimeError(f"official agent HTTP {response.status_code}")
        answer = None
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            data = line.removeprefix("data:").strip()
            if data == "[DONE]":
                break
            event = json.loads(data)
            if event.get("type") == "error":
                raise RuntimeError("official NVIDIA NL-to-SQL agent returned an error")
            if event.get("type") == "result":
                answer = event.get("answer")

    if not isinstance(answer, dict):
        raise RuntimeError("official NVIDIA agent did not return a result event")
    sql = answer.get("sql_code")
    if not isinstance(sql, str) or "verified_project_objects" not in sql.casefold():
        raise RuntimeError("model SQL did not reference approved synthetic view")
    if not sql.lstrip().lower().startswith("select"):
        raise RuntimeError("model SQL was not a SELECT query")
    observed = numeric_sql_result(answer.get("sql_response_from_db"))
    return observed == expected


def main() -> None:
    report("Official NVIDIA pipeline: isolated Sion PostgreSQL view, no production data")
    values = ci_config()
    with httpx.Client(base_url=UPSTREAM, follow_redirects=False, trust_env=False) as client:
        wait_web(client)
        token = authenticated_token(client, values)
        auth = {"x-api-key": token}
        source = client.get("/api/connections/source", headers=auth, timeout=20)
        if source.status_code != 200 or source.json() is not True:
            raise RuntimeError("NVIDIA is not using the approved env-only source")
        report("PASS authenticated NVIDIA frontend and configured source")
        enable_compilation(client)
        term_count = await_compilation(client, auth)
        report(f"Semantic term count: {term_count} (unverified draft, not Sion canonical)")
        good = 0
        for label, question, expected in QUESTIONS:
            ok = ask_official(client, auth, question, expected)
            report(f"Official agent SQL golden {label}: " + ("PASS" if ok else "FAIL"))
            good += int(ok)
        if good != len(QUESTIONS):
            raise RuntimeError("official NL-to-SQL answers differed from golden fixtures")
        report(f"PASS {good}/{len(QUESTIONS)} official NVIDIA NL-to-SQL goldens")
        report("No model SQL, response text, user data, or API secrets logged.")


if __name__ == "__main__":
    try:
        main()
    except (httpx.HTTPError, RuntimeError, ValueError, OSError, json.JSONDecodeError) as error:
        # Print only diagnostics authored by this script. Never print provider bodies.
        if isinstance(error, RuntimeError):
            report("FAIL official NVIDIA E2E: " + str(error))
        else:
            report(f"FAIL official NVIDIA E2E: {type(error).__name__}")
        raise SystemExit(1) from None
