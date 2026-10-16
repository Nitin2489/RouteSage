
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from backend.graph_repository import GraphRepository


@dataclass(frozen=True)
class Incident:
    """A recorded network incident and its resolution."""

    source_router: str
    destination_router: str
    symptom: str
    root_cause: str
    remediation: str
    resolved: bool = False
    incident_id: str = ""
    created_at: str = ""

    def __post_init__(self):
        fields = (
            ("source_router", self.source_router),
            ("destination_router", self.destination_router),
            ("symptom", self.symptom),
            ("root_cause", self.root_cause),
            ("remediation", self.remediation),
        )
        for name, value in fields:
            if not value.strip():
                label = name.replace("_", " ")
                label = label[0].upper() + label[1:]
                raise ValueError(f"{label} cannot be empty")

        if not self.incident_id:
            object.__setattr__(self, "incident_id", str(uuid4()))

        if not self.created_at:
            object.__setattr__(
                self, "created_at", datetime.now(timezone.utc).isoformat()
            )


class IncidentMemory:
    """Persists incidents and retrieves matching historical cases."""

    def __init__(self, repo: GraphRepository):
        self.graph = repo.graph

    def record(self, incident: Incident) -> None:
        self.graph.query(
            """
            MERGE (i:Incident {incident_id: $incident_id})
            SET i.source_router = $source_router,
                i.destination_router = $destination_router,
                i.symptom = $symptom,
                i.root_cause = $root_cause,
                i.remediation = $remediation,
                i.resolved = $resolved,
                i.created_at = $created_at
            """,
            {
                "incident_id": incident.incident_id,
                "source_router": incident.source_router,
                "destination_router": incident.destination_router,
                "symptom": incident.symptom,
                "root_cause": incident.root_cause,
                "remediation": incident.remediation,
                "resolved": incident.resolved,
                "created_at": incident.created_at,
            },
        )

    def find_similar(
        self,
        source_router: str,
        destination_router: str,
        symptom: str,
        limit: int = 5,
    ) -> list[dict]:
        """Find recent incidents matching the same endpoints and symptom."""
        if limit < 1:
            raise ValueError("Limit must be at least 1")

        result = self.graph.query(
            """
            MATCH (i:Incident)
            WHERE i.source_router = $source_router
              AND i.destination_router = $destination_router
              AND toLower(i.symptom) = toLower($symptom)
            RETURN i.incident_id, i.source_router, i.destination_router,
                   i.symptom, i.root_cause, i.remediation,
                   i.resolved, i.created_at
            ORDER BY i.resolved DESC, i.created_at DESC
            LIMIT $limit
            """,
            {
                "source_router": source_router,
                "destination_router": destination_router,
                "symptom": symptom,
                "limit": limit,
            },
        )

        fields = (
            "incident_id",
            "source_router",
            "destination_router",
            "symptom",
            "root_cause",
            "remediation",
            "resolved",
            "created_at",
        )
        return [
            dict(zip(fields, row))
            for row in result.result_set
        ]


    def resolve(self, incident_id: str) -> bool:
        """Mark an existing incident as resolved.

        Returns True if the incident exists, otherwise False.
        """
        result = self.graph.query(
            """
            MATCH (i:Incident {incident_id: $incident_id})
            SET i.resolved = true
            RETURN i.incident_id
            """,
            {"incident_id": incident_id},
        )
        return bool(result.result_set)
