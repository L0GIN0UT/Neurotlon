import threading
from collections import deque
from datetime import datetime, timedelta

GRANT_TTL = timedelta(seconds=120)
RATE_WINDOW = timedelta(seconds=60)
MAX_PHOTOS_PER_WINDOW = 20


class PhotoAccess:
    """Who may fetch a photo: a station only for a participant it has just checked.

    A stolen station token then cannot walk through all codes: a photo is served only after
    the same station asked `eligibility` for that code within `GRANT_TTL`, and at most
    `MAX_PHOTOS_PER_WINDOW` requests per station and minute are counted. Kept in memory
    (single-process server), the clock comes from the caller.
    """

    MAX_GRANTS = 4096
    MAX_STATIONS = 256

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._grants: dict[tuple[int, str], datetime] = {}
        self._hits: dict[int, deque[datetime]] = {}

    def grant(self, station_id: int, code: str, now: datetime) -> None:
        with self._lock:
            self._grants = {k: t for k, t in self._grants.items() if t > now}
            self._grants.pop((station_id, code), None)  # re-insert keeps the order by age
            self._grants[(station_id, code)] = now + GRANT_TTL
            while len(self._grants) > self.MAX_GRANTS:
                del self._grants[next(iter(self._grants))]

    def allowed(self, station_id: int, code: str, now: datetime) -> bool:
        with self._lock:
            expires = self._grants.get((station_id, code))
            return expires is not None and expires > now

    def try_request(self, station_id: int, now: datetime) -> bool:
        """Count a photo request; False when the station is over its per-minute limit."""
        with self._lock:
            self._hits = {
                sid: hits
                for sid, hits in self._hits.items()
                if hits and now - hits[-1] < RATE_WINDOW
            }
            hits = self._hits.setdefault(station_id, deque())
            while hits and now - hits[0] >= RATE_WINDOW:
                hits.popleft()
            if len(hits) >= MAX_PHOTOS_PER_WINDOW:
                return False
            hits.append(now)
            while len(self._hits) > self.MAX_STATIONS:
                del self._hits[next(iter(self._hits))]
            return True
