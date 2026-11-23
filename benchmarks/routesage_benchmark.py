import csv
import json
import math
import statistics
import time
from pathlib import Path

from backend.diagnosis import diagnose_connectivity
from backend.failure_impact import analyze_link_impact


class QueryResult:
    def __init__(self, result_set):
        self.result_set = result_set


class FakeGraph:
    def __init__(self, routers, edges):
        self.routers = routers
        self.edges = edges

    def query(self, query, params=None):
        if "RETURN r.name AS name" in query or "RETURN r.name" in query:
            return QueryResult([[r] for r in self.routers])

        rows = []

        # Diagnosis query: interface names and operational states.
        if "si.name" in query and "si.id" not in query:
            for a, b, state, aid, bid in self.edges:
                ar, ai = aid.split(":")
                br, bi = bid.split(":")
                rows.append([ar, br, ai, bi, "up", "up", state])
            return QueryResult(rows)

        # Failure-impact snapshot query: names, IDs and states.
        if "si.id" in query:
            for a, b, state, aid, bid in self.edges:
                ar, ai = aid.split(":")
                br, bi = bid.split(":")
                rows.append([ar, br, ai, bi, aid, bid, "up", "up", state])
            return QueryResult(rows)

        return QueryResult([])


class FakeRepo:
    def __init__(self, routers, edges):
        self.graph = FakeGraph(routers, edges)


def make_chain(n):
    routers = [f"R{i}" for i in range(n)]
    edges = []

    for i in range(n - 1):
        a = f"R{i}:eth{i}_out"
        b = f"R{i+1}:eth{i}_in"
        edges.append((a, b, "up", a, b))

    return routers, edges


def percentile95(values):
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def measure(fn, warmups=10, repeats=100):
    for _ in range(warmups):
        fn()

    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)

    return {
        "median_ms": statistics.median(samples),
        "p95_ms": percentile95(samples),
        "min_ms": min(samples),
        "max_ms": max(samples),
        "samples_ms": samples,
    }


def main():
    output_dir = Path("benchmarks/results")
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []

    # The implementation bounds impact analysis to 100 router pairs.
    sizes = [5, 8, 10, 12, 14]

    for n in sizes:
        routers, edges = make_chain(n)
        repo = FakeRepo(routers, edges)

        diagnosis_fn = lambda: diagnose_connectivity(
            repo, routers[0], routers[-1]
        )

        impact_fn = lambda: analyze_link_impact(
            repo, edges[0][0], edges[0][1]
        )

        diagnosis_check = diagnosis_fn()
        impact_check = impact_fn()

        # Basic correctness checks for the chain topology.
        assert diagnosis_check["reachable"] is True
        assert diagnosis_check["path"] == routers
        assert impact_check["summary"]["pairs_analyzed"] == n * (n - 1) // 2
        assert impact_check["summary"]["newly_unreachable_pairs"] >= 1

        diagnosis_metrics = measure(diagnosis_fn)
        impact_metrics = measure(impact_fn)

        row = {
            "routers": n,
            "links": len(edges),
            "interfaces": len(edges) * 2,
            "topology": "chain",
            "diagnosis_median_ms": diagnosis_metrics["median_ms"],
            "diagnosis_p95_ms": diagnosis_metrics["p95_ms"],
            "impact_median_ms": impact_metrics["median_ms"],
            "impact_p95_ms": impact_metrics["p95_ms"],
            "router_pairs_analyzed": impact_check["summary"]["pairs_analyzed"],
            "affected_pairs": impact_check["summary"]["affected_pairs"],
            "newly_unreachable_pairs": impact_check["summary"]["newly_unreachable_pairs"],
        }

        results.append(row)

        print(f"\nTopology: chain, {n} routers")
        print(f"  Diagnosis median: {diagnosis_metrics['median_ms']:.3f} ms")
        print(f"  Diagnosis p95:    {diagnosis_metrics['p95_ms']:.3f} ms")
        print(f"  Impact median:    {impact_metrics['median_ms']:.3f} ms")
        print(f"  Impact p95:       {impact_metrics['p95_ms']:.3f} ms")
        print(f"  Pairs analyzed:   {row['router_pairs_analyzed']}")

    json_path = output_dir / "benchmark_results.json"
    csv_path = output_dir / "benchmark_results.csv"

    with json_path.open("w") as f:
        json.dump(results, f, indent=2)

    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)

    print("\nResults saved:")
    print(json_path)
    print(csv_path)


if __name__ == "__main__":
    main()
