from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from neurotlon_server.audit import write_audit
from neurotlon_server.models import User
from neurotlon_server.security import hash_password


class LoginTakenError(Exception):
    pass


def normalize_login(login: str) -> str:
    return login.strip().lower()


def _login_exists(db: Session, login: str) -> bool:
    return db.scalar(select(User.id).where(User.login == login)) is not None


def create_user(
    db: Session,
    *,
    login: str,
    password: str,
    role: str,
    discipline: str | None,
    actor_id: int | None,
) -> User:
    login = normalize_login(login)
    if _login_exists(db, login):
        raise LoginTakenError(login)
    user = User(
        login=login, password_hash=hash_password(password), role=role, discipline=discipline
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:  # lost a race against a concurrent create
        db.rollback()
        raise LoginTakenError(login) from None
    write_audit(
        db,
        action="user.create",
        object_type="user",
        object_id=user.id,
        user_id=actor_id,
        after={"login": login, "role": role, "discipline": discipline},
    )
    db.commit()
    return user
