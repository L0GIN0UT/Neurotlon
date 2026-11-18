"""Заглушка игры для разработки лаунчера: `python -m neurotlon_games.stub --launch <path>`.

Читает launch.json, ждёт `--seconds`, пишет result.json по `shared/game-launch.md`
(сначала во временный файл, затем переименование) и выходит с кодом 0.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
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


def spawn_child(pid_file: Path) -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    pid_file.write_text(str(child.pid), encoding="utf-8")


def connect_bridge(host: str, port: int, wait_s: float = 5.0) -> None:
    """Подключиться к мосту, дождаться связи и отключиться."""
    from neurotlon_bridge.client import BridgeClient

    client = BridgeClient(host, port)
    try:
        deadline = time.monotonic() + wait_s
        while not client.connected and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.3)
    finally:
        client.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="neurotlon_games.stub", description=__doc__)
    parser.add_argument("--launch", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--abort", action="store_true", help="записать status=aborted")
    parser.add_argument(
        "--spawn-child",
        action="store_true",
        help="запустить долгоживущий дочерний процесс, его pid — в child.pid рядом с result.json",
    )
    parser.add_argument("--crash", action="store_true", help="выйти с кодом 1 без результата")
    parser.add_argument(
        "--connect",
        action="store_true",
        help="подключиться к мосту из launch.json (для проверки neurotlon-game-check)",
    )
    args = parser.parse_args(argv)

    launch = json.loads(args.launch.read_text(encoding="utf-8"))
    if args.spawn_child:
        spawn_child(Path(launch["result_path"]).parent / "child.pid")
    if args.connect:
        connect_bridge(launch["bridge"]["host"], launch["bridge"]["port"])
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
