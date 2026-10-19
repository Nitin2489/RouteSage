from pathlib import Path


def test_demo_link_selection_is_direction_independent_without_arbitrary_fallback():
    frontend = (Path(__file__).resolve().parents[2] / "frontend" / "index.html").read_text(
        encoding="utf-8"
    )
    demo_start = frontend.index("async function runDemo()")
    demo_end = frontend.index("async function resetDemo()", demo_start)
    demo = frontend[demo_start:demo_end]

    assert 'x.source === "CORE-01" && x.target === "APP-01"' in demo
    assert 'x.source === "APP-01" && x.target === "CORE-01"' in demo
    assert "Demo topology is missing the APP-01 ↔ CORE-01 link." in demo
    assert "|| state.links[0]" not in demo
    assert ") || l" not in demo
    assert "affected_source_interface: l.source_interface" in demo
    assert "affected_destination_interface: l.target_interface" in demo
    assert 'await api("/api/incidents", {' in demo
    assert demo.index('await diagnose();') < demo.index('await api("/api/incidents", {')


def test_diagnosis_panel_explains_reachable_paths_with_failed_alternates():
    frontend = (Path(__file__).resolve().parents[2] / "frontend" / "index.html").read_text(
        encoding="utf-8"
    )
    result_start = frontend.index("function renderResult(d)")
    result_end = frontend.index("async function diagnose()", result_start)
    result = frontend[result_start:result_end]

    assert "const failedPaths = (d.paths || []).filter((path) => !path.operational);" in result
    assert "Selected link failed; alternate path available." in result
    assert "End-to-end connectivity remains available through an operational route" in result
    assert "while the failed link may still reduce redundancy." in result
    assert "Failed path evidence" in result
    assert "e.source_interface" in result
    assert "e.destination_interface" in result


def test_frontend_renders_read_only_failure_impact_report():
    frontend = (Path(__file__).resolve().parents[2] / "frontend" / "index.html").read_text(
        encoding="utf-8"
    )

    assert 'api("/api/links/impact"' in frontend
    assert "maximum number of link-disjoint operational paths" in frontend
    assert "newly_unreachable_pairs" in frontend
    assert "surviving_paths" in frontend


def test_frontend_exposes_graph_investigation_agent():
    frontend = (Path(__file__).resolve().parents[2] / "frontend" / "index.html").read_text(
        encoding="utf-8"
    )

    assert 'api("/api/agent/investigate"' in frontend
    assert "Graph agent decision" in frontend
    assert "evidence_trace" in frontend
    assert "memory_recorded" in frontend
    assert "Proposed action only" in frontend
    assert "operator confirmation required" in frontend
