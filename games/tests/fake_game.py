"""Нарочно сломанные «игры» для `neurotlon-game-check`: `fake_game.py --mode X --launch ...`."""

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

from neurotlon_games.stub import build_result, connect_bridge, write_atomic


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--launch", type=Path, required=True)
    parser.add_argument("--mode", default="ok")
    parser.add_argument("--no-bridge", action="store_true")
    args = parser.parse_args()
    launch: dict[str, Any] = json.loads(args.launch.read_text(encoding="utf-8"))
    if not args.no_bridge:
        connect_bridge(launch["bridge"]["host"], launch["bridge"]["port"], wait_s=3)
    result = build_result(launch, random.Random(1), abort=False)
    out = Path(launch["result_path"])
    match args.mode:
        case "no-result":
            return 0
        case "crash":
            return 3
        case "hang":
            time.sleep(300)
        case "wrong-session":
            result["session_id"] = "00000000-0000-4000-8000-000000000000"
        case "two-winners":
            for entry in result["entries"]:
                entry["wins"] = 1
        case "no-winner":
            for entry in result["entries"]:
                entry["wins"] = 0
        case "wins-outside-pong":
            result["entries"][0]["wins"] = 1
        case "wrong-participant":
            result["entries"][0]["participant_code"] = "NT99"
        case "points-too-big":
            result["entries"][0]["points"] = 5000
        case "fractional-points":
            result["entries"][0]["points"] = 4.5
        case "points-over-limit":
            result["entries"][0]["points"] = 50
        case "self-abort":
            result = {**result, "status": "aborted", "entries": [], "reason": "сам прервался"}
        case "garbage":
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("{not json", encoding="utf-8")
            return 0
        case "ok":
            pass
    write_atomic(out, result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
