"""Read-only link failure impact analysis over the current graph snapshot."""
from __future__ import annotations

from collections import deque

from backend.graph_repository import GraphRepository


MAX_PATHS = 100
MAX_ROUTER_PAIRS = 100


def _link_key(source_interface: str, destination_interface: str) -> str:
    return "|".join(sorted((source_interface, destination_interface)))


def _snapshot(repo: GraphRepository) -> tuple[set[str], dict[str, list[tuple[str, dict]]]]:
    routers = repo.graph.query("MATCH (r:Router) RETURN r.name").result_set
    known_routers = {row[0] for row in routers}
    rows = repo.graph.query(
        """
        MATCH (source:Router)-[:HAS_INTERFACE]->(si:Interface)
              -[link:CONNECTED_TO]-
              (di:Interface)<-[:HAS_INTERFACE]-(destination:Router)
        RETURN source.name, destination.name,
               si.name, di.name, si.id, di.id,
               si.operational_state, di.operational_state, link.state
        """
    ).result_set
    adjacency: dict[str, list[tuple[str, dict]]] = {}
    for row in rows:
        source, destination = row[0], row[1]
        edge = {
            "source_interface": row[2],
            "destination_interface": row[3],
            "source_interface_id": row[4],
            "destination_interface_id": row[5],
            "source_state": row[6],
            "destination_state": row[7],
            "link_state": row[8],
        }
        adjacency.setdefault(source, []).append((destination, edge))
        adjacency.setdefault(destination, []).append(
            (
                source,
                {
                    **edge,
                    "source_interface": edge["destination_interface"],
                    "destination_interface": edge["source_interface"],
                    "source_interface_id": edge["destination_interface_id"],
                    "destination_interface_id": edge["source_interface_id"],
                    "source_state": edge["destination_state"],
                    "destination_state": edge["source_state"],
                },
            )
        )
    for router, neighbors in adjacency.items():
        unique = {}
        for neighbor, edge in neighbors:
            key = (
                neighbor,
                edge["source_interface_id"],
                edge["destination_interface_id"],
            )
            unique.setdefault(key, (neighbor, edge))
        adjacency[router] = list(unique.values())
    return known_routers, adjacency


def _operational(edge: dict, excluded_link_key: str | None = None) -> bool:
    return (
        edge["link_state"] == "up"
        and edge["source_state"] == "up"
        and edge["destination_state"] == "up"
        and (
            excluded_link_key is None
            or _link_key(
                edge["source_interface_id"],
                edge["destination_interface_id"],
            )
            != excluded_link_key
        )
    )


def _paths(
    known_routers: set[str],
    adjacency: dict[str, list[tuple[str, dict]]],
    source: str,
    destination: str,
    excluded_link_key: str | None = None,
) -> list[dict]:
    queue = deque([(source, [source], [])])
    paths = []
    while queue and len(paths) < MAX_PATHS:
        current, path, edges = queue.popleft()
        if current == destination:
            paths.append({"path": path, "edges": edges})
            continue
        if len(path) - 1 >= max(1, len(known_routers) - 1):
            continue
        for neighbor, edge in adjacency.get(current, []):
            if neighbor in path or not _operational(edge, excluded_link_key):
                continue
            queue.append((neighbor, path + [neighbor], edges + [edge]))
    return paths


class _Flow:
    def __init__(self):
        self.graph: dict[str, list[list]] = {}

    def add(self, source: str, target: str, capacity: int) -> None:
        forward = [target, capacity, None]
        reverse = [source, 0, forward]
        forward[2] = reverse
        self.graph.setdefault(source, []).append(forward)
        self.graph.setdefault(target, []).append(reverse)

    def max_value(self, source: str, target: str) -> int:
        total = 0
        while True:
            level = {source: 0}
            queue = deque([source])
            while queue:
                current = queue.popleft()
                for neighbor, capacity, _ in self.graph.get(current, []):
                    if capacity and neighbor not in level:
                        level[neighbor] = level[current] + 1
                        queue.append(neighbor)
            if target not in level:
                return total
            cursor = {node: 0 for node in level}

            def send(current: str, amount: int) -> int:
                if current == target:
                    return amount
                edges = self.graph.get(current, [])
                while cursor[current] < len(edges):
                    edge = edges[cursor[current]]
                    neighbor, capacity, reverse = edge
                    if capacity and level.get(neighbor) == level[current] + 1:
                        pushed = send(neighbor, min(amount, capacity))
                        if pushed:
                            edge[1] -= pushed
                            reverse[1] += pushed
                            return pushed
                    cursor[current] += 1
                return 0

            while True:
                pushed = send(source, 10**9)
                if not pushed:
                    break
                total += pushed


def _redundancy(
    known_routers: set[str],
    adjacency: dict[str, list[tuple[str, dict]]],
    source: str,
    destination: str,
    excluded_link_key: str | None = None,
) -> int:
    flow = _Flow()
    added = set()
    for router, neighbors in adjacency.items():
        for _, edge in neighbors:
            if not _operational(edge, excluded_link_key):
                continue
            key = _link_key(
                edge["source_interface_id"],
                edge["destination_interface_id"],
            )
            if key in added:
                continue
            added.add(key)
            link_node = f"link:{key}"
            source_router = edge["source_interface_id"].split(":", 1)[0]
            destination_router = edge["destination_interface_id"].split(":", 1)[0]
            flow.add(source_router, link_node, 1)
            flow.add(destination_router, link_node, 1)
            flow.add(link_node, source_router, 1)
            flow.add(link_node, destination_router, 1)
    return flow.max_value(source, destination)


def analyze_link_impact(
    repo: GraphRepository,
    source_interface: str,
    destination_interface: str,
) -> dict:
    """Compare current paths with a hypothetical outage of one exact link."""
    known_routers, adjacency = _snapshot(repo)
    selected_key = _link_key(source_interface, destination_interface)
    selected_edges = [
        edge
        for neighbors in adjacency.values()
        for _, edge in neighbors
        if _link_key(edge["source_interface_id"], edge["destination_interface_id"])
        == selected_key
    ]
    if not selected_edges:
        raise LookupError("Selected link was not found in the graph")

    routers = sorted(known_routers)
    pairs = [
        (source, destination)
        for index, source in enumerate(routers)
        for destination in routers[index + 1 :]
    ]
    if len(pairs) > MAX_ROUTER_PAIRS:
        raise ValueError("Topology exceeds the bounded impact-analysis limit")

    affected_pairs = []
    newly_unreachable_pairs = []
    for source, destination in pairs:
        baseline_paths = _paths(known_routers, adjacency, source, destination)
        scenario_paths = _paths(
            known_routers, adjacency, source, destination, selected_key
        )
        baseline_redundancy = _redundancy(
            known_routers, adjacency, source, destination
        )
        scenario_redundancy = _redundancy(
            known_routers, adjacency, source, destination, selected_key
        )
        baseline_reachable = bool(baseline_paths)
        scenario_reachable = bool(scenario_paths)
        if baseline_reachable and not scenario_reachable:
            newly_unreachable_pairs.append(
                {"source": source, "destination": destination}
            )
        if (
            baseline_reachable != scenario_reachable
            or baseline_redundancy != scenario_redundancy
        ):
            affected_pairs.append(
                {
                    "source": source,
                    "destination": destination,
                    "baseline_reachable": baseline_reachable,
                    "scenario_reachable": scenario_reachable,
                    "baseline_redundancy": baseline_redundancy,
                    "scenario_redundancy": scenario_redundancy,
                    "surviving_paths": scenario_paths[:3],
                }
            )

    return {
        "selected_link": {
            "source_interface": source_interface,
            "destination_interface": destination_interface,
            "link_key": selected_key,
            "state": selected_edges[0]["link_state"],
        },
        "metric": "maximum number of link-disjoint operational paths",
        "summary": {
            "pairs_analyzed": len(pairs),
            "affected_pairs": len(affected_pairs),
            "newly_unreachable_pairs": len(newly_unreachable_pairs),
        },
        "affected_pairs": affected_pairs,
        "newly_unreachable_pairs": newly_unreachable_pairs,
    }
