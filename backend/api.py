"""RouteSage REST API: graph-backed network diagnostics and incident memory."""
from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

from backend.ai_service import AIServiceError, RouteSageAI
from backend.diagnosis import diagnose_connectivity, diagnose_with_memory
from backend.failure_impact import analyze_link_impact
from backend.graph_agent import investigate
from backend.graph_repository import GraphRepository
from backend.incident_memory import Incident, IncidentMemory
from backend.network_model import Interface, Link, Router
from backend.rate_limit import SlidingWindowRateLimiter
from backend.telemetry import SimulatedTelemetry


logger = logging.getLogger(__name__)

app = FastAPI(
    title="RouteSage API",
    description="Graph-grounded network reliability and incident intelligence.",
    version="1.0.0",
)

repo = GraphRepository(
    host=os.getenv("FALKORDB_HOST", "localhost"),
    port=int(os.getenv("FALKORDB_PORT", "6379")),
    graph_name=os.getenv("FALKORDB_GRAPH", "routesage"),
)
memory = IncidentMemory(repo)
ai_service = RouteSageAI()
telemetry = SimulatedTelemetry()
ai_rate_limiter = SlidingWindowRateLimiter(
    limit=int(os.getenv("ROUTESAGE_AI_RATE_LIMIT", "20")), window_seconds=60
)


class DiagnoseRequest(BaseModel):
    source: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=120)


class LinkStateRequest(BaseModel):
    source_interface: str = Field(min_length=1, max_length=255)
    destination_interface: str = Field(min_length=1, max_length=255)
    state: Literal["up", "down"]


class LinkImpactRequest(BaseModel):
    source_interface: str = Field(min_length=1, max_length=255)
    destination_interface: str = Field(min_length=1, max_length=255)


class AgentInvestigationRequest(BaseModel):
    source: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=120)
    selected_source_interface: str = Field(default="", max_length=255)
    selected_destination_interface: str = Field(default="", max_length=255)
    remember: bool = True


class AIDiagnoseRequest(BaseModel):
    source: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=120)
    question: str = Field(default="Explain the diagnosis and recommend safe next steps.", max_length=2000)


class ResolveIncidentRequest(BaseModel):
    reason: str = Field(default="Manually resolved by an operator", min_length=1, max_length=1000)
    verification_evidence: str = Field(
        default="Manual resolution; recovery verification was not recorded.",
        min_length=1,
        max_length=2000,
    )
    actor: str = Field(default="operator", min_length=1, max_length=120)


def query_rows(query: str, params: dict | None = None) -> list[list]:
    return repo.graph.query(query, params or {}).result_set


@app.get("/api/health")
def health():
    try:
        query_rows("RETURN 1")
        return {"status": "ok", "database": "connected", "graph": os.getenv("FALKORDB_GRAPH", "routesage")}
    except Exception as exc:
        logger.warning("FalkorDB health check failed", exc_info=exc)
        raise HTTPException(status_code=503, detail="FalkorDB is unavailable") from exc


@app.get("/api/topology")
def topology():
    routers = query_rows("""
        MATCH (r:Router)
        OPTIONAL MATCH (r)-[:HAS_INTERFACE]->(i:Interface)
        RETURN r.name, r.management_ip, collect({
            name: i.name, ip_address: i.ip_address,
            operational_state: i.operational_state
        })
        ORDER BY r.name
    """)
    links = query_rows("""
        MATCH (a:Interface)-[l:CONNECTED_TO]-(b:Interface)
        WHERE a.id < b.id
        MATCH (ra:Router)-[:HAS_INTERFACE]->(a)
        MATCH (rb:Router)-[:HAS_INTERFACE]->(b)
        RETURN ra.name, rb.name, a.id, b.id, l.state,
               a.operational_state, b.operational_state
    """)
    return {
        "routers": [
            {"name": row[0], "management_ip": row[1], "interfaces": row[2] or []}
            for row in routers if row[0]
        ],
        "links": [
            {"source": row[0], "target": row[1], "source_interface": row[2],
             "target_interface": row[3], "state": row[4],
             "source_state": row[5], "target_state": row[6],
             "operational": row[4] == "up" and row[5] == "up" and row[6] == "up"}
            for row in links
        ],
    }


@app.post("/api/diagnose")
def diagnose(request: DiagnoseRequest):
    try:
        result = diagnose_with_memory(repo, memory, request.source.strip(), request.destination.strip())
        # Explain only what the graph proves; do not present a language model as connected.
        if result["reachable"]:
            result["summary"] = f"Reachability is available from {result['source']} to {result['destination']}."
            result["recommendation"] = "No repair is required for the selected path. Review failed alternate paths if redundancy matters."
        elif result["reason"] == "router_not_found":
            result["summary"] = "One or both selected routers are not present in the graph."
            result["recommendation"] = "Check router names and load the intended topology."
        elif result["reason"] == "no_path":
            result["summary"] = "No structural path exists between the selected routers."
            result["recommendation"] = "Inspect topology discovery and missing interface connections."
        else:
            failed = [edge for edge in result.get("evidence", []) if edge.get("link_state") != "up" or edge.get("source_state") != "up" or edge.get("destination_state") != "up"]
            result["summary"] = f"No fully operational path exists from {result['source']} to {result['destination']}."
            result["recommendation"] = "Inspect the failed edge evidence below, then restore the affected link or interface and run diagnosis again."
            result["suspect_edges"] = failed
        return result
    except Exception as exc:
        logger.exception("Diagnosis failed")
        raise HTTPException(status_code=500, detail="Diagnosis failed; check server logs") from exc


@app.post("/api/ai/diagnose")
def ai_diagnose(request: AIDiagnoseRequest, http_request: Request):
    """Explain a graph-verified diagnosis with Gemini, without changing network state."""
    try:
        client_host = http_request.client.host if http_request.client else "unknown"
        if not ai_rate_limiter.allow(client_host):
            raise HTTPException(status_code=429, detail="AI request limit exceeded; try again shortly")
        source_name = request.source.strip()
        destination_name = request.destination.strip()
        if not source_name or not destination_name:
            raise HTTPException(status_code=422, detail="Source and destination are required.")

        diagnosis = diagnose_with_memory(
            repo, memory, source_name, destination_name
        )

        # The graph remains the source of truth; Gemini explains its evidence.
        graph_topology = topology()
        recent_incidents = incidents()["incidents"]

        explanation = ai_service.explain_diagnosis(
            question=request.question.strip() or "Explain the diagnosis and recommend safe next steps.",
            diagnosis=diagnosis,
            topology=graph_topology,
            incidents=recent_incidents,
        )
        return {
            "source": source_name,
            "destination": destination_name,
            "diagnosis": diagnosis,
            "ai": explanation,
        }
    except AIServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="AI diagnosis failed. Check API and database logs.") from exc


@app.get("/api/incidents")
def incidents():
    rows = query_rows("""
        MATCH (i:Incident)
        RETURN i.incident_id, i.source_router, i.destination_router, i.symptom,
               i.root_cause, i.remediation, i.resolved, i.created_at,
               i.affected_source_interface, i.affected_destination_interface,
               i.resolved_at, i.resolution_reason, i.verification_evidence,
               i.resolved_by
        ORDER BY i.created_at DESC LIMIT 100
    """)
    fields = ("incident_id", "source_router", "destination_router", "symptom",
              "root_cause", "remediation", "resolved", "created_at",
              "affected_source_interface", "affected_destination_interface",
              "resolved_at", "resolution_reason", "verification_evidence",
              "resolved_by")
    return {"incidents": [dict(zip(fields, row)) for row in rows]}


@app.post("/api/incidents")
def create_incident(incident: Incident):
    result = memory.record(incident)
    return {
        "saved": True,
        "created": result["created"],
        "incident_id": result["incident_id"],
    }


@app.post("/api/incidents/{incident_id}/resolve")
def resolve_incident(incident_id: str, request: ResolveIncidentRequest | None = None):
    request = request or ResolveIncidentRequest()
    if not memory.resolve(
        incident_id,
        reason=request.reason,
        verification_evidence=request.verification_evidence,
        actor=request.actor,
    ):
        if memory.is_resolved(incident_id):
            return {"resolved": True, "already_resolved": True, "incident_id": incident_id}
        raise HTTPException(status_code=404, detail="Incident not found")
    return {"resolved": True, "already_resolved": False, "incident_id": incident_id}


@app.post("/api/links/state")
def set_link_state(request: LinkStateRequest):
    result = repo.graph.query("""
        MATCH (a:Interface {id: $source_interface})-[l:CONNECTED_TO]-(b:Interface {id: $destination_interface})
        SET l.state = $state
        RETURN l.state
    """, request.model_dump())
    if not result.result_set:
        raise HTTPException(status_code=404, detail="Link not found; check interface IDs from /api/topology")

    telemetry.record_link_state(
        request.source_interface, request.destination_interface, request.state
    )

    resolved_incidents = []
    awaiting_verification = []
    if request.state == "up":
        link_key = "|".join(sorted((request.source_interface, request.destination_interface)))
        for incident in memory.open_incidents_for_link(link_key):
            verification = diagnose_connectivity(
                repo, incident["source_router"], incident["destination_router"]
            )
            if verification["reachable"]:
                if memory.resolve(
                    incident["incident_id"],
                    reason="Affected link restored and end-to-end reachability verified",
                    verification_evidence=(
                        f"Deterministic diagnosis confirmed {incident['source_router']} "
                        f"to {incident['destination_router']} is reachable after link restoration."
                    ),
                    actor="system:link-recovery-verification",
                ):
                    resolved_incidents.append(incident["incident_id"])
            else:
                awaiting_verification.append(incident["incident_id"])

    return {
        "updated": True,
        "state": request.state,
        "resolved_incidents": resolved_incidents,
        "awaiting_verification": awaiting_verification,
    }


@app.post("/api/links/impact")
def link_impact(request: LinkImpactRequest):
    try:
        return analyze_link_impact(
            repo,
            request.source_interface,
            request.destination_interface,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/agent/investigate")
def agent_investigate(request: AgentInvestigationRequest):
    try:
        return investigate(
            repo,
            memory,
            request.source.strip(),
            request.destination.strip(),
            selected_source_interface=request.selected_source_interface.strip(),
            selected_destination_interface=request.selected_destination_interface.strip(),
            remember=request.remember,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Graph agent investigation failed")
        raise HTTPException(status_code=500, detail="Graph agent investigation failed") from exc


@app.post("/api/simulation/start")
def start_simulation():
    """Enable local simulated-event recording; this never contacts devices."""
    telemetry.start()
    return {"running": telemetry.running, "source": "simulated"}


@app.post("/api/simulation/stop")
def stop_simulation():
    telemetry.stop()
    return {"running": telemetry.running, "source": "simulated"}


@app.get("/api/simulation/events")
def simulation_events(limit: int = 50):
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=422, detail="Limit must be between 1 and 200")
    return {
        "source": "simulated",
        "running": telemetry.running,
        "events": telemetry.events(limit),
    }


@app.post("/api/demo/seed")
def seed_demo():
    """Create a repeatable small topology for a first-run demonstration."""
    routers = [
        Router("EDGE-01", "10.10.0.1"),
        Router("CORE-01", "10.10.0.2"),
        Router("CORE-02", "10.10.0.3"),
        Router("APP-01", "10.10.0.4"),
        Router("DB-01", "10.10.0.5"),
    ]
    for router in routers:
        repo.add_router(router)
    interfaces = {
        "EDGE-01": [("eth0", "10.0.1.1"), ("eth1", "10.0.2.1")],
        "CORE-01": [("eth0", "10.0.1.2"), ("eth1", "10.0.3.1"), ("eth2", "10.0.4.1")],
        "CORE-02": [("eth0", "10.0.2.2"), ("eth1", "10.0.5.1"), ("eth2", "10.0.6.1")],
        "APP-01": [("eth0", "10.0.3.2"), ("eth1", "10.0.5.2")],
        "DB-01": [("eth0", "10.0.4.2"), ("eth1", "10.0.6.2")],
    }
    for router, items in interfaces.items():
        for name, ip in items:
            repo.add_interface(router, Interface(name, ip, "up"))
    links = [
        ("EDGE-01:eth0", "CORE-01:eth0", "up"),
        ("EDGE-01:eth1", "CORE-02:eth0", "up"),
        ("CORE-01:eth1", "APP-01:eth0", "up"),
        ("CORE-01:eth2", "DB-01:eth0", "up"),
        ("CORE-02:eth1", "APP-01:eth1", "up"),
        ("CORE-02:eth2", "DB-01:eth1", "up"),
    ]
    for source, destination, state in links:
        repo.add_link(Link(source, destination, state))
    return {"seeded": True, "routers": len(routers), "links": len(links),
            "message": "Demo topology is ready. Try EDGE-01 → DB-01."}


FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND), name="assets")

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(FRONTEND / "index.html")
