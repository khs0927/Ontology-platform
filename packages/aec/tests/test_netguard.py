"""Egress guard must not depend on the resolver of the machine running the tests."""

from __future__ import annotations

import socket

import pytest

from aec_intelligence.operational import netguard


def _resolve_to(monkeypatch, *ips):
    monkeypatch.setattr(netguard, "_getaddrinfo",
                        lambda host: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips])


@pytest.mark.parametrize("url", ["http://127.0.0.1:11434", "http://10.0.0.5:8080", "http://[::1]:11434",
                                 "http://localhost:11434", "http://host.docker.internal:11434"])
def test_local_literals_and_names(url):
    assert netguard.is_local_endpoint(url)


@pytest.mark.parametrize("url", ["http://198.18.0.1", "http://198.19.255.254", "http://[::ffff:198.18.0.7]",
                                 "ftp://127.0.0.1", "https://8.8.8.8"])
def test_fake_ip_public_and_bad_scheme_are_not_local(url):
    assert not netguard.is_local_endpoint(url)


def test_fake_ip_dns_answer_is_not_local(monkeypatch):
    # Clash/sing-box style fake-IP DNS maps every public name into 198.18.0.0/15.
    _resolve_to(monkeypatch, "198.18.0.1")
    assert not netguard.is_local_endpoint("https://api.example.com")


def test_mixed_dns_answer_is_not_local(monkeypatch):
    _resolve_to(monkeypatch, "192.168.1.10", "93.184.216.34")
    assert not netguard.is_local_endpoint("http://llm.lan")


def test_private_dns_answer_is_local(monkeypatch):
    _resolve_to(monkeypatch, "192.168.1.10")
    assert netguard.is_local_endpoint("http://llm.lan:11434")
