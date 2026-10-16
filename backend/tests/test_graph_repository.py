
from uuid import uuid4

from backend.graph_repository import GraphRepository
from backend.network_model import Router, Interface, Link


def test_repository_stores_and_retrieves_topology():
    graph_name = f"test_{uuid4().hex}"
    repo = GraphRepository(graph_name=graph_name)

    suffix = uuid4().hex[:8]
    r1_name = f"R1_{suffix}"
    r2_name = f"R2_{suffix}"
    i1_id = f"{r1_name}:eth0"
    i2_id = f"{r2_name}:eth0"

    try:
        repo.add_router(Router(r1_name, "10.0.0.1"))
        repo.add_router(Router(r2_name, "10.0.0.2"))

        repo.add_interface(
            r1_name,
            Interface("eth0", "10.0.0.1", "up"),
        )
        repo.add_interface(
            r2_name,
            Interface("eth0", "10.0.0.2", "up"),
        )

        repo.add_link(Link(i1_id, i2_id, "up"))

        connections = repo.get_router_connections(r1_name)

        assert connections == [(r1_name, r2_name)]
    finally:
        repo.db.connection  # Keep the repository reference alive.
        repo.db.select_graph(graph_name).delete()
