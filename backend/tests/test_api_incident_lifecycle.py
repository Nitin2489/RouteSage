"""API regression coverage for the link-scoped incident lifecycle.

Every test patches the API module to a UUID-named graph. Teardown refuses to
delete any graph that could be the configured demo graph.
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import api
from backend.graph_repository import GraphRepository
from backend.incident_memory import IncidentMemory
from backend.network_model import Interface, Link, Router
from backend.telemetry import SimulatedTelemetry


@pytest.fixture
def isolated_client(monkeypatch):
    graph_name = f"test_api_{uuid4().hex}"
    configured_graph = os.getenv("FALKORDB_GRAPH", "routesage")
    assert graph_name.startswith("test_api_")
    assert graph_name != configured_graph

    test_repo = GraphRepository(graph_name=graph_name)
    monkeypatch.setattr(api, "repo", test_repo)
    monkeypatch.setattr(api, "memory", IncidentMemory(test_repo))
    monkeypatch.setattr(api, "telemetry", SimulatedTelemetry())

    try:
        yield TestClient(api.app), test_repo
    finally:
        # This fixture must never modify the configured application graph.
        assert test_repo.graph.name == graph_name
        assert graph_name.startswith("test_api_")
        assert graph_name != configured_graph
        test_repo.graph.delete()


def seed_three_router_chain(repo: GraphRepository) -> None:
    for router, address in (("R1", "10.0.0.1"), ("R2", "10.0.0.2"), ("R3", "10.0.0.3")):
        repo.add_router(Router(router, address))
        repo.add_interface(router, Interface("eth0", address, "up"))
    repo.add_link(Link("R1:eth0", "R2:eth0", "down"))
    repo.add_link(Link("R2:eth0", "R3:eth0", "down"))


def incident_payload(source_interface: str, destination_interface: str) -> dict:
    return {
        "source_router": "R1",
        "destination_router": "R3",
        "symptom": "Destination unreachable",
        "root_cause": "Observed simulated link failure",
        "remediation": "Restore the affected link and verify reachability",
        "affected_source_interface": source_interface,
        "affected_destination_interface": destination_interface,
    }


def test_duplicate_incident_creation_is_idempotent(isolated_client):
    client, _ = isolated_client
    payload = incident_payload("R1:eth0", "R2:eth0")

    first = client.post("/api/incidents", json=payload)
    second = client.post("/api/incidents", json={**payload, "root_cause": "Different wording"})
    history = client.get("/api/incidents")

    assert first.status_code == 200
    assert first.json()["created"] is True
    assert second.status_code == 200
    assert second.json() == {"saved": True, "created": False, "incident_id": first.json()["incident_id"]}
    assert len(history.json()["incidents"]) == 1


def test_restore_matches_exact_link_and_requires_reachability(isolated_client):
    client, repo = isolated_client
    seed_three_router_chain(repo)
    first_link = client.post("/api/incidents", json=incident_payload("R1:eth0", "R2:eth0")).json()
    second_link = client.post("/api/incidents", json=incident_payload("R2:eth0", "R3:eth0")).json()

    restore_first = client.post(
        "/api/links/state",
        json={"source_interface": "R1:eth0", "destination_interface": "R2:eth0", "state": "up"},
    )
    history = {item["incident_id"]: item for item in client.get("/api/incidents").json()["incidents"]}

    assert restore_first.status_code == 200
    assert restore_first.json()["resolved_incidents"] == []
    assert restore_first.json()["awaiting_verification"] == [first_link["incident_id"]]
    assert history[first_link["incident_id"]]["resolved"] is False
    assert history[second_link["incident_id"]]["resolved"] is False


def test_successful_recovery_is_idempotent_and_preserves_resolved_history(isolated_client):
    client, repo = isolated_client
    seed_three_router_chain(repo)
    created = client.post("/api/incidents", json=incident_payload("R2:eth0", "R3:eth0")).json()

    assert client.post(
        "/api/links/state",
        json={"source_interface": "R1:eth0", "destination_interface": "R2:eth0", "state": "up"},
    ).status_code == 200
    recovered = client.post(
        "/api/links/state",
        json={"source_interface": "R2:eth0", "destination_interface": "R3:eth0", "state": "up"},
    )
    repeated_restore = client.post(
        "/api/links/state",
        json={"source_interface": "R2:eth0", "destination_interface": "R3:eth0", "state": "up"},
    )
    history = client.get("/api/incidents").json()["incidents"]

    assert recovered.json()["resolved_incidents"] == [created["incident_id"]]
    assert repeated_restore.json()["resolved_incidents"] == []
    assert len(history) == 1
    assert history[0]["incident_id"] == created["incident_id"]
    assert history[0]["resolved"] is True
    assert history[0]["affected_source_interface"] == "R2:eth0"
    assert history[0]["affected_destination_interface"] == "R3:eth0"
    assert history[0]["resolved_at"]
    assert history[0]["resolved_by"] == "system:link-recovery-verification"


def test_manual_resolution_records_actor_reason_and_evidence(isolated_client):
    client, _ = isolated_client
    created = client.post("/api/incidents", json=incident_payload("R1:eth0", "R2:eth0")).json()

    response = client.post(
        f"/api/incidents/{created['incident_id']}/resolve",
        json={
            "reason": "Maintenance completed",
            "verification_evidence": "Operator confirmed service recovery",
            "actor": "network-engineer",
        },
    )
    repeated = client.post(
        f"/api/incidents/{created['incident_id']}/resolve",
        json={"reason": "Duplicate retry", "verification_evidence": "Not used", "actor": "network-engineer"},
    )
    history = client.get("/api/incidents").json()["incidents"]

    assert response.status_code == 200
    assert response.json()["already_resolved"] is False
    assert repeated.json()["already_resolved"] is True
    assert history[0]["resolved"] is True
    assert history[0]["resolution_reason"] == "Maintenance completed"
    assert history[0]["verification_evidence"] == "Operator confirmed service recovery"
    assert history[0]["resolved_by"] == "network-engineer"


def test_simulation_event_stream_is_labeled_and_scoped_to_test_graph(isolated_client):
    client, repo = isolated_client
    seed_three_router_chain(repo)

    assert client.post("/api/simulation/start").json() == {"running": True, "source": "simulated"}
    assert client.post(
        "/api/links/state",
        json={"source_interface": "R1:eth0", "destination_interface": "R2:eth0", "state": "up"},
    ).status_code == 200
    stream = client.get("/api/simulation/events").json()
    assert client.post("/api/simulation/stop").json() == {"running": False, "source": "simulated"}

    assert stream["source"] == "simulated"
    assert stream["running"] is True
    assert stream["events"][0]["event_type"] == "link_state_changed"
    assert stream["events"][0]["state"] == "up"
