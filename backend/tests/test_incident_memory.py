
import pytest

from backend.incident_memory import Incident


def test_creates_incident_with_generated_metadata():
    incident = Incident(
        source_router="R1",
        destination_router="R3",
        symptom="Destination unreachable",
        root_cause="Link R2-R3 is down",
        remediation="Restore the failed link",
    )

    assert incident.incident_id
    assert incident.created_at
    assert incident.resolved is False


def test_rejects_empty_source_router():
    with pytest.raises(ValueError, match="Source router"):
        Incident(
            source_router=" ",
            destination_router="R3",
            symptom="Destination unreachable",
            root_cause="Link failure",
            remediation="Restore the link",
        )


def test_rejects_empty_symptom():
    with pytest.raises(ValueError, match="Symptom"):
        Incident(
            source_router="R1",
            destination_router="R3",
            symptom=" ",
            root_cause="Link failure",
            remediation="Restore the link",
        )


def test_incident_is_immutable():
    incident = Incident(
        source_router="R1",
        destination_router="R3",
        symptom="Destination unreachable",
        root_cause="Link failure",
        remediation="Restore the link",
    )

    with pytest.raises(AttributeError):
        incident.resolved = True


def test_link_identity_is_direction_independent():
    incident = Incident(
        source_router="R1",
        destination_router="R3",
        symptom="Destination unreachable",
        root_cause="Link failure",
        remediation="Restore the link",
        affected_source_interface="R1:eth0",
        affected_destination_interface="R2:eth1",
    )

    assert incident.affected_link_key == "R1:eth0|R2:eth1"


def test_rejects_partial_affected_link_reference():
    with pytest.raises(ValueError, match="Both affected interface IDs"):
        Incident(
            source_router="R1",
            destination_router="R3",
            symptom="Destination unreachable",
            root_cause="Link failure",
            remediation="Restore the link",
            affected_source_interface="R1:eth0",
        )


from uuid import uuid4

from backend.graph_repository import GraphRepository
from backend.incident_memory import IncidentMemory


def test_records_and_retrieves_incident():
    repo = GraphRepository(graph_name=f"test_{uuid4().hex}")
    memory = IncidentMemory(repo)

    try:
        incident = Incident(
            source_router="R1",
            destination_router="R3",
            symptom="Destination unreachable",
            root_cause="Link R2-R3 is down",
            remediation="Restore the failed link",
            resolved=True,
        )

        memory.record(incident)

        matches = memory.find_similar(
            "R1", "R3", "destination unreachable"
        )

        assert len(matches) == 1
        assert matches[0]["incident_id"] == incident.incident_id
        assert matches[0]["root_cause"] == "Link R2-R3 is down"
        assert matches[0]["resolved"] is True

    finally:
        repo.graph.delete()


def test_deduplicates_only_active_incidents_for_the_same_link_identity():
    repo = GraphRepository(graph_name=f"test_{uuid4().hex}")
    memory = IncidentMemory(repo)

    try:
        first = Incident(
            source_router="R1",
            destination_router="R3",
            symptom="Destination unreachable",
            root_cause="Observed link failure",
            remediation="Restore the link",
            affected_source_interface="R1:eth0",
            affected_destination_interface="R2:eth1",
        )
        retry = Incident(
            source_router="R1",
            destination_router="R3",
            symptom="Different wording must not change identity",
            root_cause="Another hypothesis",
            remediation="Investigate",
            affected_source_interface="R2:eth1",
            affected_destination_interface="R1:eth0",
        )
        unrelated = Incident(
            source_router="R1",
            destination_router="R3",
            symptom="Destination unreachable",
            root_cause="Another link failure",
            remediation="Restore another link",
            affected_source_interface="R2:eth2",
            affected_destination_interface="R3:eth0",
        )

        assert memory.record(first) == {"incident_id": first.incident_id, "created": True}
        assert memory.record(retry) == {"incident_id": first.incident_id, "created": False}
        assert memory.record(unrelated) == {"incident_id": unrelated.incident_id, "created": True}
        assert len(memory.open_incidents_for_link(first.affected_link_key)) == 1
        assert len(memory.open_incidents_for_link(unrelated.affected_link_key)) == 1
    finally:
        repo.graph.delete()


def test_incident_search_respects_limit():
    repo = GraphRepository(graph_name=f"test_{uuid4().hex}")
    memory = IncidentMemory(repo)

    try:
        for index in range(3):
            memory.record(
                Incident(
                    source_router="R1",
                    destination_router="R3",
                    symptom="Destination unreachable",
                    root_cause=f"Cause {index}",
                    remediation=f"Action {index}",
                )
            )

        matches = memory.find_similar(
            "R1", "R3", "Destination unreachable", limit=2
        )
        assert len(matches) == 2

    finally:
        repo.graph.delete()


def test_resolves_existing_incident():
    repo = GraphRepository(graph_name=f"test_{uuid4().hex}")
    memory = IncidentMemory(repo)

    try:
        incident = Incident(
            source_router="R1",
            destination_router="R3",
            symptom="Destination unreachable",
            root_cause="Link failure",
            remediation="Restore the link",
        )
        memory.record(incident)

        assert memory.resolve(
            incident.incident_id,
            reason="Operator verified recovery",
            verification_evidence="Ping succeeded",
            actor="test-operator",
        ) is True

        matches = memory.find_similar(
            "R1", "R3", "Destination unreachable"
        )
        assert len(matches) == 1
        assert matches[0]["resolved"] is True

    finally:
        repo.graph.delete()


def test_resolving_unknown_incident_returns_false():
    repo = GraphRepository(graph_name=f"test_{uuid4().hex}")
    memory = IncidentMemory(repo)

    try:
        assert memory.resolve(
            "unknown-incident-id",
            reason="Not applicable",
            verification_evidence="Not applicable",
        ) is False
    finally:
        repo.graph.delete()

def test_resolved_incidents_are_prioritized():
    repo = GraphRepository(graph_name=f"test_{uuid4().hex}")
    memory = IncidentMemory(repo)

    try:
        unresolved = Incident(
            source_router="R1",
            destination_router="R3",
            symptom="Destination unreachable",
            root_cause="Link failure",
            remediation="Restore the link",
        )
        resolved = Incident(
            source_router="R1",
            destination_router="R3",
            symptom="Destination unreachable",
            root_cause="Interface failure",
            remediation="Enable the interface",
        )

        memory.record(unresolved)
        memory.record(resolved)
        memory.resolve(
            resolved.incident_id,
            reason="Operator verified recovery",
            verification_evidence="Ping succeeded",
        )

        matches = memory.find_similar(
            "R1", "R3", "Destination unreachable"
        )

        assert len(matches) == 2
        assert matches[0]["incident_id"] == resolved.incident_id
        assert matches[0]["resolved"] is True
        assert matches[1]["incident_id"] == unresolved.incident_id
        assert matches[1]["resolved"] is False

    finally:
        repo.graph.delete()
