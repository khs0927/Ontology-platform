"""NVIDIA free developer API read-only token probe. No inference or raw key logging."""

from __future__ import annotations

import json
import os
import ssl
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def main() -> int:
    key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not key:
        print("SKIPPED: NVIDIA_API_KEY has not been configured as an Actions secret.")
        return 0
    if not key.startswith("nvapi-") or len(key) < 25:
        print("ERROR: NVIDIA secret has invalid format.")
        return 2
    request = Request(
        "https://integrate.api.nvidia.com/v1/models",
        headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
    )
    client = build_opener(
        NoRedirect(), HTTPSHandler(context=ssl.create_default_context())
    )
    try:
        with client.open(request, timeout=12) as response:
            body = response.read(1_500_001)
            if len(body) > 1_500_000:
                print("ERROR: NVIDIA response exceeds safe limit.")
                return 1
        models = json.loads(body).get("data", [])
        if not isinstance(models, list):
            print("ERROR: NVIDIA response schema mismatch.")
            return 1
        ids = {x.get("id") for x in models if isinstance(x, dict)}
        print("NVIDIA models API authentication: SUCCESS (HTTP 200)")
        print("Visible model count:", len(ids))
        for name in (
            "nvidia/nemotron-3.5-lightning-30b-a3b",
            "nvidia/nemotron-3-embed-1b",
            "nvidia/llama-nemotron-rerank-vl-1b-v2",
        ):
            print(name, "listed" if name in ids else "not listed")
        print("No inference performed; chat entitlements and free credits unverified.")
        return 0
    except HTTPError as exc:
        print("NVIDIA HTTP status:", exc.code)
        return 1
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        print("NVIDIA error type:", type(exc).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
