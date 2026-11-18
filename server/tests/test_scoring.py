from neurotlon_server.scoring import (
    DisciplineIn,
    ParticipantIn,
    ParticipantScore,
    PlaceholderScoring,
    ResultIn,
    TeamIn,
    duel_score,
    score_participants,
    score_teams,
    top_players,
)

DISCIPLINES = [DisciplineIn("darts", 10), DisciplineIn("football", 10), DisciplineIn("pong", 10)]


def res(
    id: int,
    participant: int = 1,
    discipline: str = "darts",
    section: str = "bci",
    outcome: str = "completed",
    points: int | None = 0,
    wins: int | None = None,
    status: str = "confirmed",
    voided: bool = False,
    session: str = "",
) -> ResultIn:
    return ResultIn(
        id, participant, discipline, section, outcome, points, wins, status, voided, session
    )


def person(id: int, team: int | None = 1) -> ParticipantIn:
    return ParticipantIn(id, f"NT{id:02d}", None, team)


class FakeScoring:
    """Independent of the placeholder rule: a section is worth its `points` field."""

    def score(self, result: ResultIn, discipline: DisciplineIn) -> int:
        return result.points or 0


FAKE = FakeScoring()


def score_one(*results: ResultIn) -> ParticipantScore:
    return score_participants(results, [person(1)], DISCIPLINES, FAKE)[1]


def test_darts_and_football_use_points() -> None:
    score = score_one(
        res(1, points=42), res(2, discipline="football", section="physical", points=7)
    )
    assert score.total == 49
    assert (score.bci_points, score.physical_points, score.sections_passed) == (42, 7, 2)
    assert score.by_discipline == {"darts": 42, "football": 7}


def test_placeholder_pong_is_wins_times_win_points_and_ignores_points() -> None:
    scoring = PlaceholderScoring()
    pong = DisciplineIn("pong", 25)
    assert scoring.score(res(1, discipline="pong", points=99, wins=1), pong) == 25
    assert scoring.score(res(2, discipline="pong", points=99, wins=0), pong) == 0
    assert scoring.score(res(3, discipline="pong", points=99, wins=None), pong) == 0


def test_placeholder_darts_football_points_and_not_completed() -> None:
    scoring = PlaceholderScoring()
    assert scoring.score(res(1, points=42), DisciplineIn("darts", 10)) == 42
    assert scoring.score(res(2, discipline="football", points=7), DISCIPLINES[1]) == 7
    skipped = res(3, outcome="not_completed", points=None)
    assert scoring.score(skipped, DISCIPLINES[0]) == 0


def test_not_completed_is_zero_and_not_passed() -> None:
    score = score_one(
        res(1, outcome="not_completed", points=None), res(2, section="physical", points=5)
    )
    assert (score.total, score.sections_passed) == (5, 1)


def test_conflict_counts_nothing() -> None:
    score = score_one(res(1, points=10), res(2, points=20), res(3, section="physical", points=3))
    assert (score.total, score.sections_passed, score.conflicts) == (3, 1, 1)


def test_voided_and_entered_are_ignored() -> None:
    score = score_one(
        res(1, points=10, voided=True),
        res(2, points=20),
        res(3, section="physical", points=3, status="entered"),
    )
    assert (score.total, score.conflicts, score.sections_passed) == (20, 0, 1)


def test_locked_counts() -> None:
    assert score_one(res(1, points=8, status="locked")).total == 8


def _teams(*numbers: int) -> list[TeamIn]:
    return [TeamIn(n, n, f"T{n}", "#000000") for n in numbers]


def _rank(
    results: list[ResultIn], teams: list[TeamIn], people: list[ParticipantIn]
) -> list[tuple[int, int]]:
    return [(t.number, s.rank) for t, s in score_teams(results, people, teams, DISCIPLINES, FAKE)]


def test_team_sums_and_per_discipline() -> None:
    people = [person(1, 1), person(2, 1), person(3, None)]
    results = [
        res(1, 1, points=10),
        res(2, 2, points=5),
        res(3, 2, "football", points=2),
        res(4, 3, points=100),
    ]
    ((_, team),) = score_teams(results, people, _teams(1), DISCIPLINES, FAKE)
    assert team.total == 17
    assert team.by_discipline == {"darts": 15, "football": 2, "pong": 0}
    assert len(team.members) == 2


def test_ranking_by_total_first() -> None:
    people = [person(1, 1), person(2, 2)]
    results = [res(1, 1, points=5), res(2, 2, points=9)]
    assert _rank(results, _teams(1, 2), people) == [(2, 1), (1, 2)]


def test_tie_break_sections_passed_then_bci_then_physical() -> None:
    people = [person(1, 1), person(2, 2)]
    # equal total 10: team 2 passed more sections
    results = [res(1, 1, points=10), res(2, 2, points=10), res(3, 2, section="physical", points=0)]
    assert _rank(results, _teams(1, 2), people) == [(2, 1), (1, 2)]
    # equal total and sections: more BCI points wins
    results = [
        res(1, 1, points=4),
        res(2, 1, section="physical", points=6),
        res(3, 2, points=6),
        res(4, 2, section="physical", points=4),
    ]
    assert _rank(results, _teams(1, 2), people) == [(2, 1), (1, 2)]
    # equal total, sections and BCI: more physical points wins
    results = [
        res(1, 1, points=5),
        res(2, 1, section="physical", points=1),
        res(3, 2, points=5),
        res(4, 2, section="physical", points=3),
    ]
    assert _rank(results, _teams(1, 2), people) == [(2, 1), (1, 2)]


def test_fully_equal_teams_share_rank() -> None:
    people = [person(1, 1), person(2, 2), person(3, 3)]
    results = [res(1, 1, points=5), res(2, 2, points=5), res(3, 3, points=1)]
    assert _rank(results, _teams(1, 2, 3), people) == [(1, 1), (2, 1), (3, 3)]


def test_finished_needs_all_members_with_all_sections() -> None:
    people = [person(1, 1), person(2, 1), person(3, 2)]
    results = [
        res(i, p, d, s)
        for i, (p, d, s) in enumerate(
            (p, d.code, s) for p in (1, 2) for d in DISCIPLINES for s in ("bci", "physical")
        )
    ]
    results.append(res(100, 3))
    out = {
        t.number: s.finished
        for t, s in score_teams(results, people, _teams(1, 2), DISCIPLINES, FAKE)
    }
    assert out == {1: True, 2: False}
    results[0] = res(0, 1, outcome="not_completed", points=None)
    out = {
        t.number: s.finished for t, s in score_teams(results, people, _teams(1), DISCIPLINES, FAKE)
    }
    assert out == {1: False}


def test_team_without_members_is_not_finished() -> None:
    ((_, team),) = score_teams([], [], _teams(1), DISCIPLINES, FAKE)
    assert (team.finished, team.total) == (False, 0)


def pong(id: int, participant: int, wins: int, session: str, **extra: object) -> ResultIn:
    return res(id, participant, "pong", wins=wins, session=session, points=None, **extra)  # type: ignore[arg-type]


DUEL_PEOPLE = [person(1, 1), person(2, 2), person(3, 1), person(4, 2)]


def test_duel_score_counts_pong_match_wins_per_team() -> None:
    results = [
        pong(1, 1, 1, "s1"),
        pong(2, 2, 0, "s1"),
        pong(3, 1, 0, "s2", section="physical"),
        pong(4, 2, 1, "s2", section="physical"),
        pong(5, 3, 1, "s3"),
        pong(6, 4, 0, "s3"),
    ]
    assert duel_score(results, DUEL_PEOPLE) == {1: 2, 2: 1}


def test_duel_score_ignores_points_and_other_disciplines() -> None:
    results = [res(1, 1, "darts", points=99), res(2, 2, "football", points=50)]
    assert duel_score(results, DUEL_PEOPLE) == {1: 0, 2: 0}


def test_duel_score_skips_voided_entered_and_unfinished() -> None:
    results = [
        pong(1, 1, 1, "v", voided=True),
        pong(2, 2, 0, "v"),
        pong(3, 1, 1, "e", status="entered"),
        pong(4, 2, 0, "e"),
        pong(5, 3, 1, "half"),  # the opponent's result has not arrived
    ]
    assert duel_score(results, DUEL_PEOPLE) == {1: 0, 2: 0}


def test_duel_score_skips_not_completed_match() -> None:
    results = [
        pong(1, 1, 1, "n"),
        res(2, 2, "pong", outcome="not_completed", points=None, session="n"),
    ]
    assert duel_score(results, DUEL_PEOPLE) == {1: 0, 2: 0}


def test_duel_score_excludes_matches_in_conflict() -> None:
    results = [
        pong(1, 1, 1, "c1"),
        pong(2, 2, 0, "c1"),
        pong(3, 1, 0, "c2"),  # participant 1 has a second pong BCI result: conflict
        pong(4, 4, 1, "c2"),
        pong(5, 3, 1, "ok"),
        pong(6, 4, 0, "ok2", section="physical"),  # other section, other session: half a match
    ]
    assert duel_score(results, DUEL_PEOPLE) == {1: 0, 2: 0}


def test_duel_score_rejects_two_winners_and_unknown_teams() -> None:
    results = [pong(1, 1, 1, "x"), pong(2, 2, 1, "x"), pong(3, 5, 1, "y"), pong(4, 2, 0, "y")]
    assert duel_score(results, [*DUEL_PEOPLE, person(5, None)]) == {1: 0, 2: 0}


def _top(results: list[ResultIn], numbers: dict[int, int], limit: int = 5, d: str = "darts"):  # type: ignore[no-untyped-def]
    people = [person(i, 1) for i in numbers]
    members = score_participants(results, people, DISCIPLINES, FAKE)
    return top_players(members.values(), numbers, d, limit)


def test_top_players_sum_both_sections_and_sort_by_points() -> None:
    results = [
        res(1, 1, points=5),
        res(2, 1, section="physical", points=7),
        res(3, 2, points=20),
        res(4, 3, "football", points=100),
    ]
    top = _top(results, {1: 1, 2: 2, 3: 3})
    assert [(e.participant_id, e.points, e.rank) for e in top] == [(2, 20, 1), (1, 12, 2)]


def test_top_players_tie_breaks_by_sections_then_number() -> None:
    results = [
        res(1, 1, points=10),
        res(2, 2, points=5),
        res(3, 2, section="physical", points=5),
        res(4, 3, points=10),
    ]
    top = _top(results, {1: 3, 2: 2, 3: 1})
    assert [e.participant_id for e in top] == [2, 3, 1]  # 2: two sections; 3 before 1 by number


def test_top_players_pending_take_no_place_and_follow_the_top() -> None:
    results = [res(i, i, points=i) for i in range(1, 8)]
    results += [res(20, 8, points=1), res(21, 8, points=2, session="again")]
    results += [res(30, 9, points=1), res(31, 9, points=2, session="again")]
    numbers = {i: i for i in range(1, 10)}
    top = _top(results, numbers)
    assert [(e.rank, e.participant_id, e.pending) for e in top] == [
        (1, 7, False),
        (2, 6, False),
        (3, 5, False),
        (4, 4, False),
        (5, 3, False),
        (None, 8, True),
        (None, 9, True),
    ]
    assert [e.rank for e in _top(results, numbers, limit=2)] == [1, 2, None, None]


def test_top_players_only_pending_when_nobody_counted() -> None:
    results = [res(1, 1, points=1), res(2, 1, points=2, session="again")]
    assert [(e.rank, e.pending) for e in _top(results, {1: 1})] == [(None, True)]


def test_top_players_empty_when_nobody_scored() -> None:
    assert _top([], {1: 1, 2: 2}) == []


def test_duel_score_skips_same_team_and_teamless_matches() -> None:
    results = [
        pong(1, 1, 1, "same"),  # players 1 and 3 are both on team 1
        pong(2, 3, 0, "same"),
        pong(3, 1, 1, "free"),  # player 5 has no team
        pong(4, 5, 0, "free"),
        pong(5, 5, 1, "free2"),
        pong(6, 2, 0, "free2"),
    ]
    people = [*DUEL_PEOPLE, person(5, None)]
    assert duel_score(results, people) == {1: 0, 2: 0}
