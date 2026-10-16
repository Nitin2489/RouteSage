"""RouteSage REST API: graph-backed network diagnostics and incident memory."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.diagnosis import diagnose_with_memory
from backend.graph_repository import GraphRepository
from backend.incident_memory import Incident, IncidentMemory
from backend.network_model import Interface, Link, Router

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


class DiagnoseRequest(BaseModel):
    source: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=120)


class LinkStateRequest(BaseModel):
    source_interface: str
    destination_interface: str
    state: Literal["up", "down"]


def query_rows(query: str, params: dict | None = None) -> list[list]:
    return repo.graph.query(query, params or {}).result_set


@app.get("/api/health")
def health():
    try:
        query_rows("RETURN 1")
        return {"status": "ok", "database": "connected", "graph": os.getenv("FALKORDB_GRAPH", "routesage")}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"FalkorDB unavailable: {exc}") from exc


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
        raise HTTPException(status_code=500, detail=f"Diagnosis failed: {exc}") from exc


@app.get("/api/incidents")
def incidents():
    rows = query_rows("""
        MATCH (i:Incident)
        RETURN i.incident_id, i.source_router, i.destination_router, i.symptom,
               i.root_cause, i.remediation, i.resolved, i.created_at
        ORDER BY i.created_at DESC LIMIT 100
    """)
    fields = ("incident_id", "source_router", "destination_router", "symptom",
              "root_cause", "remediation", "resolved", "created_at")
    return {"incidents": [dict(zip(fields, row)) for row in rows]}


@app.post("/api/incidents")
def create_incident(incident: Incident):
    memory.record(incident)
    return {"saved": True, "incident": incident}


@app.post("/api/incidents/{incident_id}/resolve")
def resolve_incident(incident_id: str):
    if not memory.resolve(incident_id):
        raise HTTPException(status_code=404, detail="Incident not found")
    return {"resolved": True, "incident_id": incident_id}


@app.post("/api/links/state")
def set_link_state(request: LinkStateRequest):
    result = repo.graph.query("""
        MATCH (a:Interface {id: $source_interface})-[l:CONNECTED_TO]-(b:Interface {id: $destination_interface})
        SET l.state = $state
        RETURN l.state
    """, request.model_dump())
    if not result.result_set:
        raise HTTPException(status_code=404, detail="Link not found; check interface IDs from /api/topology")
    return {"updated": True, "state": request.state}


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
