# RouteSage - Graph-Grounded Network Reliability Intelligence

RouteSage is a graph-based network reliability and incident-diagnosis system built with FastAPI and FalkorDB. It models routers, interfaces, and network links, evaluates connectivity across multi-hop paths, analyzes hypothetical link failures, and maintains incident investigation history. An optional Gemini integration provides AI-assisted explanations grounded in graph-derived evidence.

## Overview

RouteSage addresses a central network reliability question:

**“What breaks if a link fails, what connectivity survives, and what should an operator investigate next?”**

Rather than relying solely on isolated device records, RouteSage evaluates relationships between routers, interfaces, and links in a graph database. It separates deterministic topology analysis from optional AI-generated explanations, allowing operators to inspect the underlying evidence behind a diagnosis.

## Key Features

- **Graph-based topology modeling:** Represents routers, interfaces, and network connections in FalkorDB.
- **Connectivity diagnosis:** Evaluates operational paths using link and interface state.
- **Failure-impact analysis:** Compares the current topology with a hypothetical link-outage scenario to identify affected router pairs, surviving paths, newly unreachable pairs, and operational link-disjoint path counts.
- **Evidence-driven investigation:** Combines deterministic diagnosis, failed-interface evidence, topology analysis, and relevant incident history.
- **Incident management:** Supports incident history, filtering, status tracking, and link-associated incident deduplication.
- **Recovery verification:** Supports reachability checks after simulated link restoration before associated incidents are resolved.
- **Reliability analytics:** Calculates topology metrics, including operational and failed link counts, average operational degree, and routers with limited operational neighbors.
- **Interactive dashboard:** Provides Overview, Topology Explorer, AI Investigation, Incident Center, and Reliability Analytics views.
- **Optional Gemini integration:** Generates explanations and investigation suggestions from supplied graph context, with a deterministic fallback when AI output is unavailable.
- **Investigation memory:** Persists investigation records in FalkorDB and associates them with analyzed routers.
- **Simulated telemetry:** Provides a bounded, in-memory event stream for demonstrating network state changes without requiring live network devices.

## Architecture

RouteSage consists of a browser-based dashboard, a FastAPI backend, a FalkorDB graph database, optional Gemini integration, incident memory, and simulated telemetry.

![RouteSage system architecture](docs/RouteSage_System_Architecture.png)

### Technology Stack

| Component | Technology |
|---|---|
| Backend API | Python, FastAPI |
| Graph database | FalkorDB |
| Graph queries | Cypher-compatible graph queries |
| AI-assisted explanations | Google Gemini, optional |
| Frontend | Browser-based dashboard |
| Testing | pytest |
| Local infrastructure | Docker |

## Installation and Configuration

### Prerequisites

- Python
- Docker Desktop
- Git
- A Gemini API key, if AI-assisted explanations are required

### 1. Start FalkorDB

Start Docker Desktop and launch the database container:

```powershell
docker run -d --name routesage-falkordb -p 6379:6379 -p 3000:3000 falkordb/falkordb:latest
```

If the container already exists but is stopped:

```powershell
docker start routesage-falkordb
```

Verify that the container is running:

```powershell
docker ps --filter "name=routesage-falkordb"
```

The default database connection is `localhost:6379`.

### 2. Create the Python Environment

Run the following commands from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell prevents virtual-environment activation, invoke its interpreter directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in the repository root if optional Gemini integration is required:

```dotenv
GEMINI_API_KEY=your_api_key
GEMINI_MODEL=gemini-3-flash-preview
ROUTESAGE_AI_RATE_LIMIT=20
```

Keep API keys private and do not commit `.env` to version control.

The application supports the following database configuration variables:

| Variable | Purpose |
|---|---|
| `FALKORDB_HOST` | FalkorDB hostname |
| `FALKORDB_PORT` | FalkorDB port |
| `FALKORDB_GRAPH` | Graph name |
| `GEMINI_API_KEY` | Optional Gemini API authentication |
| `GEMINI_MODEL` | Gemini model identifier |
| `ROUTESAGE_AI_RATE_LIMIT` | AI request limit per client IP |

The default AI request limit is 20 requests per client IP per 60-second window in the local process. This is a local safeguard, not a distributed production rate limiter.

When Gemini is unavailable, unconfigured, rate-limited, or returns unusable output, the AI diagnosis endpoint can return a deterministic fallback based on supplied graph-diagnosis facts.

### 4. Run the Application

Start the API and dashboard server from the repository root:

```powershell
python -m uvicorn backend.api:app --reload --port 8001
```

The application serves the browser dashboard and API from the same FastAPI process.

## Demonstration Workflow

The demonstration workflow covers topology inspection, failure analysis, investigation, and recovery verification.

1. Confirm that FalkorDB is available.
2. Load the demonstration topology using `POST /api/demo/seed` when the graph is empty.
3. Inspect routers, interfaces, and links in the Topology Explorer.
4. Simulate a link failure using the dashboard's failure-simulation controls.
5. Run a connectivity diagnosis and inspect the associated failed-interface evidence.
6. Analyze the impact of the hypothetical outage, including surviving paths and newly unreachable router pairs.
7. Review the investigation output and compare deterministic graph evidence with the optional Gemini explanation.
8. Inspect incident records and reliability metrics.
9. Restore the simulated link and rerun the connectivity diagnosis to verify end-to-end reachability.

Observed results depend on the topology and graph state loaded into FalkorDB.

## API Capabilities

The backend exposes endpoints for topology initialization, deterministic diagnosis, AI-assisted diagnosis, graph-agent investigation, and simulated telemetry.

| Endpoint | Purpose |
|---|---|
| `POST /api/demo/seed` | Load demonstration topology data |
| `POST /api/diagnose` | Run deterministic connectivity diagnosis |
| `POST /api/ai/diagnose` | Request an AI-assisted diagnosis |
| `POST /api/agent/investigate` | Run a graph-grounded investigation |
| `POST /api/simulation/start` | Start simulated event recording |
| `GET /api/simulation/events` | Retrieve recorded simulated events |
| `POST /api/simulation/stop` | Stop simulated event recording |

Request and response schemas are defined by the FastAPI application.

## Graph Investigation Agent

The graph investigation agent combines deterministic topology diagnosis, failure-impact analysis, failed-interface evidence, and relevant incident context.

The `POST /api/agent/investigate` endpoint evaluates the current FalkorDB graph and can persist an `Investigation` node connected to the analyzed `Router` nodes when `remember: true` is enabled.

The endpoint does not itself change network link state, create incidents, or resolve incidents. Its proposed action is a recommendation for operator review, not an executed remediation. The endpoint reports `executed: false`.

## Simulated Telemetry

RouteSage includes a bounded, in-memory event stream for demonstrating simulated link-state changes.

- Events are explicitly labeled with `source: simulated`.
- Event history belongs to the running application process.
- Events are not retained across application restarts.
- The stream does not represent telemetry collected from physical network devices.

## Testing

Run the backend test suite from the repository root:

```powershell
python -m pytest backend/tests -v
```

The tests use isolated graph names and require a reachable FalkorDB instance. Start FalkorDB before running the suite.

## Scope and Limitations

- The bundled topology is demonstration data, not a live network inventory.
- RouteSage does not currently ingest SNMP, streaming telemetry, or packet captures.
- Simulated telemetry is not equivalent to real-time monitoring of physical network devices.
- Failure-impact analysis is bounded to at most 100 router pairs and 100 paths per pair. It evaluates hypothetical graph states rather than predicting real-world network behavior.
- Incident deduplication uses stable, unordered interface-pair identifiers for link-associated incidents. Legacy incidents without a link reference are preserved as independent records.
- Gemini-generated explanations are not formal proofs. Root-cause statements should be treated as hypotheses, and recommendations require human review.
- Investigation memory is local to the configured FalkorDB graph and has no tenant isolation or retention policy in this prototype.
- Production deployment would require appropriate authentication, authorization, secret management, deployment hardening, and operational observability.

RouteSage is a network reliability engineering prototype focused on graph-grounded diagnosis, traceable evidence, and incident investigation memory.
