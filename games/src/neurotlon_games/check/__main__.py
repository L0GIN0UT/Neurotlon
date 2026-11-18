"""`neurotlon-game-check --discipline pong -- <команда игры>`: проверка игры по контракту."""

from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Sequence
from pathlib import Path

from neurotlon_bridge.source import PROFILES

from .checks import Options, run_check

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_USAGE = 2

DESCRIPTION = """\
Запускает игру так же, как лаунчер стенда, с эмулированным мостом, который сам двигает
сигналы, и проверяет: запуск, подключение к мосту, калибровку, выход вовремя, result.json
(схема, session_id, правила сервера, один победитель в понге). Код выхода 0 только если
нет ни одного FAIL. Команда игры задаётся после `--`, лаунчер допишет к ней `--launch <путь>`.

Пример: neurotlon-game-check --discipline pong -- python -m neurotlon_games.template
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="neurotlon-game-check",
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--discipline", required=True, choices=sorted(PROFILES))
    parser.add_argument(
        "--duration-s",
        type=int,
        default=10,
        help="duration_s в launch.json, от 10 (по умолчанию 10)",
    )
    parser.add_argument(
        "--max-points",
        type=int,
        default=None,
        help="max_points в launch.json: лимит очков за секцию дартса и футбола (по умолчанию нет)",
    )
    parser.add_argument(
        "--grace-s",
        type=float,
        default=120.0,
        help="запас на выход сверх duration_s, как у лаунчера (по умолчанию 120)",
    )
    parser.add_argument(
        "--bridge-speed",
        type=float,
        default=10.0,
        help="во сколько раз быстрее мост проводит калибровку (по умолчанию 10)",
    )
    parser.add_argument(
        "--time-scale",
        type=float,
        default=1.0,
        help="ускорить таймеры игр на GameApp через NEUROTLON_TIME_SCALE (для тестов)",
    )
    parser.add_argument(
        "--abort-test",
        action="store_true",
        help="вместо обычной проверки оборвать мост: прервётся ли игра (необязательно)",
    )
    parser.add_argument("--abort-wait-s", type=float, default=None, help="сколько ждать выхода")
    parser.add_argument(
        "--keep", type=Path, default=None, help="папка, куда сохранить файлы сессии"
    )
    return parser


def split_command(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    """Аргументы проверки и команда игры (всё после первого `--`)."""
    args = list(argv)
    if "--" not in args:
        return args, []
    index = args.index("--")
    return args[:index], args[index + 1 :]


def main(argv: Sequence[str] | None = None) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(errors="replace")  # консоль не в UTF-8 не должна ронять отчёт
    own, command = split_command(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(own)
    if not command:
        parser.error("после `--` нужна команда запуска игры")
    if args.duration_s < 10 or args.time_scale <= 0 or args.bridge_speed <= 0:
        parser.error("duration-s не меньше 10, time-scale и bridge-speed больше 0")
    if args.max_points is not None and not 1 <= args.max_points <= 1000:
        parser.error("max-points от 1 до 1000")
    options = Options(
        discipline=args.discipline,
        command=tuple(command),
        duration_s=args.duration_s,
        max_points=args.max_points,
        grace_s=args.grace_s,
        bridge_speed=args.bridge_speed,
        time_scale=args.time_scale,
        abort_test=args.abort_test,
        abort_wait_s=args.abort_wait_s,
        keep_dir=args.keep,
    )
    print(f"Проверка игры: {args.discipline}, duration_s={args.duration_s}", flush=True)
    report = run_check(options)
    print(report.format())
    return EXIT_PASS if report.passed else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
