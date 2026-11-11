"""Egress guard must not depend on the resolver of the machine running the tests.

Since Ontology #99 (ported in the 2026-11-09 catch-up) netguard never consults DNS: only literal local IPs,
the built-in compose/host names and the operator allow-list ``AEC_LOCAL_HOSTNAMES`` count as local.
"""

from __future__ import annotations

import socket

import pytest

from aec_intelligence.operational import netguard


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("netguard must not resolve DNS")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.delenv("AEC_LOCAL_HOSTNAMES", raising=False)


@pytest.mark.parametrize("url", ["http://127.0.0.1:11434", "http://10.0.0.5:8080", "http://[::1]:11434",
                                 "http://localhost:11434", "http://host.docker.internal:11434",
                                 "http://embeddings:80", "http://ollama:11434"])
def test_local_literals_and_names(url):
    assert netguard.is_local_endpoint(url)


@pytest.mark.parametrize("url", ["http://198.18.0.1", "http://198.19.255.254", "http://[::ffff:198.18.0.7]",
                                 "ftp://127.0.0.1", "https://8.8.8.8"])
def test_fake_ip_public_and_bad_scheme_are_not_local(url):
    assert not netguard.is_local_endpoint(url)


def test_hostnames_are_remote_whatever_dns_would_answer():
    # Fake-IP DNS (Clash/sing-box) or a LAN resolver could answer 198.18.x / 192.168.x; it is never asked.
    assert not netguard.is_local_endpoint("https://api.example.com")
    assert not netguard.is_local_endpoint("http://llm.lan:11434")


def test_operator_allow_list_opts_a_lan_host_in(monkeypatch):
    monkeypatch.setenv("AEC_LOCAL_HOSTNAMES", "llm.lan, GPU-BOX.lan.")
    assert netguard.is_local_endpoint("http://llm.lan:11434")
    assert netguard.is_local_endpoint("http://gpu-box.lan/")
    assert not netguard.is_local_endpoint("http://other.lan/")
