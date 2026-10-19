from uuid import uuid4

from fastapi.testclient import TestClient

from backend import api
from backend.failure_impact import analyze_link_impact
from backend.graph_agent import investigate
from backend.graph_repository import GraphRepository
from backend.incident_memory import IncidentMemory
from backend.network_model import Interface, Link, Router


def build_repo():
    repo = GraphRepository(graph_name=f"test_agent_{uuid4().hex}")
    for name in ("A", "B", "C", "D"):
        repo.add_router(Router(name, f"10.0.0.{ord(name) - 64}"))
        repo.add_interface(name, Interface("eth0", f"10.0.1.{ord(name) - 64}", "up"))
    repo.add_link(Link("A:eth0", "B:eth0", "down"))
    repo.add_link(Link("B:eth0", "D:eth0", "up"))
    repo.add_link(Link("A:eth0", "C:eth0", "up"))
    repo.add_link(Link("C:eth0", "D:eth0", "up"))
    return repo


def test_agent_uses_failed_edge_and_persists_graph_memory():
    repo = build_repo()
    try:
        result = investigate(repo, IncidentMemory(repo), "A", "D")

        assert result["decision"] == "preserve_connectivity_and_restore_failed_link"
        assert result["graph_evidence"]["failed_edges"][0]["link_state"] == "down"
        assert result["graph_evidence"]["impact"]["selected_link"]["state"] == "down"
        assert result["graph_evidence"]["impact"]["summary"]["affected_pairs"] == 0
        assert result["memory_recorded"] is True
        assert len(result["graph_evidence"]["history"]) == 1
        assert result["proposed_action"]["executed"] is False
        assert result["proposed_action"]["requires_operator_confirmation"] is True
        assert result["evidence_trace"]
    finally:
        repo.graph.delete()


def test_agent_read_only_mode_does_not_write_investigation_memory():
    repo = build_repo()
    try:
        before = repo.graph.query(
            "MATCH (n) RETURN labels(n), count(n)"
        ).result_set
        result = investigate(
            repo,
            IncidentMemory(repo),
            "A",
            "D",
            remember=False,
        )
        after = repo.graph.query(
            "MATCH (n) RETURN labels(n), count(n)"
        ).result_set

        assert result["memory_recorded"] is False
        assert result["graph_evidence"]["history"] == []
        assert before == after
    finally:
        repo.graph.delete()


def test_agent_api_returns_graph_decision_and_persists_memory(monkeypatch):
    repo = build_repo()
    monkeypatch.setattr(api, "repo", repo)
    monkeypatch.setattr(api, "memory", IncidentMemory(repo))
    try:
        response = TestClient(api.app).post(
            "/api/agent/investigate",
            json={"source": "A", "destination": "D", "remember": True},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["decision"] == "preserve_connectivity_and_restore_failed_link"
        assert body["memory_recorded"] is True
        assert body["graph_evidence"]["history"]
    finally:
        repo.graph.delete()


def test_later_investigation_retrieves_prior_graph_memory():
    repo = build_repo()
    try:
        memory = IncidentMemory(repo)
        first = investigate(repo, memory, "A", "D")
        second = investigate(repo, memory, "A", "D")

        history = second["graph_evidence"]["history"]
        ids = [item["investigation_id"] for item in history]
        assert len(history) == 2
        assert second["investigation_id"] in ids
        assert first["investigation_id"] in ids
        assert first["investigation_id"] != second["investigation_id"]
    finally:
        repo.graph.delete()


def test_agent_api_read_only_mode_preserves_topology_and_incidents(monkeypatch):
    repo = build_repo()
    monkeypatch.setattr(api, "repo", repo)
    monkeypatch.setattr(api, "memory", IncidentMemory(repo))
    try:
        before_topology = TestClient(api.app).get("/api/topology").json()
        before_incidents = TestClient(api.app).get("/api/incidents").json()
        response = TestClient(api.app).post(
            "/api/agent/investigate",
            json={"source": "A", "destination": "D", "remember": False},
        )
        after_topology = TestClient(api.app).get("/api/topology").json()
        after_incidents = TestClient(api.app).get("/api/incidents").json()

        assert response.status_code == 200
        assert response.json()["memory_recorded"] is False
        assert response.json()["graph_evidence"]["history"] == []
        assert before_topology == after_topology
        assert before_incidents == after_incidents
    finally:
        repo.graph.delete()
