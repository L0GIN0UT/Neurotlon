import pytest

from neurotlon_server.draw import (
    PALETTE,
    DrawOption,
    DrawResult,
    draw_options,
    even_team_count,
    run_draw,
)


def people(ovz: int, general: int) -> list[tuple[str, str]]:
    return [(f"NT{i:02d}", "ovz") for i in range(1, ovz + 1)] + [
        (f"NT{i:02d}", "general") for i in range(ovz + 1, ovz + general + 1)
    ]


def category_of(result: DrawResult) -> dict[str, str]:
    return {x.code: x.category for t in result.teams for x in t.members}


# --- options ---


@pytest.mark.parametrize(("ovz", "general"), [(0, 0), (0, 9), (9, 0), (1, 1), (1, 5), (2, 1)])
def test_no_options_when_fewer_than_two_teams(ovz: int, general: int) -> None:
    assert draw_options(ovz, general) == []


def test_options_7_ovz_9_general() -> None:
    assert draw_options(7, 9) == [
        DrawOption(m=3, team_count=2, reserve_general=3, reserve_ovz=1),
        DrawOption(m=1, team_count=6, reserve_general=3, reserve_ovz=1),
        DrawOption(m=2, team_count=2, reserve_general=5, reserve_ovz=3),
    ]


def test_options_sorted_by_reserve_then_larger_m() -> None:
    options = draw_options(10, 10)
    keys = [(o.reserve_total, -o.m) for o in options]
    assert keys == sorted(keys)


def test_even_team_count_never_odd() -> None:
    for ovz in range(0, 13):
        for general in range(0, 13):
            for m in range(1, 8):
                assert even_team_count(ovz, general, m) % 2 == 0


# --- run_draw ---


@pytest.mark.parametrize(("ovz", "general", "m"), [(10, 10, 1), (10, 10, 2), (7, 9, 1), (9, 11, 2)])
def test_structure(ovz: int, general: int, m: int) -> None:
    result = run_draw(people(ovz, general), m, seed=5)
    t = result.team_count
    assert t % 2 == 0 and t >= 2
    assert len(result.teams) == t
    cats = category_of(result)
    for team in result.teams:
        assert len(team.members) == 2 * m
        assert [x.number_in_team for x in team.members] == list(range(1, 2 * m + 1))
        assert sum(x.category == "ovz" for x in team.members) == m
    placed = set(cats)
    assert len(placed) == t * 2 * m
    assert set(result.reserve_ovz).isdisjoint(placed)
    assert set(result.reserve_general).isdisjoint(placed)
    assert len(result.reserve_ovz) == ovz - t * m
    assert len(result.reserve_general) == general - t * m
    assert placed | set(result.reserve_ovz) | set(result.reserve_general) == {
        c for c, _ in people(ovz, general)
    }


def test_slot_pattern_shared_by_all_teams() -> None:
    result = run_draw(people(10, 10), 2, seed=11)
    patterns = {tuple(x.category for x in t.members) for t in result.teams}
    assert len(patterns) == 1


def test_pairs_share_category_and_duels() -> None:
    result = run_draw(people(10, 10), 2, seed=3)
    cats = category_of(result)
    assert [(d.order, d.team_a, d.team_b) for d in result.duels] == [
        (i + 1, 2 * i + 1, 2 * i + 2) for i in range(result.team_count // 2)
    ]
    for duel in result.duels:
        assert [p.k for p in duel.pairs] == [1, 2, 3, 4]
        team_a = result.teams[duel.team_a - 1]
        team_b = result.teams[duel.team_b - 1]
        for pair in duel.pairs:
            assert pair.code_a == team_a.members[pair.k - 1].code
            assert pair.code_b == team_b.members[pair.k - 1].code
            assert cats[pair.code_a] == cats[pair.code_b]


def test_team_numbers_names_colors() -> None:
    result = run_draw(people(14, 14), 1, seed=1)
    assert len(PALETTE) >= 12 and len(set(PALETTE)) == len(PALETTE)
    assert [t.number for t in result.teams] == list(range(1, 15))
    assert result.teams[0].name == "Команда 1"
    assert [t.color for t in result.teams] == list(PALETTE[:14])


def test_deterministic_and_input_order_independent() -> None:
    data = people(10, 10)
    first = run_draw(data, 2, seed=42)
    assert run_draw(data, 2, seed=42) == first
    assert run_draw(list(reversed(data)), 2, seed=42) == first


def test_different_seed_differs() -> None:
    data = people(10, 10)
    assert run_draw(data, 1, seed=1) != run_draw(data, 1, seed=2)


def test_seed_zero_and_large() -> None:
    data = people(4, 4)
    assert run_draw(data, 1, seed=0).seed == 0
    assert run_draw(data, 1, seed=2**63 - 1).team_count == 4


def test_invalid_m_raises() -> None:
    with pytest.raises(ValueError):
        run_draw(people(3, 3), 2, seed=1)
    with pytest.raises(ValueError):
        run_draw(people(5, 5), 0, seed=1)


def test_max_teams_caps_team_count() -> None:
    assert even_team_count(10, 10, 1) == 10
    assert even_team_count(10, 10, 1, max_teams=2) == 2
    assert even_team_count(10, 10, 1, max_teams=3) == 2
    assert even_team_count(1, 10, 1, max_teams=2) == 0
    assert {o.team_count for o in draw_options(10, 10, max_teams=2)} == {2}
    assert run_draw(people(10, 10), 5, seed=1, max_teams=2).team_count == 2
