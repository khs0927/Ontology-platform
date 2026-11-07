"""End-to-end HTTP smoke: REAL NVIDIA frontend/backend and REAL Sion bridge.

Runs only in the private networking context of an ephemeral public-repo Actions
runner, with synthetic Sion data, ephemeral credentials and unreachable
model endpoints. Tests authentication, token creation and genuine API routing,
not semantic-LLM inference or production readiness.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from sion_api.auth import AuthPolicy
from sion_api.main import create_app

SION_TOKEN = "sion-gh-ci-temporary-token-2026-1107"
UPSTREAM = "http://127.0.0.1:3000"


def config() -> dict[str, str]:
    p = Path(os.environ["GITHUB_WORKSPACE"]) / "nvidia" / ".env"
    values: dict[str, str] = {}
    for line in p.read_text().splitlines():
        if line and not line.startswith("#"):
            name, _, value = line.partition("=")
            values[name] = value
    return values


def wait_ready(client: httpx.Client, path: str, timeout: int = 120) -> httpx.Response:
    deadline = time.monotonic() + timeout
    last = "not started"
    while time.monotonic() < deadline:
        try:
            response = client.get(path, timeout=5)
            last = f"HTTP {response.status_code}"
            if response.status_code == 200:
                return response
        except httpx.HTTPError as exc:
            last = type(exc).__name__
        time.sleep(3)
    raise AssertionError(f"NVIDIA {path} did not become ready: {last}")


def main() -> None:
    data = config()
    with httpx.Client(base_url=UPSTREAM, follow_redirects=False, trust_env=False) as upstream:
        wait_ready(upstream, "/", 150)
        signin = upstream.post(
            "/api/auth/sign-in/email",
            json={
                "email": data["AUTO_ONTOLOGY_ADMIN_EMAIL"],
                "password": data["AUTO_ONTOLOGY_ADMIN_PASSWORD"],
            },
            headers={"Origin": UPSTREAM},
            timeout=20,
        )
        assert signin.status_code == 200, f"admin login failed: HTTP {signin.status_code}"
        print("PASS NVIDIA frontend + bootstrap-admin session")

        created = upstream.post(
            "/api/api-tokens",
            json={"name": "sion-ci-ephemeral", "expires_in_days": 1},
            headers={"Origin": UPSTREAM},
            timeout=20,
        )
        assert created.status_code == 201, f"token issue failed: HTTP {created.status_code}"
        upstream_token = created.json()["token"]
        assert upstream_token.startswith("auto_ontology_")
        print("PASS NVIDIA one-day API token issued (redacted)")

        authenticated = upstream.get(
            "/api/semantic-compilation/status",
            headers={"x-api-key": upstream_token},
            timeout=20,
        )
        assert authenticated.status_code == 200, (
            f"upstream catalog status HTTP {authenticated.status_code}"
        )
        assert type(authenticated.json().get("calculated")) is bool
        print("PASS NVIDIA authenticated semantic-status API")

        os.environ["SION_NVIDIA_AUTO_ONTOLOGY_URL"] = UPSTREAM
        os.environ["SION_NVIDIA_AUTO_ONTOLOGY_API_TOKEN"] = upstream_token
        os.environ["SION_NVIDIA_AUTO_ONTOLOGY_ENABLE_ASK"] = "false"

        policy = AuthPolicy(
            mode="bearer",
            token_scopes=((SION_TOKEN, frozenset({"read:knowledge"})),),
        )
        app = create_app(database_url="sqlite://", auto_create_schema=True, auth_policy=policy)
        with TestClient(
            app, base_url="http://localhost", client=("203.0.113.10", 10001)
        ) as sion:
            auth = {"Authorization": f"Bearer {SION_TOKEN}"}
            status = sion.get("/api/v1/nvidia/status", headers=auth)
            assert status.status_code == 200
            assert status.json()["configured"] is True
            assert status.json()["ask_enabled"] is False

            ready = sion.get("/api/v1/nvidia/readiness", headers=auth)
            assert ready.status_code == 200, f"Sion readiness failed: HTTP {ready.status_code}"
            assert ready.json()["can_execute_sql"] is None

            terms = sion.get("/api/v1/nvidia/terms?query=door&limit=5", headers=auth)
            assert terms.status_code == 200, f"Sion upstream terms HTTP {terms.status_code}"
            assert terms.json()["read_only"] is True
            assert terms.json()["canonical"] is False
            assert isinstance(terms.json()["candidates"], list)

            forbidden = sion.post(
                "/api/v1/nvidia/ask",
                headers=auth,
                json={"question": "How many doors?"},
            )
            assert forbidden.status_code == 503, (
                "Unapproved LLM question was incorrectly enabled"
            )
            assert sion.get("/api/v1/entities", headers=auth).json() == []
            assert sion.get("/api/v1/nvidia/readiness").status_code == 401
        print(
            "PASS Sion -> REAL NVIDIA frontend: authenticated readiness, "
            "terms, fail-closed SQL and canonical isolation"
        )
        print("NOTE Model inference, semantic compilation and SQL accuracy NOT tested.")

if __name__ == "__main__":
    main()
