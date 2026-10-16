# RouteSage demo script (3–4 minutes)

**Before recording:** start Docker Desktop and FalkorDB, activate the virtual environment, install requirements, then run `python -m uvicorn backend.api:app --reload`. Open http://127.0.0.1:8000 and verify the connection badge.

**0:00–0:25 — Problem.** Network failures are difficult to diagnose when topology, current state, and incident history are scattered. RouteSage puts that context in FalkorDB.

**0:25–1:00 — Graph.** Show topology and health metrics. Select routers and connections. Explain that routers, interfaces, and connections are explicit graph entities and relationships.

**1:00–2:00 — Failure.** Select a link and simulate failure. Diagnose reachability. Point to exact failed interface/link state and route evidence. Be clear: this version uses graph algorithms and diagnostic rules, not a connected LLM.

**2:00–2:45 — Recovery.** Restore the link and diagnose again. Show reachability returning.

**2:45–3:20 — Incident intelligence.** Show the incident timeline and API docs at `/docs`. Explain traceable graph evidence and persistent incident memory.

**Closing.** RouteSage turns graph context into evidence-backed network diagnosis, with a foundation for a provider-backed AI agent.

Do not claim live device telemetry, autonomous remediation, or an integrated LLM as existing functionality.
