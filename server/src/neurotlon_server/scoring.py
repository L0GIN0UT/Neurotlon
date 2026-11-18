"""Pure scoring: totals and ranking are always computed from section results (decision 13)."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Protocol

COUNTED_STATUSES = frozenset({"confirmed", "locked"})
SECTIONS = ("bci", "physical")
PRECISION = 6  # float sums: 0.1 + 0.2 and 0.3 must rank equal


@dataclass(frozen=True)
class ResultIn:
    id: int
    participant_id: int
    discipline: str
    section: str
    outcome: str
    points: float | None
    wins: int | None
    status: str
    voided: bool = False
    session_id: str = ""


@dataclass(frozen=True)
class ParticipantIn:
    id: int
    code: str
    display_name: str | None
    team_id: int | None
    number_in_team: int | None = None


@dataclass(frozen=True)
class TeamIn:
    id: int
    number: int
    name: str
    color: str


@dataclass(frozen=True)
class DisciplineIn:
    code: str
    win_points: int


@dataclass(frozen=True)
class ParticipantScore:
    participant_id: int
    total: float = 0.0
    bci_points: float = 0.0
    physical_points: float = 0.0
    sections_passed: int = 0
    conflicts: int = 0
    by_discipline: dict[str, float] = field(default_factory=dict)
    by_section: dict[tuple[str, str], float] = field(default_factory=dict)
    passed_by_discipline: dict[str, int] = field(default_factory=dict)
    conflicts_by_discipline: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class TopEntry:
    """One line of a discipline's top list on the scoreboard."""

    rank: int
    participant_id: int
    number: int
    points: float
    sections_passed: int
    pending: bool


@dataclass(frozen=True)
class TeamScore:
    team_id: int
    rank: int
    total: float
    sections_passed: int
    bci_points: float
    physical_points: float
    by_discipline: dict[str, float]
    finished: bool
    members: list[ParticipantScore]


def group_live(results: Iterable[ResultIn]) -> dict[tuple[int, str, str], list[ResultIn]]:
    """Non-voided confirmed/locked results per (participant, discipline, section)."""
    groups: dict[tuple[int, str, str], list[ResultIn]] = defaultdict(list)
    for result in results:
        if not result.voided and result.status in COUNTED_STATUSES:
            groups[(result.participant_id, result.discipline, result.section)].append(result)
    return groups


def duel_score(
    results: Iterable[ResultIn], participants: Iterable[ParticipantIn]
) -> dict[int, int]:
    """Pong matches won per team id (1 match = 1 point for the winner's team).

    A match is one pong session: two counted results, both completed, exactly one with wins=1.
    A session where either player's section is in a conflict, or whose rows are voided or not
    yet confirmed, is not a match yet. Independent of the points scoring.
    """
    team_of = {p.id: p.team_id for p in participants}
    sessions: dict[str, list[ResultIn]] = defaultdict(list)
    for rows in group_live(results).values():
        if len(rows) == 1 and rows[0].discipline == "pong":
            sessions[rows[0].session_id].append(rows[0])
    score: dict[int, int] = {team_id: 0 for team_id in team_of.values() if team_id is not None}
    for rows in sessions.values():
        if len(rows) != 2 or any(r.outcome != "completed" for r in rows):
            continue
        winners = [r for r in rows if r.wins == 1]
        if len(winners) != 1 or sum(r.wins or 0 for r in rows) != 1:
            continue
        team_id = team_of.get(winners[0].participant_id)
        if team_id is not None:
            score[team_id] += 1
    return score


TOP_LIMIT = 5


def top_players(
    members: Iterable[ParticipantScore],
    numbers: dict[int, int],
    discipline: str,
    limit: int = TOP_LIMIT,
) -> list[TopEntry]:
    """Best players of one team in one discipline (physical + BCI points).

    Order: points desc, sections passed in the discipline desc, number in team asc. Players with
    no counted result are left out, except those whose section is in a conflict: they are marked
    pending and listed first, so the judge's open question is never cut off.
    """
    rows = [
        (m, m.by_discipline.get(discipline, 0.0), m.passed_by_discipline.get(discipline, 0))
        for m in members
        if discipline in m.by_discipline or m.conflicts_by_discipline.get(discipline)
    ]
    rows.sort(
        key=lambda r: (
            not r[0].conflicts_by_discipline.get(discipline),  # undecided players stay visible
            -r[1],
            -r[2],
            numbers.get(r[0].participant_id, 0),
        )
    )
    return [
        TopEntry(
            rank=i,
            participant_id=m.participant_id,
            number=numbers.get(m.participant_id, 0),
            points=points,
            sections_passed=passed,
            pending=bool(m.conflicts_by_discipline.get(discipline)),
        )
        for i, (m, points, passed) in enumerate(rows[:limit], start=1)
    ]


class SectionScoring(Protocol):
    """Points for one counted section result."""

    def score(self, result: ResultIn, discipline: DisciplineIn) -> float: ...


class PlaceholderScoring:
    """Заглушка до утверждения методики подсчёта очков (решение 14).

    Заменяется реализацией SectionScoring без изменения остального расчёта.
    """

    def score(self, result: ResultIn, discipline: DisciplineIn) -> float:
        if result.outcome != "completed":
            return 0.0
        if discipline.code == "pong":
            return float((result.wins or 0) * discipline.win_points)
        return float(result.points or 0.0)


def score_participants(
    results: Iterable[ResultIn],
    participants: Iterable[ParticipantIn],
    disciplines: Iterable[DisciplineIn],
    scoring: SectionScoring,
) -> dict[int, ParticipantScore]:
    by_code = {d.code: d for d in disciplines}
    per_person: dict[int, list[list[ResultIn]]] = defaultdict(list)
    for (participant_id, _, _), rows in group_live(results).items():
        per_person[participant_id].append(rows)

    scores: dict[int, ParticipantScore] = {}
    for person in participants:
        total = bci = physical = 0.0
        passed = conflicts = 0
        by_discipline: dict[str, float] = {}
        by_section: dict[tuple[str, str], float] = {}
        passed_by: dict[str, int] = {}
        conflicts_by: dict[str, int] = {}
        for rows in per_person.get(person.id, []):
            if len(rows) > 1:  # conflict: counts as nothing until resolved
                conflicts += 1
                conflicts_by[rows[0].discipline] = conflicts_by.get(rows[0].discipline, 0) + 1
                continue
            row = rows[0]
            points = scoring.score(row, by_code[row.discipline])
            total += points
            passed += row.outcome == "completed"
            passed_by[row.discipline] = passed_by.get(row.discipline, 0) + (
                row.outcome == "completed"
            )
            if row.section == "bci":
                bci += points
            else:
                physical += points
            by_discipline[row.discipline] = by_discipline.get(row.discipline, 0.0) + points
            by_section[(row.discipline, row.section)] = points
        scores[person.id] = ParticipantScore(
            person.id,
            round(total, PRECISION),
            round(bci, PRECISION),
            round(physical, PRECISION),
            passed,
            conflicts,
            {code: round(points, PRECISION) for code, points in by_discipline.items()},
            {key: round(points, PRECISION) for key, points in by_section.items()},
            passed_by,
            conflicts_by,
        )
    return scores


def _sort_key(team: TeamScore) -> tuple[float, int, float, float]:
    return (team.total, team.sections_passed, team.bci_points, team.physical_points)


def score_teams(
    results: Iterable[ResultIn],
    participants: Iterable[ParticipantIn],
    teams: Iterable[TeamIn],
    disciplines: Iterable[DisciplineIn],
    scoring: SectionScoring,
) -> list[tuple[TeamIn, TeamScore]]:
    """Teams in rank order (ties share a rank, then by team number)."""
    people = list(participants)
    discipline_list = list(disciplines)
    scores = score_participants(results, people, discipline_list, scoring)
    sections_needed = len(discipline_list) * len(SECTIONS)
    members: dict[int, list[ParticipantScore]] = defaultdict(list)
    for person in sorted(people, key=lambda p: p.code):
        if person.team_id is not None:
            members[person.team_id].append(scores[person.id])

    unranked: list[tuple[TeamIn, TeamScore]] = []
    for team in teams:
        group = members.get(team.id, [])
        by_discipline: dict[str, float] = {d.code: 0.0 for d in discipline_list}
        for member in group:
            for code, points in member.by_discipline.items():
                by_discipline[code] = round(by_discipline.get(code, 0.0) + points, PRECISION)
        score = TeamScore(
            team_id=team.id,
            rank=0,
            total=round(sum(m.total for m in group), PRECISION),
            sections_passed=sum(m.sections_passed for m in group),
            bci_points=round(sum(m.bci_points for m in group), PRECISION),
            physical_points=round(sum(m.physical_points for m in group), PRECISION),
            by_discipline=by_discipline,
            finished=bool(group) and all(m.sections_passed == sections_needed for m in group),
            members=group,
        )
        unranked.append((team, score))

    keys = [_sort_key(score) for _, score in unranked]
    ranked = [
        (team, replace(score, rank=1 + sum(1 for key in keys if key > _sort_key(score))))
        for team, score in unranked
    ]
    ranked.sort(key=lambda item: (item[1].rank, item[0].number))
    return ranked
