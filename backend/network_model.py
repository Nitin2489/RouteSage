
from dataclasses import dataclass
from ipaddress import ip_address


@dataclass(frozen=True)
class Router:
    """A router in the network topology."""
    name: str
    management_ip: str

    def __post_init__(self):
        if not self.name.strip():
            raise ValueError("Router name cannot be empty")
        ip_address(self.management_ip)


@dataclass(frozen=True)
class Interface:
    """A network interface belonging to a router."""
    name: str
    ip_address: str
    operational_state: str

    def __post_init__(self):
        if not self.name.strip():
            raise ValueError("Interface name cannot be empty")
        ip_address(self.ip_address)

        if self.operational_state not in {"up", "down"}:
            raise ValueError("Operational state must be 'up' or 'down'")


@dataclass(frozen=True)
class Link:
    """A connection between two network interfaces."""
    source_interface: str
    destination_interface: str
    state: str

    def __post_init__(self):
        if not self.source_interface.strip():
            raise ValueError("Source interface cannot be empty")
        if not self.destination_interface.strip():
            raise ValueError("Destination interface cannot be empty")
        if self.source_interface == self.destination_interface:
            raise ValueError("A link must connect two different interfaces")
        if self.state not in {"up", "down"}:
            raise ValueError("Link state must be 'up' or 'down'")
