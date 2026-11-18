"""Заглушка игры для разработки лаунчера: `python -m neurotlon_games.stub --launch <path>`.

Читает launch.json, ждёт `--seconds`, пишет result.json по `shared/game-launch.md`
(сначала во временный файл, затем переименование) и выходит с кодом 0.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

PROTOCOL = 1


def build_result(launch: dict[str, Any], rng: random.Random, abort: bool) -> dict[str, Any]:
    session_id = launch["session_id"]
    if abort:
        return {
            "protocol": PROTOCOL,
            "session_id": session_id,
            "status": "aborted",
            "entries": [],
            "reason": "stub: aborted",
        }
    entries: list[dict[str, Any]] = [
        {"participant_code": p["code"], "outcome": "completed", "points": rng.randint(0, 100)}
        for p in launch["participants"]
    ]
    if launch["discipline"] == "pong":
        winner = rng.randrange(len(entries))
        for i, entry in enumerate(entries):
            entry["wins"] = int(i == winner)
    return {
        "protocol": PROTOCOL,
        "session_id": session_id,
        "status": "finished",
        "entries": entries,
    }


def write_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="neurotlon_games.stub", description=__doc__)
    parser.add_argument("--launch", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--abort", action="store_true", help="записать status=aborted")
    parser.add_argument("--crash", action="store_true", help="выйти с кодом 1 без результата")
    args = parser.parse_args(argv)

    launch = json.loads(args.launch.read_text(encoding="utf-8"))
    time.sleep(max(args.seconds, 0.0))
    if args.crash:
        print("stub: simulated crash", file=sys.stderr)
        return 1
    write_atomic(
        Path(launch["result_path"]), build_result(launch, random.Random(args.seed), args.abort)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
