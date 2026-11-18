"""Team draw: a pure, deterministic function of (participants, m, seed)."""

import random
from dataclasses import dataclass

OVZ = "ovz"
GENERAL = "general"

# The first two teams are red and blue (default names below); the admin can rename and recolour.
DEFAULT_NAMES: tuple[str, ...] = ("Красные", "Синие")
PALETTE: tuple[str, ...] = (
    "#E6194B",
    "#4363D8",
    "#3CB44B",
    "#F58231",
    "#911EB4",
    "#42D4F4",
    "#F032E6",
    "#BFEF45",
    "#9A6324",
    "#469990",
    "#800000",
    "#808000",
    "#000075",
    "#E6BEFF",
)


@dataclass(frozen=True)
class DrawOption:
    m: int
    team_count: int
    reserve_general: int
    reserve_ovz: int

    @property
    def reserve_total(self) -> int:
        return self.reserve_general + self.reserve_ovz


@dataclass(frozen=True)
class Member:
    code: str
    category: str
    number_in_team: int


@dataclass(frozen=True)
class TeamResult:
    number: int
    name: str
    color: str
    members: tuple[Member, ...]


@dataclass(frozen=True)
class PairResult:
    k: int
    code_a: str
    code_b: str


@dataclass(frozen=True)
class DuelResult:
    order: int
    team_a: int
    team_b: int
    pairs: tuple[PairResult, ...]


@dataclass(frozen=True)
class DrawResult:
    seed: int
    m: int
    team_count: int
    teams: tuple[TeamResult, ...]
    duels: tuple[DuelResult, ...]
    reserve_ovz: tuple[str, ...]
    reserve_general: tuple[str, ...]


def even_team_count(ovz: int, general: int, m: int, max_teams: int | None = None) -> int:
    """Largest even team count for team size m, capped by max_teams; 0 if fewer than 2 fit."""
    if m < 1:
        return 0
    t = min(ovz // m, general // m)
    if max_teams is not None:
        t = min(t, max_teams)
    t -= t % 2
    return t if t >= 2 else 0


def draw_options(ovz: int, general: int, max_teams: int | None = None) -> list[DrawOption]:
    options = []
    for m in range(1, min(ovz, general) + 1):
        t = even_team_count(ovz, general, m, max_teams)
        if t:
            options.append(DrawOption(m, t, general - t * m, ovz - t * m))
    return sorted(options, key=lambda o: (o.reserve_total, -o.m))


def run_draw(
    participants: list[tuple[str, str]], m: int, seed: int, max_teams: int | None = None
) -> DrawResult:
    ovz = sorted(code for code, cat in participants if cat == OVZ)
    general = sorted(code for code, cat in participants if cat == GENERAL)
    t = even_team_count(len(ovz), len(general), m, max_teams)
    if not t:
        raise ValueError("fewer than 2 teams possible for this m")

    rng = random.Random(seed)
    rng.shuffle(ovz)
    rng.shuffle(general)
    pattern = [OVZ] * m + [GENERAL] * m
    rng.shuffle(pattern)
    order = list(range(t))
    rng.shuffle(order)

    teams: list[TeamResult] = []
    for position, raw in enumerate(order, start=1):
        ovz_part = iter(ovz[raw::t][:m])
        general_part = iter(general[raw::t][:m])
        members = tuple(
            Member(next(ovz_part) if cat == OVZ else next(general_part), cat, slot)
            for slot, cat in enumerate(pattern, start=1)
        )
        color = PALETTE[(position - 1) % len(PALETTE)]
        name = (
            DEFAULT_NAMES[position - 1] if position <= len(DEFAULT_NAMES) else f"Команда {position}"
        )
        teams.append(TeamResult(position, name, color, members))

    duels = []
    for i in range(0, t, 2):
        a, b = teams[i], teams[i + 1]
        pairs = tuple(
            PairResult(k, a.members[k - 1].code, b.members[k - 1].code) for k in range(1, 2 * m + 1)
        )
        duels.append(DuelResult(i // 2 + 1, a.number, b.number, pairs))

    return DrawResult(
        seed=seed,
        m=m,
        team_count=t,
        teams=tuple(teams),
        duels=tuple(duels),
        reserve_ovz=tuple(sorted(ovz[m * t :])),
        reserve_general=tuple(sorted(general[m * t :])),
    )
