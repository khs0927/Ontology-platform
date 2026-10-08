import http.client
import json
from pathlib import Path
import threading

import pytest

from aec_intelligence.mcp_http import MCPHTTPServer


@pytest.mark.parametrize("host", ["attacker.example", "localhost.attacker.example", "127.0.0.1", "localhost:bad"])
def test_mcp_rejects_untrusted_host_without_dispatch(tmp_path: Path, host: str):
    server = MCPHTTPServer(("127.0.0.1", 0), tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        status, _, error = _request(port, {"jsonrpc": "2.0", "id": 1, "method": "initialize"}, {"Host": host})
        assert status == 403 and error["error"]["message"] == "Invalid Host"
        assert not server.rpc_server.initialized
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_mcp_rejected_post_closes_connection_with_unread_body(tmp_path: Path):
    server = MCPHTTPServer(("127.0.0.1", 0), tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    try:
        connection.request("POST", "/mcp", '{}', {"Origin": "https://attacker.example"})
        response = connection.getresponse(); response.read()
        assert response.status == 403 and response.getheader("Connection") == "close"
        assert connection.sock is None
    finally:
        connection.close(); server.shutdown(); server.server_close(); thread.join(timeout=5)


def _request(port: int, payload: dict, headers: dict[str, str] | None = None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    request_headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **(headers or {})}
    connection.request("POST", "/mcp", json.dumps(payload), request_headers)
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response.status, response.getheader("Content-Type"), json.loads(data) if data else None


def test_mcp_streamable_http_json_mode_and_security(tmp_path: Path):
    server = MCPHTTPServer(("127.0.0.1", 0), tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, content_type, initialize = _request(port, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}}, {"Origin": f"http://127.0.0.1:{port}"})
        assert status == 200
        assert content_type == "application/json"
        assert initialize["result"]["protocolVersion"] == "2025-11-25"
        status, _, listed = _request(port, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, {"MCP-Protocol-Version": "2025-11-25"})
        assert status == 200
        assert any(tool["name"] == "aec.audit" for tool in listed["result"]["tools"])
        status, _, error = _request(port, {"jsonrpc": "2.0", "id": 3, "method": "ping"})
        assert status == 400
        assert error["error"]["code"] == -32602
        status, _, error = _request(port, {"jsonrpc": "2.0", "id": 4, "method": "ping"}, {"Origin": "https://untrusted.example"})
        assert status == 403
        assert error["error"]["message"] == "Invalid Origin"
        status, _, _ = _request(port, {"jsonrpc": "2.0", "method": "notifications/initialized"}, {"MCP-Protocol-Version": "2025-11-25"})
        assert status == 202
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_mcp_streamable_http_does_not_offer_legacy_get_sse(tmp_path: Path):
    server = MCPHTTPServer(("127.0.0.1", 0), tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    try:
        connection.request("GET", "/mcp", headers={"Accept": "text/event-stream"})
        response = connection.getresponse()
        response.read()
        assert response.status == 405
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_mcp_streamable_http_rejects_invalid_origin_on_get(tmp_path: Path):
    server = MCPHTTPServer(("127.0.0.1", 0), tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    try:
        connection.request("GET", "/mcp", headers={"Accept": "text/event-stream", "Origin": "https://untrusted.example"})
        response = connection.getresponse()
        body = json.loads(response.read())
        assert response.status == 403
        assert body["error"]["message"] == "Invalid Origin"
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
