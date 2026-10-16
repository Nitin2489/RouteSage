# RouteSage — Network Reliability Intelligence

Graph-powered network diagnosis and incident intelligence built with FalkorDB.

RouteSage models routers, interfaces, and links as a graph, finds operational and failed paths, exposes evidence behind connectivity decisions, and stores incident history. The dashboard lets operators inspect topology, inject a link failure, diagnose reachability, and restore the link.

> **AI transparency:** this version uses graph algorithms and evidence-based diagnostic rules. It does not claim an external LLM is connected. The grounded diagnosis response is designed to provide graph context to a provider-backed AI agent in a later iteration.

## Features
- FalkorDB graph model for routers, interfaces, and CONNECTED_TO relationships.
- Multi-hop path analysis, failed/operational alternate-path evidence, and interface/link state checks.
- Incident records and matching historical incident retrieval.
- FastAPI REST endpoints and a responsive dashboard with topology selection, health metrics, evidence panels, and failure/recovery controls.
- Tests for graph model, repository, diagnosis, and incident memory.

## Architecture
Browser dashboard (HTML/CSS/JS) → FastAPI REST API → graph diagnosis + incident memory → FalkorDB.

## Quick start (Windows PowerShell)

1. Start Docker Desktop. If the existing container is not running, run:

    docker run -d --name routesage-falkordb -p 6379:6379 -p 3000:3000 falkordb/falkordb:latest

2. From the repository root, activate the virtual environment and install dependencies:

    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install -r requirements.txt

3. Start the dashboard/API:

    python -m uvicorn backend.api:app --reload

Open http://127.0.0.1:8000; API docs: http://127.0.0.1:8000/docs. Configure FALKORDB_HOST, FALKORDB_PORT, and FALKORDB_GRAPH if needed. The current API expects FalkorDB at localhost:6379 by default.

## Demo
1. Verify the graph connection badge.
2. If the graph is empty, open http://127.0.0.1:8000/docs, find `POST /api/demo/seed`, and click **Try it out → Execute** to create the demonstration topology.
3. Select a topology link and inject a failure.
4. Diagnose source-to-destination connectivity and inspect graph evidence.
5. Restore the link and rerun diagnosis; show persistent incident history.

See docs/DEMO_SCRIPT.md for a concise recording script.

## Tests
With FalkorDB running, execute `python -m pytest -q` from the repository root. Tests use isolated graph names.

## Limitations
- Topology is modeled demo data, not telemetry from physical devices.
- No SNMP, streaming telemetry, or packet-capture ingestion yet.
- Incident similarity matches endpoints and symptom text; it does not use vector embeddings.
- External LLM integration is not claimed as complete until a provider, credentials, grounding, and error handling are configured and tested.

Built for Graph Hacks 2026: graph context, traceable evidence, and persistent incident memory for network troubleshooting.
