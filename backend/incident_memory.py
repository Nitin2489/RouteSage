
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
    affected_source_interface: str = ""
    affected_destination_interface: str = ""

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

        if bool(self.affected_source_interface) != bool(self.affected_destination_interface):
            raise ValueError(
                "Both affected interface IDs are required when linking an incident to a link"
            )

    @property
    def affected_link_key(self) -> str:
        """Stable, direction-independent identity for an affected physical link."""
        if not self.affected_source_interface:
            return ""
        return "|".join(
            sorted((self.affected_source_interface, self.affected_destination_interface))
        )


class IncidentMemory:
    """Persists incidents and retrieves matching historical cases."""

    def __init__(self, repo: GraphRepository):
        self.graph = repo.graph

    def record(self, incident: Incident) -> dict:
        """Persist an incident, returning an existing active link incident when present.

        Link-associated incidents are idempotent on source/destination and the stable
        unordered interface pair. Legacy incidents without a link reference are kept
        as independent records rather than guessing identity from prose.
        """
        if incident.affected_link_key:
            existing = self.graph.query(
                """
                MATCH (i:Incident {affected_link_key: $affected_link_key})
                WHERE i.source_router = $source_router
                  AND i.destination_router = $destination_router
                  AND coalesce(i.resolved, false) = false
                RETURN i.incident_id
                LIMIT 1
                """,
                {
                    "affected_link_key": incident.affected_link_key,
                    "source_router": incident.source_router,
                    "destination_router": incident.destination_router,
                },
            )
            if existing.result_set:
                return {"incident_id": existing.result_set[0][0], "created": False}

        self.graph.query(
            """
            MERGE (i:Incident {incident_id: $incident_id})
            SET i.source_router = $source_router,
                i.destination_router = $destination_router,
                i.symptom = $symptom,
                i.root_cause = $root_cause,
                i.remediation = $remediation,
                i.resolved = $resolved,
                i.created_at = $created_at,
                i.affected_source_interface = $affected_source_interface,
                i.affected_destination_interface = $affected_destination_interface,
                i.affected_link_key = $affected_link_key
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
                "affected_source_interface": incident.affected_source_interface,
                "affected_destination_interface": incident.affected_destination_interface,
                "affected_link_key": incident.affected_link_key,
            },
        )
        return {"incident_id": incident.incident_id, "created": True}

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


    def resolve(
        self,
        incident_id: str,
        *,
        reason: str,
        verification_evidence: str,
        actor: str = "system",
    ) -> bool:
        """Mark an existing incident as resolved with an auditable outcome.

        Returns True if the incident exists, otherwise False.
        """
        resolved_at = datetime.now(timezone.utc).isoformat()
        result = self.graph.query(
            """
            MATCH (i:Incident {incident_id: $incident_id})
            WHERE coalesce(i.resolved, false) = false
            SET i.resolved = true,
                i.resolved_at = $resolved_at,
                i.updated_at = $resolved_at,
                i.resolution_reason = $reason,
                i.verification_evidence = $verification_evidence,
                i.resolved_by = $actor
            RETURN i.incident_id
            """,
            {
                "incident_id": incident_id,
                "resolved_at": resolved_at,
                "reason": reason,
                "verification_evidence": verification_evidence,
                "actor": actor,
            },
        )
        return bool(result.result_set)

    def open_incidents_for_link(self, affected_link_key: str) -> list[dict]:
        """Return only active incidents explicitly tied to the changed link."""
        result = self.graph.query(
            """
            MATCH (i:Incident {affected_link_key: $affected_link_key})
            WHERE coalesce(i.resolved, false) = false
            RETURN i.incident_id, i.source_router, i.destination_router
            """,
            {"affected_link_key": affected_link_key},
        )
        return [
            {"incident_id": row[0], "source_router": row[1], "destination_router": row[2]}
            for row in result.result_set
        ]

    def is_resolved(self, incident_id: str) -> bool:
        """Return whether an incident exists and has already been resolved."""
        result = self.graph.query(
            """
            MATCH (i:Incident {incident_id: $incident_id})
            RETURN coalesce(i.resolved, false)
            """,
            {"incident_id": incident_id},
        )
        return bool(result.result_set and result.result_set[0][0])
