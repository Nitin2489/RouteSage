
import pytest

from backend.network_model import Router, Interface, Link


def test_valid_router():
    router = Router(name="R1", management_ip="192.168.1.1")
    assert router.name == "R1"


def test_router_rejects_invalid_ip():
    with pytest.raises(ValueError):
        Router(name="R1", management_ip="not-an-ip")


def test_valid_interface():
    interface = Interface(
        name="eth0",
        ip_address="10.0.0.1",
        operational_state="up",
    )
    assert interface.operational_state == "up"


def test_interface_rejects_invalid_state():
    with pytest.raises(ValueError):
        Interface(
            name="eth0",
            ip_address="10.0.0.1",
            operational_state="unknown",
        )


def test_valid_link():
    link = Link(
        source_interface="R1:eth0",
        destination_interface="R2:eth0",
        state="up",
    )
    assert link.state == "up"


def test_link_rejects_same_interface():
    with pytest.raises(ValueError):
        Link(
            source_interface="R1:eth0",
            destination_interface="R1:eth0",
            state="up",
        )
