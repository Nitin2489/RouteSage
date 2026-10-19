
from falkordb import FalkorDB


def main():
    db = FalkorDB(host="localhost", port=6379)
    graph = db.select_graph("routesage")

    result = graph.query("RETURN 1 AS connected")

    if result.result_set != [[1]]:
        raise RuntimeError("FalkorDB connectivity check failed")

    print("Connected to FalkorDB successfully!")
    print("Connectivity check passed.")


if __name__ == "__main__":
    main()
