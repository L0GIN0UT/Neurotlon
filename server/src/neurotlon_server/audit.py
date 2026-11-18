from typing import Any

from sqlalchemy.orm import Session

from neurotlon_server.models import AuditLog


def write_audit(
    db: Session,
    *,
    action: str,
    object_type: str,
    object_id: int | str,
    user_id: int | None,
    station_id: int | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
) -> None:
    """Callers must pass only non-secret fields (no passwords, hashes or tokens)."""
    db.add(
        AuditLog(
            user_id=user_id,
            station_id=station_id,
            action=action,
            object_type=object_type,
            object_id=str(object_id),
            before=before,
            after=after,
            reason=reason,
        )
    )
