
from collections import deque

from backend.graph_repository import GraphRepository


def diagnose_connectivity(
    repo: GraphRepository,
    source_router: str,
    destination_router: str,
) -> dict:
    """Diagnose reachability across the modeled network topology."""

    router_result = repo.graph.query(
        "MATCH (r:Router) RETURN r.name AS name"
    )
    known_routers = {row[0] for row in router_result.result_set}

    if (
        source_router not in known_routers
        or destination_router not in known_routers
    ):
        return {
            "source": source_router,
            "destination": destination_router,
            "reachable": False,
            "reason": "router_not_found",
            "path": [],
            "evidence": [],
            "paths": [],
        }

    if source_router == destination_router:
        return {
            "source": source_router,
            "destination": destination_router,
            "reachable": True,
            "reason": "same_router",
            "path": [source_router],
            "evidence": [],
            "paths": [
                {
                    "path": [source_router],
                    "edges": [],
                    "operational": True,
                }
            ],
        }

    result = repo.graph.query(
        """
        MATCH (source:Router)-[:HAS_INTERFACE]->(si:Interface)
              -[link:CONNECTED_TO]-
              (di:Interface)<-[:HAS_INTERFACE]-(destination:Router)
        RETURN source.name, destination.name,
               si.name, di.name,
               si.operational_state, di.operational_state,
               link.state
        """
    )

    adjacency = {}

    for row in result.result_set:
        source, destination = row[0], row[1]

        edge = {
            "source_interface": row[2],
            "destination_interface": row[3],
            "source_state": row[4],
            "destination_state": row[5],
            "link_state": row[6],
        }

        adjacency.setdefault(source, []).append((destination, edge))
        adjacency.setdefault(
            destination,
            [
                *adjacency.get(destination, []),
                (
                    source,
                    {
                        **edge,
                        "source_interface": edge["destination_interface"],
                        "destination_interface": edge["source_interface"],
                        "source_state": edge["destination_state"],
                        "destination_state": edge["source_state"],
                    },
                ),
            ],
        )


    # FalkorDB's undirected relationship match can expose the same
    # connection more than once. Remove exact duplicate adjacency entries
    # while preserving distinct parallel links.
    for router, neighbors in adjacency.items():
        unique_neighbors = {}
        for neighbor, edge in neighbors:
            key = (
                neighbor,
                edge["source_interface"],
                edge["destination_interface"],
                edge["source_state"],
                edge["destination_state"],
                edge["link_state"],
            )
            unique_neighbors.setdefault(key, (neighbor, edge))
        adjacency[router] = list(unique_neighbors.values())

    def find_paths(operational_only: bool) -> list[dict]:
        """Find simple paths, optionally requiring operational edges."""
        max_depth = max(1, len(known_routers) - 1)
        queue = deque([(source_router, [source_router], [])])
        paths = []

        while queue and len(paths) < 100:
            current, path, evidence = queue.popleft()

            if current == destination_router:
                paths.append({"path": path, "edges": evidence})
                continue

            if len(path) - 1 >= max_depth:
                continue

            for neighbor, edge in adjacency.get(current, []):
                # Prevent cycles within this path, but allow other paths
                # to explore the same router independently.
                if neighbor in path:
                    continue

                operational = (
                    edge["link_state"] == "up"
                    and edge["source_state"] == "up"
                    and edge["destination_state"] == "up"
                )
                if operational_only and not operational:
                    continue

                queue.append(
                    (neighbor, path + [neighbor], evidence + [edge])
                )

        return paths



    candidates = find_paths(operational_only=True)
    failed_paths = find_paths(operational_only=False)

    # Include every structurally valid path and identify whether it works.

    operational_path_keys = {
        (
            tuple(candidate["path"]),
            tuple(
                (
                    edge["source_interface"],
                    edge["destination_interface"],
                )
                for edge in candidate["edges"]
            ),
        )
        for candidate in candidates
    }

    all_paths = [
        {
            **candidate,
            "operational": (
                tuple(candidate["path"]),
                tuple(
                    (
                        edge["source_interface"],
                        edge["destination_interface"],
                    )
                    for edge in candidate["edges"]
                ),
            ) in operational_path_keys,
        }
        for candidate in failed_paths
    ]


    if candidates:
        candidate = candidates[0]
        return {
            "source": source_router,
            "destination": destination_router,
            "reachable": True,
            "reason": (
                "operational_direct_link"
                if len(candidate["path"]) == 2
                else "operational_path"
            ),
            "path": candidate["path"],
            "evidence": candidate["edges"],
            "paths": all_paths,
        }

    if failed_paths:
        direct_only = all(
            len(candidate["path"]) == 2 for candidate in failed_paths
        )
        return {
            "source": source_router,
            "destination": destination_router,
            "reachable": False,
            "reason": (
                "direct_link_not_operational"
                if direct_only
                else "all_paths_have_failures"
            ),
            "path": [],
            "evidence": [
                edge
                for candidate in failed_paths
                for edge in candidate["edges"]
            ],
            "paths": all_paths,
        }

    return {
        "source": source_router,
        "destination": destination_router,
        "reachable": False,
        "reason": "no_path",
        "path": [],
        "evidence": [],
        "paths": [],
    }


from backend.incident_memory import IncidentMemory


def diagnose_with_memory(
    repo: GraphRepository,
    memory: IncidentMemory,
    source_router: str,
    destination_router: str,
) -> dict:
    """Combine current topology diagnosis with matching incident history."""

    diagnosis = diagnose_connectivity(
        repo, source_router, destination_router
    )

    symptom = (
        "Destination unreachable"
        if not diagnosis["reachable"]
        else "Connectivity restored"
    )

    history = memory.find_similar(
        source_router=source_router,
        destination_router=destination_router,
        symptom=symptom,
    )

    return {
        **diagnosis,
        "historical_incidents": history,
    }
