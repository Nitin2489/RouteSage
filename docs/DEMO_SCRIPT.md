# RouteSage demo script (3–4 minutes)

## Before recording

1. Start Docker Desktop and ensure the `routesage-falkordb` container is running.
2. Activate the project's virtual environment and install `requirements.txt`.
3. Set `GEMINI_API_KEY` in a local `.env` file if you want to show the optional Gemini explanation. Never show or commit the key.
4. Start the app with `python -m uvicorn backend.api:app --reload --port 8001`.
5. Open http://127.0.0.1:8001 and confirm the database connection badge is healthy. If the graph is empty, run `POST /api/demo/seed` at `/docs`.

## Walkthrough

**0:00–0:25 — Problem.** Network failures can be hard to investigate when topology, state, and incident history are disconnected. RouteSage brings modeled topology and diagnostic evidence into one view.

**0:25–1:00 — Graph model.** Show the routers, interfaces, and links. Explain that FalkorDB stores the topology as a graph, which supports multi-hop path analysis.

**1:00–2:00 — Let the graph agent investigate.** In **AI Investigation**, choose `EDGE-01` → `DB-01` and click **Ask graph agent**. It follows FalkorDB topology and incident context, identifies failed interface evidence, compares alternate paths, records an investigation memory, and recommends a safe next step. The evidence trace is the path behind its decision. Use **Run incident demo** (or select a connection, use **Analyze impact**, then use **Simulate failure**) to create the modeled failure. This changes only the modeled FalkorDB graph; it does not contact a network device. The read-only impact report uses maximum link-disjoint operational paths as its redundancy metric. Rerun diagnosis and point to the failed link/interface evidence. Show that an alternate operational route can preserve reachability while reducing redundancy.

**2:00–2:40 — Recovery and incident record.** Show the incident created by the demo, restore the same modeled link, and rerun diagnosis. The matching incident resolves only after deterministic end-to-end reachability is verified; unrelated incidents remain open.

**2:40–3:20 — Incident memory and AI.** Show the investigation memory in the agent response, then show incident history and `/docs`. If Gemini is configured, run AI diagnosis. Explain that graph analysis determines reachability and evidence; Gemini summarizes that context and proposes investigation steps. Its explanation is advisory, not a network action.

## Closing

RouteSage is a graph-backed network reliability prototype for evidence-based path diagnosis and incident context. It does not currently ingest live device telemetry, perform autonomous remediation, or replace an operator's judgment.
