
from falkordb import FalkorDB

from backend.network_model import Router, Interface, Link


class GraphRepository:
    """Stores and retrieves network topology in FalkorDB."""

    def __init__(self, host="localhost", port=6379, graph_name="routesage"):
        self.db = FalkorDB(host=host, port=port)
        self.graph = self.db.select_graph(graph_name)

    def add_router(self, router: Router) -> None:
        self.graph.query(
            """
            MERGE (r:Router {name: $name})
            SET r.management_ip = $management_ip
            """,
            {
                "name": router.name,
                "management_ip": router.management_ip,
            },
        )

    def add_interface(self, router_name: str, interface: Interface) -> None:
        self.graph.query(
            """
            MATCH (r:Router {name: $router_name})
            MERGE (i:Interface {id: $interface_id})
            SET i.name = $name,
                i.ip_address = $ip_address,
                i.operational_state = $state
            MERGE (r)-[:HAS_INTERFACE]->(i)
            """,
            {
                "router_name": router_name,
                "interface_id": f"{router_name}:{interface.name}",
                "name": interface.name,
                "ip_address": interface.ip_address,
                "state": interface.operational_state,
            },
        )

    def add_link(self, link: Link) -> None:
        self.graph.query(
            """
            MATCH (source:Interface {id: $source_id})
            MATCH (destination:Interface {id: $destination_id})
            MERGE (source)-[connection:CONNECTED_TO]->(destination)
            SET connection.state = $state
            """,
            {
                "source_id": link.source_interface,
                "destination_id": link.destination_interface,
                "state": link.state,
            },
        )

    def get_router_connections(self, router_name: str) -> list[tuple[str, str]]:
        result = self.graph.query(
            """
            MATCH (source:Router {name: $router_name})
                  -[:HAS_INTERFACE]->(source_interface:Interface)
                  -[:CONNECTED_TO]->(destination_interface:Interface)
                  <-[:HAS_INTERFACE]-(destination:Router)
            RETURN source.name, destination.name
            """,
            {"router_name": router_name},
        )

        return [(row[0], row[1]) for row in result.result_set]
