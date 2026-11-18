from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Cookie, Depends, Header

from neurotlon_server.auth import (
    COOKIE_NAME,
    Db,
    Now,
    current_station,
    current_user,
    current_web_session,
)
from neurotlon_server.errors import ProblemError, forbidden


@dataclass(frozen=True)
class Caller:
    """Who calls the station API: a station (section bci) or a volunteer (physical)."""

    kind: Literal["station", "volunteer"]
    discipline: str
    section: Literal["bci", "physical"]
    station_id: int | None = None
    user_id: int | None = None

    def check(self, discipline: str, section: str | None = None) -> None:
        if discipline != self.discipline or (section is not None and section != self.section):
            raise ProblemError(
                403, "wrong_discipline", "Wrong discipline", "Not your discipline or section"
            )


def current_caller(
    db: Db,
    now: Now,
    authorization: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> Caller:
    if authorization:
        station = current_station(db, authorization)
        return Caller("station", station.discipline, "bci", station_id=station.id)
    user = current_user(db, current_web_session(db, now, token))
    if user.role != "volunteer" or user.discipline is None:
        raise forbidden()
    return Caller("volunteer", user.discipline, "physical", user_id=user.id)


def station_caller(caller: Annotated[Caller, Depends(current_caller)]) -> Caller:
    if caller.kind != "station":
        raise forbidden()
    return caller


Anyone = Annotated[Caller, Depends(current_caller)]
StationOnly = Annotated[Caller, Depends(station_caller)]
