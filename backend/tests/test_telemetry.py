import pytest

from backend.telemetry import SimulatedTelemetry


def test_simulation_records_only_while_running_and_labels_events():
    telemetry = SimulatedTelemetry()
    telemetry.record_link_state("R1:eth0", "R2:eth0", "down")
    assert telemetry.events() == []

    telemetry.start()
    telemetry.record_link_state("R1:eth0", "R2:eth0", "down")
    telemetry.stop()
    events = telemetry.events()

    assert [event["event_type"] for event in events] == [
        "simulation_stopped", "link_state_changed", "simulation_started"
    ]
    assert all(event["source"] == "simulated" for event in events)


def test_simulation_enforces_event_query_limit():
    with pytest.raises(ValueError, match="between 1 and 200"):
        SimulatedTelemetry().events(0)
