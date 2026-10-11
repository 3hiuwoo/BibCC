"""Offline tests for fetch_url transport retries and OpenReview diagnostics."""

import email.message
import json
import socket
import ssl
import urllib.error
from pathlib import Path

import pytest

from bibcc import sources
from bibcc.venues import VenueLibrary

SOURCES = Path(__file__).parent / "fixtures" / "sources"
SDLORA = "SD-LoRA: Scalable Decoupled Low-Rank Adaptation for Class Incremental Learning"


def _fixture(name: str) -> str:
    return (SOURCES / name).read_text(encoding="utf-8")


class FakeWeb:
    """Serve canned responses by URL substring; everything else is a 404."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, headers=None, timeout=15, retries=0):
        self.calls.append(url)
        for needle, response in self.routes.items():
            if needle in url:
                return response
        return None, "HTTP 404: Not Found"


class _Response:
    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code, reason="Error"):
    return urllib.error.HTTPError("https://example.org", code, reason, email.message.Message(), None)


@pytest.fixture
def net(monkeypatch):
    """Replace urlopen with a queue of outcomes, and record the sleeps."""
    state = {"outcomes": [], "calls": 0, "sleeps": []}

    def urlopen(req, timeout=None):
        state["calls"] += 1
        outcome = state["outcomes"].pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return _Response(outcome)

    monkeypatch.setattr(sources.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(sources.time, "sleep", lambda s: state["sleeps"].append(s))
    return state


# ------------------------------------------------------------ fetch_url


@pytest.mark.parametrize(
    "failure,message",
    [
        (urllib.error.URLError(ssl.SSLEOFError(8, "EOF occurred in violation of protocol")), "Network error: "),
        (urllib.error.URLError(socket.gaierror(8, "nodename nor servname provided")), "Network error: "),
        (TimeoutError(), "Request timed out"),
        (socket.timeout("timed out"), "Request timed out"),
        (ConnectionResetError(54, "Connection reset by peer"), "ConnectionResetError: "),
        (ssl.SSLError(1, "bad record mac"), "SSLError: "),
    ],
)
def test_transport_failure_is_retried_once_without_a_retry_budget(net, failure, message):
    net["outcomes"] = [failure, b"ok"]
    assert sources.fetch_url("https://example.org") == ("ok", None)
    assert net["calls"] == 2 and net["sleeps"] == [1.0]

    net["outcomes"], net["calls"], net["sleeps"] = [failure, failure, b"ok"], 0, []
    content, error = sources.fetch_url("https://example.org")
    assert content is None and error.startswith(message)
    assert net["calls"] == 2


def test_transport_retries_use_the_budget_with_capped_backoff(net):
    failure = urllib.error.URLError(ssl.SSLEOFError(8, "EOF occurred in violation of protocol"))
    net["outcomes"] = [failure] * 6
    content, error = sources.fetch_url("https://example.org", retries=5)
    assert content is None
    assert error == f"Network error: {failure.reason}"
    assert net["calls"] == 6
    assert net["sleeps"] == [1.0, 2.0, 4.0, 8.0, 8.0]


def test_certificate_failure_is_not_retried(net):
    net["outcomes"] = [urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed"))]
    content, error = sources.fetch_url("https://example.org", retries=3)
    assert content is None and error.startswith("Network error: ")
    assert net["calls"] == 1 and net["sleeps"] == []


@pytest.mark.parametrize("code", [400, 401, 403, 404, 500])
def test_other_http_errors_are_never_retried(net, code):
    net["outcomes"] = [_http_error(code, "Nope")]
    assert sources.fetch_url("https://example.org", retries=3) == (None, f"HTTP {code}: Nope")
    assert net["calls"] == 1 and net["sleeps"] == []


def test_rate_limits_still_need_a_retry_budget(net):
    net["outcomes"] = [_http_error(429, "Too Many Requests")]
    assert sources.fetch_url("https://example.org") == (None, "HTTP 429: Too Many Requests")
    assert net["calls"] == 1

    net["outcomes"], net["calls"] = [_http_error(503, "Service Unavailable"), b"ok"], 0
    assert sources.fetch_url("https://example.org", retries=1) == ("ok", None)
    assert net["calls"] == 2


def test_retries_share_one_budget(net):
    net["outcomes"] = [_http_error(503, "Service Unavailable"), TimeoutError(), b"ok"]
    assert sources.fetch_url("https://example.org", retries=1) == (None, "Request timed out")
    assert net["calls"] == 2


# ------------------------------------------------------------ OpenReview


@pytest.fixture
def web(monkeypatch):
    fake = FakeWeb({})
    monkeypatch.setattr(sources, "fetch_url", fake)
    return fake


def test_openreview_search_keeps_accepted_record_without_bibtex(web):
    notes = json.loads(_fixture("openreview_sdlora.json"))
    for note in notes["notes"]:
        note["content"].pop("_bibtex")
    web.routes["api2.openreview.net"] = (json.dumps(notes), None)
    record, error = sources.openreview_search(SDLORA, VenueLibrary())
    assert error is None
    assert record.extra["openreview_url"] == "https://openreview.net/forum?id=5U1rlpX68A"
    assert "bibtex" not in record.extra


def test_openreview_search_reports_unexpected_response(web):
    web.routes["api2.openreview.net"] = ("[]", None)
    assert sources.openreview_search(SDLORA, VenueLibrary()) == (None, "unexpected response from OpenReview")


def test_find_published_by_title_reports_openreview_error_with_crossref_error(web):
    web.routes["api2.openreview.net"] = (None, "HTTP 403: Forbidden")
    web.routes["api.crossref.org"] = (None, "HTTP 503: Service Unavailable")
    assert sources.find_published_by_title(SDLORA, VenueLibrary()) == (
        None, "OpenReview: HTTP 403: Forbidden; CrossRef: HTTP 503: Service Unavailable")


def test_find_published_by_title_reports_openreview_error_when_crossref_has_no_match(web):
    web.routes["api2.openreview.net"] = (None, "HTTP 429: Too Many Requests")
    web.routes["api.crossref.org"] = (json.dumps({"message": {"items": []}}), None)
    assert sources.find_published_by_title(SDLORA, VenueLibrary()) == (
        None, "OpenReview: HTTP 429: Too Many Requests")


def test_find_published_by_title_keeps_plain_crossref_error(web):
    web.routes["api2.openreview.net"] = (json.dumps({"notes": []}), None)
    web.routes["api.crossref.org"] = (None, "HTTP 503: Service Unavailable")
    assert sources.find_published_by_title(SDLORA, VenueLibrary()) == (None, "HTTP 503: Service Unavailable")
    web.routes["api.crossref.org"] = (json.dumps({"message": {"items": []}}), None)
    assert sources.find_published_by_title(SDLORA, VenueLibrary()) == (None, None)
