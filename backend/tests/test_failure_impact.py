from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import api
from backend.failure_impact import analyze_link_impact
from backend.graph_repository import GraphRepository
from backend.incident_memory import IncidentMemory
from backend.network_model import Interface, Link, Router


def build_graph(links):
    repo = GraphRepository(graph_name=f"test_impact_{uuid4().hex}")
    interfaces = {
        interface
        for link in links
        for interface in link[:2]
    }
    routers = sorted(interface.split(":")[0] for interface in interfaces)
    for index, router in enumerate(routers, start=1):
        repo.add_router(Router(router, f"10.0.0.{index}"))
    for offset, interface_id in enumerate(sorted(interfaces), start=1):
        router, name = interface_id.split(":")
        repo.add_interface(router, Interface(name, f"10.0.1.{offset}", "up"))
    for source, destination, state in links:
        repo.add_link(Link(source, destination, state))
    return repo


@pytest.fixture
def impact_client(monkeypatch):
    repo = build_graph(
        [
            ("A:eth0", "B:eth0", "up"),
            ("B:eth1", "C:eth0", "up"),
        ]
    )
    monkeypatch.setattr(api, "repo", repo)
    monkeypatch.setattr(api, "memory", IncidentMemory(repo))
    try:
        yield TestClient(api.app), repo
    finally:
        repo.graph.delete()


def test_reports_surviving_alternate_and_reduced_link_disjoint_redundancy():
    repo = build_graph(
        [
            ("A:eth0", "B:eth0", "up"),
            ("B:eth1", "D:eth0", "up"),
            ("A:eth1", "C:eth0", "up"),
            ("C:eth1", "D:eth1", "up"),
        ]
    )
    try:
        result = analyze_link_impact(repo, "A:eth0", "B:eth0")
        pair = next(
            item for item in result["affected_pairs"]
            if item["source"] == "A" and item["destination"] == "D"
        )
        assert result["metric"] == "maximum number of link-disjoint operational paths"
        assert pair["baseline_redundancy"] == 2
        assert pair["scenario_redundancy"] == 1
        assert pair["scenario_reachable"] is True
        assert pair["surviving_paths"][0]["path"] == ["A", "C", "D"]
    finally:
        repo.graph.delete()


def test_reports_newly_unreachable_pairs_when_no_alternate_exists():
    repo = build_graph(
        [
            ("A:eth0", "B:eth0", "up"),
            ("B:eth1", "C:eth0", "up"),
        ]
    )
    try:
        result = analyze_link_impact(repo, "A:eth0", "B:eth0")
        assert {"source": "A", "destination": "C"} in result["newly_unreachable_pairs"]
    finally:
        repo.graph.delete()


def test_existing_multiple_failures_do_not_create_false_impact():
    repo = build_graph(
        [
            ("A:eth0", "B:eth0", "down"),
            ("B:eth1", "D:eth0", "down"),
            ("A:eth1", "C:eth0", "up"),
            ("C:eth1", "D:eth1", "up"),
        ]
    )
    try:
        result = analyze_link_impact(repo, "A:eth0", "B:eth0")
        assert result["summary"]["affected_pairs"] == 0
        assert result["summary"]["newly_unreachable_pairs"] == 0
    finally:
        repo.graph.delete()


def test_link_impact_does_not_cross_into_unrelated_component():
    repo = build_graph(
        [
            ("A:eth0", "B:eth0", "up"),
            ("B:eth1", "C:eth0", "up"),
            ("X:eth0", "Y:eth0", "up"),
        ]
    )
    try:
        result = analyze_link_impact(repo, "X:eth0", "Y:eth0")
        assert result["summary"]["newly_unreachable_pairs"] == 1
        assert all(
            pair["source"] in {"X", "Y"} or pair["destination"] in {"X", "Y"}
            for pair in result["affected_pairs"]
        )
    finally:
        repo.graph.delete()


def test_api_impact_analysis_is_read_only(impact_client):
    client, _ = impact_client
    before = client.get("/api/topology").json()
    response = client.post(
        "/api/links/impact",
        json={
            "source_interface": "A:eth0",
            "destination_interface": "B:eth0",
        },
    )
    after = client.get("/api/topology").json()

    assert response.status_code == 200
    assert response.json()["selected_link"]["state"] == "up"
    assert before == after
    assert client.get("/api/incidents").json()["incidents"] == []
