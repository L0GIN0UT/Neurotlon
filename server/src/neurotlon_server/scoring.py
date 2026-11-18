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


@dataclass(frozen=True)
class ParticipantIn:
    id: int
    code: str
    display_name: str | None
    team_id: int | None


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
        for rows in per_person.get(person.id, []):
            if len(rows) > 1:  # conflict: counts as nothing until resolved
                conflicts += 1
                continue
            row = rows[0]
            points = scoring.score(row, by_code[row.discipline])
            total += points
            passed += row.outcome == "completed"
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
