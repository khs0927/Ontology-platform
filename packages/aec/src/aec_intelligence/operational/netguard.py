"""Egress guard for model endpoints. Drawing text is private: the LLM and embedding clients only talk to
loopback/private/link-local hosts unless an explicit ``*_ALLOW_REMOTE=1`` opt-in is set, and they never
route local calls through an HTTP(S) proxy taken from the environment or the Windows registry."""

from __future__ import annotations

import ipaddress
import os
import socket
import urllib.request
from urllib.parse import urlparse

LOCAL_HOSTNAMES = {"localhost", "host.docker.internal", "ollama", "gateway.docker.internal", "embeddings"}
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
# RFC 2544 benchmarking range. Python flags it ``is_private``, but fake-IP DNS proxies (Clash, sing-box,
# Surge, sandbox egress tunnels) answer *every* public name with an address from it, so treating it as local
# would let a remote endpoint pass the egress guard.
_FAKE_IP_NET = ipaddress.ip_network("198.18.0.0/15")


def _getaddrinfo(host: str):
    """Resolver seam (tests replace it so results never depend on the host's DNS)."""
    return socket.getaddrinfo(host, None)


def _is_local_addr(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if isinstance(addr, ipaddress.IPv4Address) and addr in _FAKE_IP_NET:
        return False
    return addr.is_loopback or addr.is_private or addr.is_link_local


def is_local_endpoint(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    if host in LOCAL_HOSTNAMES:
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        try:
            infos = _getaddrinfo(host)
        except (OSError, UnicodeError):
            return False
        addrs = {ipaddress.ip_address(i[4][0].split("%")[0]) for i in infos}
        # Every address the name resolves to must be local (no mixed public/private answers).
        return bool(addrs) and all(_is_local_addr(a) for a in addrs)
    return _is_local_addr(addr)


def remote_allowed(env_name: str) -> bool:
    return os.getenv(env_name, "").strip().lower() in {"1", "true", "yes"}


def opener_for(url: str):
    """Direct (proxy-less) opener for local endpoints; the default opener for opted-in remote ones."""
    return _DIRECT if is_local_endpoint(url) else urllib.request.build_opener()
