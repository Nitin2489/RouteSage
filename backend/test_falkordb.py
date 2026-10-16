
from falkordb import FalkorDB


def main():
    db = FalkorDB(host="localhost", port=6379)
    graph = db.select_graph("routesage")

    result = graph.query(
        """
        MATCH (a:Router {name: 'R1'})-[:CONNECTED_TO]->(b:Router)
        RETURN a.name AS source, b.name AS destination
        """
    )

    print("Connected to FalkorDB successfully!")
    print("Query result:")

    for row in result.result_set:
        print(f"{row[0]} -> {row[1]}")


if __name__ == "__main__":
    main()
