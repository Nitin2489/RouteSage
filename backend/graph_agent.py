"""A bounded graph-grounded investigation agent for RouteSage."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from backend.diagnosis import diagnose_with_memory
from backend.failure_impact import analyze_link_impact
from backend.graph_repository import GraphRepository
from backend.incident_memory import IncidentMemory


def _failed_edges(diagnosis: dict) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    edges: list[dict] = []
    for path in diagnosis.get("paths", []):
        if path.get("operational"):
            continue
        for index, edge in enumerate(path.get("edges", [])):
            if (
                edge.get("link_state") == "up"
                and edge.get("source_state") == "up"
                and edge.get("destination_state") == "up"
            ):
                continue
            source_router = path.get("path", [])[index]
            destination_router = path.get("path", [])[index + 1]
            edge = {
                **edge,
                "source_interface": (
                    f"{source_router}:{edge.get('source_interface', '')}"
                ),
                "destination_interface": (
                    f"{destination_router}:{edge.get('destination_interface', '')}"
                ),
            }
            key = tuple(sorted((
                edge["source_interface"],
                edge["destination_interface"],
            )))
            if key != ("", "") and key not in seen:
                seen.add(key)
                edges.append(edge)
    return edges


def _remember(
    repo: GraphRepository,
    investigation_id: str,
    source: str,
    destination: str,
    decision: str,
    selected_link: dict | None,
) -> None:
    link_key = ""
    if selected_link:
        link_key = "|".join(sorted((
            selected_link["source_interface"],
            selected_link["destination_interface"],
        )))
    repo.graph.query(
        """
        MERGE (investigation:Investigation {investigation_id: $investigation_id})
        SET investigation.source_router = $source,
            investigation.destination_router = $destination,
            investigation.decision = $decision,
            investigation.affected_link_key = $affected_link_key,
            investigation.created_at = $created_at
        WITH investigation
        MATCH (source:Router {name: $source})
        MATCH (destination:Router {name: $destination})
        MERGE (investigation)-[:ANALYZED_ROUTE]->(source)
        MERGE (investigation)-[:ANALYZED_ROUTE]->(destination)
        """,
        {
            "investigation_id": investigation_id,
            "source": source,
            "destination": destination,
            "decision": decision,
            "affected_link_key": link_key,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _history(repo: GraphRepository, source: str, destination: str) -> list[dict]:
    rows = repo.graph.query(
        """
        MATCH (i:Investigation)-[:ANALYZED_ROUTE]->(source:Router)
        MATCH (i)-[:ANALYZED_ROUTE]->(destination:Router)
        WHERE source.name = $source AND destination.name = $destination
        RETURN i.investigation_id, i.decision, i.affected_link_key, i.created_at
        ORDER BY i.created_at DESC
        LIMIT 5
        """,
        {"source": source, "destination": destination},
    ).result_set
    fields = ("investigation_id", "decision", "affected_link_key", "created_at")
    return [dict(zip(fields, row)) for row in rows]


def investigate(
    repo: GraphRepository,
    memory: IncidentMemory,
    source: str,
    destination: str,
    *,
    selected_source_interface: str = "",
    selected_destination_interface: str = "",
    remember: bool = True,
) -> dict:
    """Use graph facts to choose a safe next step and persist the investigation."""
    diagnosis = diagnose_with_memory(repo, memory, source, destination)
    failed_edges = _failed_edges(diagnosis)

    selected_link = None
    if selected_source_interface and selected_destination_interface:
        selected_link = {
            "source_interface": selected_source_interface,
            "destination_interface": selected_destination_interface,
        }
    elif failed_edges:
        selected_link = {
            "source_interface": failed_edges[0]["source_interface"],
            "destination_interface": failed_edges[0]["destination_interface"],
        }

    impact = None
    if selected_link:
        impact = analyze_link_impact(
            repo,
            selected_link["source_interface"],
            selected_link["destination_interface"],
        )

    if diagnosis["reachable"] and failed_edges:
        decision = "preserve_connectivity_and_restore_failed_link"
        explanation = (
            "The route is reachable through an operational path, but a failed "
            "link reduces redundancy; restore that exact interface pair and re-verify."
        )
    elif not diagnosis["reachable"] and failed_edges:
        decision = "restore_failed_link_and_verify_reachability"
        explanation = (
            "No operational route remains; restore the graph-evidenced failed "
            "interface pair, then verify end-to-end reachability."
        )
    elif diagnosis["reachable"]:
        decision = "no_action"
        explanation = "The graph shows an operational route and no failed path evidence."
    else:
        decision = "inspect_topology"
        explanation = "The graph has no operational route or failed edge that identifies a repair."

    investigation_id = str(uuid4())
    history_before = _history(repo, source, destination)
    if remember:
        _remember(repo, investigation_id, source, destination, decision, selected_link)
    history = _history(repo, source, destination) if remember else history_before

    proposed_action = None
    if selected_link and decision != "no_action":
        proposed_action = {
            "executed": False,
            "method": "POST",
            "endpoint": "/api/links/state",
            "payload": {
                "source_interface": selected_link["source_interface"],
                "destination_interface": selected_link["destination_interface"],
                "state": "up",
            },
            "requires_operator_confirmation": True,
        }

    return {
        "investigation_id": investigation_id,
        "source": source,
        "destination": destination,
        "decision": decision,
        "explanation": explanation,
        "recommended_action": (
            "POST /api/links/state for the affected interface pair, then rerun diagnosis"
            if selected_link and decision != "no_action"
            else "No graph-changing action recommended."
        ),
        "proposed_action": proposed_action,
        "graph_evidence": {
            "diagnosis": diagnosis,
            "failed_edges": failed_edges,
            "impact": impact,
            "history": history,
        },
        "memory_recorded": remember,
        "evidence_trace": [
            "FalkorDB Router and Interface nodes supplied the current topology.",
            "CONNECTED_TO states supplied link availability and failed-edge evidence.",
            "Bounded path traversal compared operational and failed routes.",
            "Incident memory supplied prior context; prior Investigation nodes are returned below.",
        ],
    }
