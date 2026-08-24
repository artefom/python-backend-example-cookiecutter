"""
Tests for the outbound trace-propagation allowlist.
"""

import pytest

from {{cookiecutter.__project_slug}}.telemetry import (
    TRACE_PROPAGATION_ALLOWLIST_ENV,
    propagation_allowed,
)


def test_unset_allowlist_allows_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(TRACE_PROPAGATION_ALLOWLIST_ENV, raising=False)
    assert propagation_allowed("anything.example.com") is True
    assert propagation_allowed(None) is True


@pytest.mark.parametrize("raw", ["", "   ", ",", " , "])
def test_empty_allowlist_allows_everything(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv(TRACE_PROPAGATION_ALLOWLIST_ENV, raw)
    assert propagation_allowed("anything.example.com") is True


def test_star_allows_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TRACE_PROPAGATION_ALLOWLIST_ENV, "*")
    assert propagation_allowed("anything.example.com") is True
    assert propagation_allowed(None) is True


def test_exact_host_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TRACE_PROPAGATION_ALLOWLIST_ENV, "api.partner.com")
    assert propagation_allowed("api.partner.com") is True
    assert propagation_allowed("other.partner.com") is False
    assert propagation_allowed("partner.com") is False
    # An exact entry must not match a subdomain of itself either way round.
    assert propagation_allowed("evil-api.partner.com") is False


def test_matching_ignores_case_whitespace_and_trailing_dot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        TRACE_PROPAGATION_ALLOWLIST_ENV, "  API.Partner.COM. ,, second.host  "
    )
    assert propagation_allowed("api.partner.com") is True
    assert propagation_allowed("API.PARTNER.COM") is True
    assert propagation_allowed("api.partner.com.") is True
    assert propagation_allowed("second.host") is True


def test_leading_dot_matches_apex_and_subdomains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(TRACE_PROPAGATION_ALLOWLIST_ENV, ".example.com")
    assert propagation_allowed("example.com") is True
    assert propagation_allowed("api.example.com") is True
    assert propagation_allowed("deep.api.example.com") is True
    # Must not be a bare substring/suffix match.
    assert propagation_allowed("notexample.com") is False
    # ...and must not be fooled by an attacker-controlled parent domain.
    assert propagation_allowed("example.com.evil.tld") is False


def test_port_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    # Hosts are matched without their port, so a random-port test server or a
    # sidecar on a non-default port needs only its host allowlisted.
    monkeypatch.setenv(TRACE_PROPAGATION_ALLOWLIST_ENV, "127.0.0.1")
    assert propagation_allowed("127.0.0.1") is True
    assert propagation_allowed("localhost") is False


def test_multiple_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        TRACE_PROPAGATION_ALLOWLIST_ENV, ".internal.example.com,api.partner.com"
    )
    assert propagation_allowed("svc.internal.example.com") is True
    assert propagation_allowed("api.partner.com") is True
    assert propagation_allowed("httpbin.org") is False


def test_missing_host_denied_when_allowlist_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # e.g. a unix-socket connector: nothing to check against, so not trusted.
    monkeypatch.setenv(TRACE_PROPAGATION_ALLOWLIST_ENV, "api.partner.com")
    assert propagation_allowed(None) is False
    assert propagation_allowed("") is False
