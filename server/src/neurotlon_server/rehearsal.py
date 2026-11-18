"""Rehearsal: drives a RUNNING Neurotlon server through a whole event and prints PASS / FAIL.

It uses only the public HTTP API, like the real clients do: a superuser logs in, creates the
accounts and stations, 20 participants are generated and checked in, the draw runs, then every
pair "plays" all three disciplines (BCI results from station tokens, physical results from
volunteers). It also provokes the awkward cases: a replayed result, an offline duplicate that
becomes a conflict, an undo and a correction request. Finally it checks the scoreboard stream,
resolves the conflict as the judge, locks the results and downloads the XLSX.

Everything it creates is prefixed `rehearsal-` / `Rehearsal`, and it refuses to run on a
database that already has participants. `--reset` wipes only a database that holds nothing but
rehearsal data (the server must be stopped).
"""

import argparse
import getpass
import http.client
import json
import os
import secrets
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

PREFIX = "rehearsal-"
NAME_PREFIX = "Rehearsal "
PASSWORD_ENV = "NEUROTLON_REHEARSAL_PASSWORD"
SSE_DEADLINE_S = 10.0
DISCIPLINES = ("darts", "football", "pong")
API = "/api/v1"


class Abort(Exception):
    """A step failed so badly that the rest of the rehearsal makes no sense."""


@dataclass
class Reply:
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        return json.loads(self.body)


class Http:
    """Minimal HTTP client: cookies, JSON, optional local CA, SSE. Standard library only."""

    def __init__(
        self,
        base_url: str,
        ca_file: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.cookies: dict[str, str] = {}
        self._context: ssl.SSLContext | None = None
        if self.base_url.startswith("https://"):
            self._context = ssl.create_default_context(cafile=ca_file)

    def _prepare(
        self, method: str, path: str, data: bytes | None, headers: dict[str, str] | None
    ) -> urllib.request.Request:
        request = urllib.request.Request(self.base_url + path, data=data, method=method)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if self.cookies:
            request.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in self.cookies.items()))
        return request

    def _remember(self, headers: http.client.HTTPMessage) -> None:
        # The session cookie is `Secure`; the real server is always reached over HTTPS, and a
        # test server on plain HTTP still has to work, so the flag is deliberately ignored.
        for line in headers.get_all("Set-Cookie") or []:
            pair = line.split(";", 1)[0]
            name, _, value = pair.partition("=")
            if value:
                self.cookies[name.strip()] = value.strip()
            else:
                self.cookies.pop(name.strip(), None)

    def request(
        self,
        method: str,
        path: str,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Reply:
        data = None if json_body is None else json.dumps(json_body).encode()
        request = self._prepare(method, path, data, headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=self._context) as r:
                self._remember(r.headers)
                return Reply(r.status, r.read(), dict(r.headers.items()))
        except urllib.error.HTTPError as exc:
            return Reply(exc.code, exc.read(), dict(exc.headers.items()))

    def get(self, path: str, headers: dict[str, str] | None = None) -> Reply:
        return self.request("GET", path, headers=headers)

    def post(self, path: str, body: Any = None, headers: dict[str, str] | None = None) -> Reply:
        return self.request("POST", path, body, headers)

    def patch(self, path: str, body: Any) -> Reply:
        return self.request("PATCH", path, body)

    def open_stream(self, path: str) -> http.client.HTTPResponse:
        request = self._prepare("GET", path, None, {"Accept": "text/event-stream"})
        response: http.client.HTTPResponse = urllib.request.urlopen(
            request, timeout=60, context=self._context
        )
        return response


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    out: Callable[[str], None] = print

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append(Check(name, ok, detail))
        suffix = f": {detail}" if detail and not ok else ""
        self.out(f"{'PASS' if ok else 'FAIL'}  {name}{suffix}")
        return ok

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    def summary(self) -> str:
        good = sum(c.ok for c in self.checks)
        return f"RESULT: {'PASS' if self.passed else 'FAIL'} ({good}/{len(self.checks)} checks)"


class ScoreboardWatcher:
    """Reads the SSE scoreboard stream in a thread and remembers every event."""

    def __init__(self, client: Http) -> None:
        self._http = client
        self._cond = threading.Condition()
        self.events: list[tuple[float, dict[str, Any]]] = []
        self.error: str | None = None
        self._response: http.client.HTTPResponse | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()
        self.wait_for(lambda _: True, 10.0)  # the first event comes right away

    def _run(self) -> None:
        try:
            self._response = self._http.open_stream(f"{API}/scoreboard/stream")
            name, data = "", ""
            for raw in self._response:
                line = raw.decode().rstrip("\r\n")
                if line.startswith("event:"):
                    name = line[6:].strip()
                elif line.startswith("data:"):
                    data = line[5:].strip()
                elif line == "" and name == "scoreboard" and data:
                    with self._cond:
                        self.events.append((time.monotonic(), json.loads(data)))
                        self._cond.notify_all()
                    name, data = "", ""
        except (OSError, ValueError, AttributeError, http.client.HTTPException) as exc:
            self.error = str(exc)
        finally:
            with self._cond:
                self._cond.notify_all()

    def wait_for(self, predicate: Callable[[dict[str, Any]], bool], timeout: float) -> float | None:
        """Seconds until an event satisfying `predicate` is seen (events already seen count)."""
        start = time.monotonic()
        deadline = start + timeout
        with self._cond:
            while True:
                for _, payload in self.events:
                    if predicate(payload):
                        return time.monotonic() - start
                left = deadline - time.monotonic()
                if left <= 0 or self.error:
                    return None
                self._cond.wait(min(left, 0.25))

    def close(self) -> None:
        if self._response is not None:
            self._response.close()


def _call(reply: Reply, expected: int | tuple[int, ...], what: str) -> Reply:
    allowed = (expected,) if isinstance(expected, int) else expected
    if reply.status not in allowed:
        raise Abort(f"{what}: HTTP {reply.status} {reply.body[:200]!r}")
    return reply


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _login(http: Http, login: str, password: str) -> Http:
    _call(http.post(f"{API}/auth/login", {"login": login, "password": password}), 204, login)
    return http


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class _Actors:
    admin: Http
    judge: Http
    volunteers: dict[str, Http]
    tokens: dict[str, str]


class Rehearsal:
    def __init__(
        self,
        make_http: Callable[[], Http],
        login: str,
        password: str,
        report: Report,
        xlsx_out: Path | None = None,
    ) -> None:
        self.make_http = make_http
        self.login = login
        self.password = password
        self.report = report
        self.xlsx_out = xlsx_out
        self.rng = secrets.SystemRandom()
        self.sessions: dict[tuple[str, str, str], str] = {}  # (code, discipline, section) -> id

    # --- setup -----------------------------------------------------------------------------

    def _setup_accounts(self, su: Http) -> _Actors:
        if _call(su.get(f"{API}/participants"), 200, "participants").json():
            raise Abort("the database already has participants: use a fresh database")
        if _call(su.get(f"{API}/stations"), 200, "stations").json():
            raise Abort("the database already has stations: use a fresh database")
        passwords: dict[str, str] = {}

        def create(login: str, role: str, discipline: str | None = None) -> None:
            passwords[login] = secrets.token_urlsafe(12)
            body: dict[str, Any] = {"login": login, "password": passwords[login], "role": role}
            if discipline:
                body["discipline"] = discipline
            _call(su.post(f"{API}/users", body), 201, f"create {login}")

        create(f"{PREFIX}admin", "admin")
        create(f"{PREFIX}judge", "judge")
        for d in DISCIPLINES:
            create(f"{PREFIX}vol-{d}", "volunteer", d)
        tokens: dict[str, str] = {}
        for d in DISCIPLINES:
            reply = _call(
                su.post(f"{API}/stations", {"name": f"{PREFIX}{d}", "discipline": d}),
                201,
                f"create station {d}",
            )
            tokens[d] = reply.json()["token"]
        actors = _Actors(
            admin=_login(self.make_http(), f"{PREFIX}admin", passwords[f"{PREFIX}admin"]),
            judge=_login(self.make_http(), f"{PREFIX}judge", passwords[f"{PREFIX}judge"]),
            volunteers={
                d: _login(self.make_http(), f"{PREFIX}vol-{d}", passwords[f"{PREFIX}vol-{d}"])
                for d in DISCIPLINES
            },
            tokens=tokens,
        )
        self.report.check("accounts: admin, judge, 3 volunteers, 3 stations created", True)
        for d in DISCIPLINES:
            reply = actors.volunteers[d].get(f"{API}/auth/me")
            self.report.check(f"volunteer {d} signs in", reply.status == 200, str(reply.status))
        return actors

    def _setup_event(self, admin: Http) -> list[tuple[str, str]]:
        generated = _call(admin.post(f"{API}/participants/generate", {"count": 20}), 200, "gen")
        self.report.check("20 participants generated", generated.json()["total"] == 20)
        for n in range(1, 21):
            code = f"NT{n:02d}"
            body = {
                "category": "ovz" if n <= 10 else "general",
                "display_name": f"{NAME_PREFIX}{n}",
            }
            _call(admin.post(f"{API}/participants/{code}/check-in", body), 200, f"check-in {code}")
        listing = _call(admin.get(f"{API}/participants"), 200, "participants").json()
        self.report.check("10 + 10 checked in", sum(p["checked_in"] for p in listing) == 20)
        options = _call(admin.get(f"{API}/draw/options"), 200, "draw options").json()
        usable = [o for o in options if o["m"] == 5 and o["team_count"] == 2]
        if not usable:
            raise Abort(f"no draw option with m=5 and 2 teams: {options}")
        drawn = _call(admin.post(f"{API}/draw", {"m": 5, "seed": 2027}), 200, "draw").json()
        self.report.check("draw made 2 teams", drawn["team_count"] == 2, str(drawn))
        layout = _call(admin.get(f"{API}/teams"), 200, "teams").json()
        pairs = [(p["a"], p["b"]) for duel in layout["duels"] for p in duel["pairs"]]
        self.report.check("pairs formed (at least 6)", len(pairs) >= 6, f"{len(pairs)} pairs")
        return pairs

    # --- results ---------------------------------------------------------------------------

    def _entry(self, code: str, wins: int | None = None) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "participant_code": code,
            "outcome": "completed",
            "points": round(self.rng.uniform(5, 60), 1),
        }
        if wins is not None:
            entry["wins"] = wins
        return entry

    def _body(self, discipline: str, section: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "session_id": str(uuid.uuid4()),
            "discipline": discipline,
            "section": section,
            "finished_at": _now(),
            "entries": entries,
        }

    def _entries(self, discipline: str, codes: tuple[str, ...]) -> list[dict[str, Any]]:
        if discipline == "pong":
            return [self._entry(codes[0], wins=1), self._entry(codes[1], wins=0)]
        return [self._entry(codes[0])]

    def _bci(self, actors: _Actors, discipline: str, codes: tuple[str, ...]) -> dict[str, Any]:
        station = self.make_http()
        auth = _bearer(actors.tokens[discipline])
        body = self._body(discipline, "bci", self._entries(discipline, codes))
        _call(
            station.post(
                f"{API}/sessions",
                {
                    "session_id": body["session_id"],
                    "discipline": discipline,
                    "participant_codes": list(codes),
                },
                auth,
            ),
            (200, 201),
            f"open {discipline} session",
        )
        _call(station.post(f"{API}/results", body, auth), 201, f"{discipline} BCI result")
        return body

    def _physical(self, volunteer: Http, discipline: str, codes: tuple[str, ...]) -> dict[str, Any]:
        body = self._body(discipline, "physical", self._entries(discipline, codes))
        _call(volunteer.post(f"{API}/results", body), 201, f"{discipline} physical result")
        return body

    def _play(self, actors: _Actors, pairs: list[tuple[str, str]]) -> dict[str, Any]:
        """Everyone plays everything. Returns the sessions needed for the special cases."""
        special: dict[str, Any] = {}
        for i, (a, b) in enumerate(pairs):
            for discipline in DISCIPLINES:
                volunteer = actors.volunteers[discipline]
                groups = [(a, b)] if discipline == "pong" else [(a,), (b,)]
                for codes in groups:
                    bci = self._bci(actors, discipline, codes)
                    if i == 0 and discipline == "darts" and codes == (a,):
                        special["bci"] = bci
                    if i == 1 and discipline == "football" and codes == (a,):
                        wrong = self._physical(volunteer, discipline, codes)
                        undone = volunteer.post(f"{API}/results/{wrong['session_id']}/undo")
                        self.report.check(
                            "undo within 30 s", undone.status == 204, str(undone.status)
                        )
                    physical = self._physical(volunteer, discipline, codes)
                    if i == 2 and discipline == "darts" and codes == (a,):
                        special["correction"] = physical
        self.report.check(f"{len(pairs)} pairs played darts, football and pong", True)
        return special

    def _edge_cases(self, actors: _Actors, special: dict[str, Any]) -> None:
        # Replay of a stored result is idempotent; the same id with other data is refused.
        bci = special["bci"]
        station = self.make_http()
        auth = _bearer(actors.tokens["darts"])
        replay = station.post(f"{API}/results", bci, auth)
        self.report.check(
            "replay of a session is accepted without a duplicate", replay.status == 200
        )
        changed = dict(bci, entries=[dict(bci["entries"][0], points=999)])
        clash = station.post(f"{API}/results", changed, auth)
        self.report.check("same session_id with other data is refused", clash.status == 409)

        # Offline duplicate: the same person plays darts again under a new session id.
        code = bci["entries"][0]["participant_code"]
        duplicate = self._body("darts", "bci", [self._entry(code)])
        got = station.post(f"{API}/results", duplicate, auth)
        self.report.check("offline duplicate is stored (never dropped)", got.status == 201)
        listing = _call(actors.judge.get(f"{API}/conflicts"), 200, "conflicts").json()
        found = [c for c in listing if c["participant_code"] == code]
        self.report.check("duplicate shows up as a conflict", len(found) == 1, str(listing))
        board = self.make_http().get(f"{API}/scoreboard").json()
        pending = [m for t in board["teams"] for m in t["members"] if m["pending"]]
        self.report.check("scoreboard marks the conflict as pending", len(pending) == 1)
        special["conflict"] = found[0] if found else None

    def _judge(self, actors: _Actors, special: dict[str, Any], watcher: ScoreboardWatcher) -> None:
        judge = actors.judge
        conflict = special["conflict"]
        if conflict is not None:
            keep = conflict["results"][0]["id"]
            resolved = judge.post(
                f"{API}/conflicts/resolve", {"keep_result_id": keep, "reason": "rehearsal"}
            )
            self.report.check("judge resolves the conflict", resolved.status == 200)
        left = _call(judge.get(f"{API}/conflicts"), 200, "conflicts").json()
        self.report.check("no conflicts left", left == [], str(left))

        corr = special["correction"]
        volunteer = actors.volunteers["darts"]
        asked = volunteer.post(
            f"{API}/corrections", {"session_id": corr["session_id"], "comment": "wrong score"}
        )
        self.report.check("volunteer asks for a correction", asked.status == 201, str(asked.status))
        pending = _call(judge.get(f"{API}/corrections"), 200, "corrections").json()
        self.report.check("judge sees the open request", len(pending) == 1, str(pending))
        rows = _call(
            judge.get(f"{API}/results?session_id={corr['session_id']}"), 200, "results"
        ).json()["items"]

        started = time.monotonic()
        if rows and pending:
            fixed = judge.patch(
                f"{API}/results/{rows[0]['id']}", {"points": 55, "change_reason": "rehearsal"}
            )
            self.report.check("judge corrects the result", fixed.status == 200, str(fixed.status))
            done = judge.post(f"{API}/corrections/{pending[0]['id']}/done")
            self.report.check("request marked done", done.status == 200, str(done.status))

        expected = _call(self.make_http().get(f"{API}/scoreboard"), 200, "scoreboard").json()
        seen = watcher.wait_for(lambda p: p == expected, SSE_DEADLINE_S)
        elapsed = None if seen is None else time.monotonic() - started
        self.report.check(
            f"scoreboard stream delivered the change within {SSE_DEADLINE_S:.0f} s",
            seen is not None,
            watcher.error or "no matching event",
        )
        if elapsed is not None:
            self.report.out(f"      (seen after {elapsed:.1f} s, {len(watcher.events)} events)")

    def _finish(self, actors: _Actors) -> None:
        judge = actors.judge
        board = _call(self.make_http().get(f"{API}/scoreboard"), 200, "scoreboard")
        data = board.json()
        self.report.check("scoreboard has 2 teams", len(data["teams"]) == 2)
        self.report.check(
            "both teams passed every section", all(t["finished"] for t in data["teams"])
        )
        text = board.body.decode()
        self.report.check(
            "scoreboard hides the category", "ovz" not in text and "general" not in text
        )

        locked = judge.post(f"{API}/results/lock", {})
        self.report.check(
            "judge locks the results",
            locked.status == 200 and locked.json()["locked"] > 0,
            f"{locked.status} {locked.body[:120]!r}",
        )
        again = judge.post(f"{API}/results/lock", {})
        self.report.check(
            "second lock changes nothing", again.status == 200 and again.json()["locked"] == 0
        )
        rows = _call(judge.get(f"{API}/results?limit=1000"), 200, "results").json()["items"]
        live = [r for r in rows if not r["voided"]]
        self.report.check("every live result is locked", all(r["status"] == "locked" for r in live))
        after = _call(self.make_http().get(f"{API}/scoreboard"), 200, "scoreboard").json()
        self.report.check("locking does not change the scoreboard", after == data)

        export = actors.admin.get(f"{API}/export.xlsx")
        ok = export.status == 200 and export.body[:2] == b"PK"
        names: list[str] = []
        if ok:
            from openpyxl import load_workbook

            names = load_workbook(BytesIO(export.body)).sheetnames
            ok = names == ["Итоги", "Участники"]
            if self.xlsx_out is not None:
                self.xlsx_out.write_bytes(export.body)
        self.report.check("XLSX export downloads with both sheets", ok, f"{export.status} {names}")

    # --- entry point -----------------------------------------------------------------------

    def run(self) -> Report:
        watcher: ScoreboardWatcher | None = None
        try:
            su = _login(self.make_http(), self.login, self.password)
            self.report.check("superuser signs in", True)
            actors = self._setup_accounts(su)
            pairs = self._setup_event(actors.admin)
            watcher = ScoreboardWatcher(self.make_http())
            watcher.start()
            self.report.check("scoreboard stream opens", bool(watcher.events), watcher.error or "")
            special = self._play(actors, pairs)
            self._edge_cases(actors, special)
            self._judge(actors, special, watcher)
            self._finish(actors)
        except Abort as exc:
            self.report.check("rehearsal could continue", False, str(exc))
        except OSError as exc:
            self.report.check("server is reachable", False, str(exc))
        finally:
            if watcher is not None:
                watcher.close()
        return self.report


# --- reset ---------------------------------------------------------------------------------


def reset_database(db: Path) -> None:
    """Delete and recreate a database that holds only rehearsal data. Server must be stopped."""
    import sqlite3
    from contextlib import closing

    from alembic import command
    from alembic.config import Config

    from neurotlon_server.backup import BackupError, _ensure_not_in_use

    if db.exists():
        _ensure_not_in_use(db)
        with closing(sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)) as conn:
            foreign = [
                (
                    "user",
                    "SELECT count(*) FROM user WHERE role != 'superuser' AND login NOT LIKE ?",
                ),
                ("station", "SELECT count(*) FROM station WHERE name NOT LIKE ?"),
            ]
            for what, query in foreign:
                like = PREFIX + "%"
                if conn.execute(query, (like,)).fetchone()[0]:
                    raise BackupError(f"refusing to reset: the database has non-rehearsal {what}s")
            real = conn.execute(
                "SELECT count(*) FROM participant "
                "WHERE display_name IS NOT NULL AND display_name NOT LIKE ?",
                (NAME_PREFIX + "%",),
            ).fetchone()[0]
            if real:
                raise BackupError("refusing to reset: the database has non-rehearsal participants")
        for suffix in ("", "-wal", "-shm"):
            Path(str(db) + suffix).unlink(missing_ok=True)
    ini = os.environ.get("NEUROTLON_ALEMBIC_INI") or str(
        Path(__file__).resolve().parents[2] / "alembic.ini"
    )
    config = Config(ini)
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    command.upgrade(config, "head")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="neurotlon-rehearsal", description=__doc__)
    parser.add_argument("--base-url", default="https://localhost", help="server address")
    parser.add_argument("--login", default="root", help="superuser login")
    parser.add_argument("--ca-file", help="local root certificate (rootCA.pem)")
    parser.add_argument("--xlsx-out", type=Path, help="where to save the downloaded XLSX")
    parser.add_argument("--reset", action="store_true", help="wipe a rehearsal-only DB and exit")
    parser.add_argument("--db", type=Path, help="SQLite file for --reset")
    args = parser.parse_args(argv)

    if args.reset:
        from neurotlon_server.backup import BackupError

        if args.db is None:
            parser.error("--reset needs --db")
        try:
            reset_database(args.db)
        except BackupError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"Database {args.db} is reset. Create the superuser again.")
        return 0

    password = os.environ.get(PASSWORD_ENV) or getpass.getpass("Superuser password: ")
    report = Report()
    rehearsal = Rehearsal(
        lambda: Http(args.base_url, args.ca_file),
        args.login,
        password,
        report,
        args.xlsx_out,
    )
    rehearsal.run()
    print(report.summary())
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
