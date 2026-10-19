from types import SimpleNamespace

import pytest

from backend.ai_service import RouteSageAI


DIAGNOSIS = {
    "source": "R1",
    "destination": "R2",
    "reachable": False,
    "evidence": [{"source_interface": "R1:eth0", "destination_interface": "R2:eth0", "link_state": "down", "source_state": "up", "destination_state": "up"}],
}


class FakeClient:
    def __init__(self, result=None, error=None):
        self.models = self
        self.result = result
        self.error = error

    def generate_content(self, **_kwargs):
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.result)


def explain(service):
    return service.explain_diagnosis("What happened?", DIAGNOSIS, {}, [])


def test_missing_key_uses_deterministic_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result = explain(RouteSageAI())

    assert result["mode"] == "fallback"
    assert "not configured" in result["limitations"][0].lower()
    assert "R1 to R2 is not reachable" in result["evidence"][0]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError("slow provider"), "timeout"),
        (RuntimeError("429 too many requests"), "rate limited"),
        (ConnectionError("service unavailable"), "unavailable"),
    ],
)
def test_provider_failures_use_deterministic_fallback(error, expected):
    service = RouteSageAI.__new__(RouteSageAI)
    service.client = FakeClient(error=error)

    result = explain(service)

    assert result["mode"] == "fallback"
    assert expected in result["limitations"][0].lower()
    assert all("Gemini" not in item for item in result["evidence"])


@pytest.mark.parametrize("invalid", ["not json", '{"summary": "missing fields"}'])
def test_malformed_provider_response_uses_deterministic_fallback(invalid):
    service = RouteSageAI.__new__(RouteSageAI)
    service.client = FakeClient(result=invalid)

    result = explain(service)

    assert result["mode"] == "fallback"
    assert "invalid response" in result["limitations"][0].lower()


def test_valid_structured_provider_response_is_preserved():
    service = RouteSageAI.__new__(RouteSageAI)
    service.client = FakeClient(result='{"summary":"Verified summary","likely_cause":"Hypothesis","evidence":["Graph fact"],"recommendations":["Check link"],"limitations":["Topology only"]}')

    result = explain(service)

    assert result["mode"] == "gemini"
    assert result["summary"] == "Verified summary"
