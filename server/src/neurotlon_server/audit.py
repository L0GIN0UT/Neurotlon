from typing import Any

from sqlalchemy.orm import Session

from neurotlon_server.models import AuditLog


def write_audit(
    db: Session,
    *,
    action: str,
    object_type: str,
    object_id: int,
    user_id: int | None,
    after: dict[str, Any] | None = None,
) -> None:
    """Callers must pass only non-secret fields (no passwords, hashes or tokens)."""
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            object_type=object_type,
            object_id=str(object_id),
            after=after,
        )
    )
