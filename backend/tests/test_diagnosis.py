
from uuid import uuid4

from backend.graph_repository import GraphRepository
from backend.network_model import Router, Interface, Link
from backend.diagnosis import diagnose_connectivity
from backend.diagnosis import diagnose_with_memory
from backend.incident_memory import Incident, IncidentMemory


def build_topology(repo, suffix, link_state="up", source_state="up",
                   destination_state="up"):
    source = f"R1_{suffix}"
    destination = f"R2_{suffix}"

    repo.add_router(Router(source, "10.0.0.1"))
    repo.add_router(Router(destination, "10.0.0.2"))

    repo.add_interface(
        source,
        Interface("eth0", "10.0.0.1", source_state),
    )
    repo.add_interface(
        destination,
        Interface("eth0", "10.0.0.2", destination_state),
    )

    repo.add_link(
        Link(f"{source}:eth0", f"{destination}:eth0", link_state)
    )

    return source, destination


def test_diagnoses_operational_direct_link():
    repo = GraphRepository(graph_name=f"test_{uuid4().hex}")
    graph_name = repo.graph.name
    suffix = uuid4().hex[:8]

    try:
        source, destination = build_topology(repo, suffix)

        result = diagnose_connectivity(repo, source, destination)

        assert result["reachable"] is True
        assert result["reason"] == "operational_direct_link"
    finally:
        repo.graph.delete()


def test_diagnoses_down_link():
    repo = GraphRepository(graph_name=f"test_{uuid4().hex}")
    suffix = uuid4().hex[:8]

    try:
        source, destination = build_topology(
            repo, suffix, link_state="down"
        )

        result = diagnose_connectivity(repo, source, destination)

        assert result["reachable"] is False
        assert result["reason"] == "direct_link_not_operational"
        assert result["evidence"][0]["link_state"] == "down"
    finally:
        repo.graph.delete()


def test_reports_missing_router():
    repo = GraphRepository(graph_name=f"test_{uuid4().hex}")

    try:
        result = diagnose_connectivity(repo, "MISSING_A", "MISSING_B")

        assert result["reachable"] is False
        assert result["reason"] == "router_not_found"
    finally:
        repo.graph.delete()


def test_diagnoses_multi_hop_path():
    repo = GraphRepository(graph_name=f"test_{uuid4().hex}")
    suffix = uuid4().hex[:8]

    try:
        r1 = f"R1_{suffix}"
        r2 = f"R2_{suffix}"
        r3 = f"R3_{suffix}"

        for name, ip in [
            (r1, "10.0.0.1"),
            (r2, "10.0.0.2"),
            (r3, "10.0.0.3"),
        ]:
            repo.add_router(Router(name, ip))
            repo.add_interface(
                name,
                Interface("eth0", ip, "up"),
            )

        repo.add_link(Link(f"{r1}:eth0", f"{r2}:eth0", "up"))
        repo.add_link(Link(f"{r2}:eth0", f"{r3}:eth0", "up"))

        result = diagnose_connectivity(repo, r1, r3)

        assert result["reachable"] is True
        assert result["reason"] == "operational_path"
        assert result["path"] == [r1, r2, r3]

    finally:
        repo.graph.delete()


def test_uses_operational_alternate_route():
    repo = GraphRepository(graph_name=f"test_{uuid4().hex}")
    suffix = uuid4().hex[:8]

    r1 = f"R1_{suffix}"
    r2 = f"R2_{suffix}"
    r3 = f"R3_{suffix}"
    r4 = f"R4_{suffix}"

    try:
        routers = [
            (r1, "10.0.0.1"),
            (r2, "10.0.0.2"),
            (r3, "10.0.0.3"),
            (r4, "10.0.0.4"),
        ]

        for name, ip in routers:
            repo.add_router(Router(name, ip))
            repo.add_interface(name, Interface("eth0", ip, "up"))

        # First route: R1 -> R2 -> R4, but R2 -> R4 is down.
        repo.add_link(Link(f"{r1}:eth0", f"{r2}:eth0", "up"))
        repo.add_link(Link(f"{r2}:eth0", f"{r4}:eth0", "down"))

        # Alternate route: R1 -> R3 -> R4, fully operational.
        repo.add_link(Link(f"{r1}:eth0", f"{r3}:eth0", "up"))
        repo.add_link(Link(f"{r3}:eth0", f"{r4}:eth0", "up"))

        result = diagnose_connectivity(repo, r1, r4)

        assert result["reachable"] is True
        assert result["reason"] == "operational_path"
        assert result["path"] == [r1, r3, r4]

    finally:
        repo.graph.delete()


def test_explains_failed_multi_hop_path():
    repo = GraphRepository(graph_name=f"test_{uuid4().hex}")
    suffix = uuid4().hex[:8]

    r1 = f"R1_{suffix}"
    r2 = f"R2_{suffix}"
    r3 = f"R3_{suffix}"

    try:
        for name, ip in [
            (r1, "10.0.0.1"),
            (r2, "10.0.0.2"),
            (r3, "10.0.0.3"),
        ]:
            repo.add_router(Router(name, ip))
            repo.add_interface(name, Interface("eth0", ip, "up"))

        repo.add_link(Link(f"{r1}:eth0", f"{r2}:eth0", "up"))
        repo.add_link(Link(f"{r2}:eth0", f"{r3}:eth0", "down"))

        result = diagnose_connectivity(repo, r1, r3)

        assert result["reachable"] is False
        assert result["reason"] == "all_paths_have_failures"
        assert result["evidence"]
        assert any(
            edge["link_state"] == "down"
            for edge in result["evidence"]
        )

    finally:
        repo.graph.delete()


def test_reports_failures_when_all_alternate_routes_are_down():
    repo = GraphRepository(graph_name=f"test_{uuid4().hex}")
    suffix = uuid4().hex[:8]

    r1 = f"R1_{suffix}"
    r2 = f"R2_{suffix}"
    r3 = f"R3_{suffix}"
    r4 = f"R4_{suffix}"

    try:
        routers = [
            (r1, "10.0.0.1"),
            (r2, "10.0.0.2"),
            (r3, "10.0.0.3"),
            (r4, "10.0.0.4"),
        ]

        for name, ip in routers:
            repo.add_router(Router(name, ip))
            repo.add_interface(name, Interface("eth0", ip, "up"))

        # Two possible routes to R4; each contains a down link.
        repo.add_link(Link(f"{r1}:eth0", f"{r2}:eth0", "up"))
        repo.add_link(Link(f"{r2}:eth0", f"{r4}:eth0", "down"))
        repo.add_link(Link(f"{r1}:eth0", f"{r3}:eth0", "up"))
        repo.add_link(Link(f"{r3}:eth0", f"{r4}:eth0", "down"))

        result = diagnose_connectivity(repo, r1, r4)

        assert result["reachable"] is False
        assert result["reason"] == "all_paths_have_failures"
        assert result["evidence"]
        assert any(
            edge["link_state"] == "down"
            for edge in result["evidence"]
        )

    finally:
        repo.graph.delete()


def test_diagnosis_includes_matching_incident_history():
    repo = GraphRepository(graph_name=f"test_{uuid4().hex}")
    memory = IncidentMemory(repo)
    suffix = uuid4().hex[:8]
    source = f"R1_{suffix}"
    destination = f"R2_{suffix}"

    try:
        repo.add_router(Router(source, "10.0.0.1"))
        repo.add_router(Router(destination, "10.0.0.2"))
        repo.add_interface(source, Interface("eth0", "10.0.0.1", "up"))
        repo.add_interface(destination, Interface("eth0", "10.0.0.2", "up"))
        repo.add_link(Link(f"{source}:eth0", f"{destination}:eth0", "down"))

        memory.record(
            Incident(
                source_router=source,
                destination_router=destination,
                symptom="Destination unreachable",
                root_cause="Historical link failure",
                remediation="Restore the link",
                resolved=True,
            )
        )

        result = diagnose_with_memory(repo, memory, source, destination)

        assert result["reachable"] is False
        assert len(result["historical_incidents"]) == 1
        assert (
            result["historical_incidents"][0]["root_cause"]
            == "Historical link failure"
        )

    finally:
        repo.graph.delete()

def test_finds_alternate_path_with_shared_intermediate_router():
    repo = GraphRepository(graph_name=f"test_{uuid4().hex}")
    suffix = uuid4().hex[:8]

    r1 = f"R1_{suffix}"
    r2 = f"R2_{suffix}"
    r3 = f"R3_{suffix}"
    r4 = f"R4_{suffix}"
    r5 = f"R5_{suffix}"

    try:
        routers = [
            (r1, "10.0.0.1"),
            (r2, "10.0.0.2"),
            (r3, "10.0.0.3"),
            (r4, "10.0.0.4"),
            (r5, "10.0.0.5"),
        ]

        for name, ip in routers:
            repo.add_router(Router(name, ip))
            repo.add_interface(name, Interface("eth0", ip, "up"))

        # Two routes share R2, but R2 -> R4 is down.
        repo.add_link(Link(f"{r1}:eth0", f"{r2}:eth0", "up"))
        repo.add_link(Link(f"{r2}:eth0", f"{r4}:eth0", "down"))
        repo.add_link(Link(f"{r2}:eth0", f"{r3}:eth0", "up"))
        repo.add_link(Link(f"{r3}:eth0", f"{r4}:eth0", "up"))

        result = diagnose_connectivity(repo, r1, r4)

        assert result["reachable"] is True
        assert result["path"] == [r1, r2, r3, r4]

    finally:
        repo.graph.delete()


def test_reports_operational_and_failed_alternate_paths():
    repo = GraphRepository(graph_name=f"test_{uuid4().hex}")
    suffix = uuid4().hex[:8]

    r1 = f"R1_{suffix}"
    r2 = f"R2_{suffix}"
    r3 = f"R3_{suffix}"
    r4 = f"R4_{suffix}"

    try:
        routers = [
            (r1, "10.0.0.1"),
            (r2, "10.0.0.2"),
            (r3, "10.0.0.3"),
            (r4, "10.0.0.4"),
        ]

        for name, ip in routers:
            repo.add_router(Router(name, ip))
            repo.add_interface(name, Interface("eth0", ip, "up"))

        # Route A: structurally exists, but its link is down.
        repo.add_link(Link(f"{r1}:eth0", f"{r2}:eth0", "up"))
        repo.add_link(Link(f"{r2}:eth0", f"{r4}:eth0", "down"))

        # Route B: fully operational.
        repo.add_link(Link(f"{r1}:eth0", f"{r3}:eth0", "up"))
        repo.add_link(Link(f"{r3}:eth0", f"{r4}:eth0", "up"))

        result = diagnose_connectivity(repo, r1, r4)

        assert result["reachable"] is True
        assert "paths" in result, (
            "Diagnosis should expose all relevant paths, not only one path"
        )



        paths = result["paths"]
        assert len(paths) == 2

        # Each distinct router/interface route must appear only once.
        path_signatures = [
            (
                tuple(item["path"]),
                tuple(
                    (
                        edge["source_interface"],
                        edge["destination_interface"],
                    )
                    for edge in item["edges"]
                ),
            )
            for item in paths
        ]
        assert len(path_signatures) == len(set(path_signatures))



    finally:
        repo.graph.delete()


def test_parallel_links_report_correct_operational_status():
    repo = GraphRepository(graph_name=f"test_{uuid4().hex}")

    try:
        r1 = f"R1_{uuid4().hex[:8]}"
        r2 = f"R2_{uuid4().hex[:8]}"

        for name, ip in [(r1, "10.0.0.1"), (r2, "10.0.0.2")]:
            repo.add_router(Router(name, ip))

        repo.add_interface(r1, Interface("eth0", "10.0.0.1", "up"))
        repo.add_interface(r1, Interface("eth1", "10.0.1.1", "up"))
        repo.add_interface(r2, Interface("eth0", "10.0.0.2", "up"))
        repo.add_interface(r2, Interface("eth1", "10.0.1.2", "up"))

        # One link is operational; the other is down.
        repo.add_link(Link(f"{r1}:eth0", f"{r2}:eth0", "up"))
        repo.add_link(Link(f"{r1}:eth1", f"{r2}:eth1", "down"))

        result = diagnose_connectivity(repo, r1, r2)

        assert result["reachable"] is True
        assert len(result["paths"]) == 2
        assert sum(path["operational"] for path in result["paths"]) == 1
        assert sum(not path["operational"] for path in result["paths"]) == 1

    finally:
        repo.graph.delete()
