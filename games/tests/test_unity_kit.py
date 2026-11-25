"""Unity-кит нельзя собрать в CI, поэтому сверяем его с контрактами по тексту .cs-файлов.

Имена полей классов сообщений, значения констант, причины и сроки проверки калибровки должны
совпадать со схемами в `shared/` и с Python-SDK. Расхождение значит, что игра на Unity перестанет
понимать мост или лаунчер.
"""

import json
import math
import re
from pathlib import Path
from typing import Any

import pytest

from neurotlon_bridge import client as bridge_client
from neurotlon_games.sdk import app

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "games" / "unity" / "NeurotlonKit" / "Runtime"
LAUNCH = json.loads((ROOT / "shared" / "game-launch.schema.json").read_text(encoding="utf-8"))
BRIDGE = json.loads((ROOT / "shared" / "bridge-protocol.schema.json").read_text(encoding="utf-8"))
LD = LAUNCH["$defs"]
BD = BRIDGE["$defs"]


def source(name: str) -> str:
    text = (RUNTIME / name).read_text(encoding="utf-8")
    return re.sub(r"//[^\n]*", "", text)


def serializable_classes(text: str) -> dict[str, set[str]]:
    classes: dict[str, set[str]] = {}
    for name, body in re.findall(r"\[Serializable\]\s*public class (\w+)\s*\{([^{}]*)\}", text):
        classes[name] = set(re.findall(r"public\s+[\w\[\]]+\s+(\w+)\s*;", body))
    return classes


def result_entry_fields(text: str) -> set[str]:
    start = text.index("class ResultEntryData")
    end = text.index("public bool Has", start)
    return set(re.findall(r"public\s+\w+\s+(\w+)\s*(?:=\s*[^;]+)?;", text[start:end]))


def consts(text: str, kind: str) -> dict[str, str]:
    return dict(re.findall(rf"public const {kind} (\w+) = ([^;]+);", text))


def unquote(value: str) -> str:
    return value.strip().strip('"')


def props(schema: dict[str, Any]) -> set[str]:
    return set(schema["properties"])


LAUNCH_CS = serializable_classes(source("NeurotlonLaunch.cs"))
BRIDGE_CS = serializable_classes(source("NeurotlonBridge.cs"))

CLASS_TO_SCHEMA: dict[str, tuple[dict[str, set[str]], set[str]]] = {
    "LaunchFile": (LAUNCH_CS, props(LD["Launch"])),
    "LaunchParticipant": (LAUNCH_CS, props(LD["Launch"]["properties"]["participants"]["items"])),
    "LaunchBridge": (LAUNCH_CS, props(LD["Launch"]["properties"]["bridge"])),
    "BridgeEnvelope": (BRIDGE_CS, {"type"}),
    "HelloMessage": (BRIDGE_CS, props(BD["Hello"])),
    "HelloSignal": (BRIDGE_CS, props(BD["Hello"]["properties"]["signals"]["items"])),
    "ReadingData": (BRIDGE_CS, props(BD["Reading"])),
    "SampleSignals": (BRIDGE_CS, set(BD["SignalName"]["enum"])),
    "SampleMessage": (BRIDGE_CS, props(BD["Sample"])),
    "SensorMessage": (BRIDGE_CS, props(BD["Sensor"])),
    "BurstMessage": (BRIDGE_CS, props(BD["Burst"])),
}


@pytest.mark.parametrize("name", sorted(CLASS_TO_SCHEMA))
def test_message_class_fields_match_schema(name: str) -> None:
    classes, expected = CLASS_TO_SCHEMA[name]
    assert name in classes, f"в .cs нет [Serializable] класса {name}"
    assert classes[name] == expected


def test_result_entry_fields_match_schema() -> None:
    assert result_entry_fields(source("NeurotlonResult.cs")) == props(LD["Entry"])


def test_result_json_keys_are_written_by_name() -> None:
    text = (RUNTIME / "NeurotlonResult.cs").read_text(encoding="utf-8")
    for name in props(LD["Result"]) | props(LD["Entry"]):
        assert f'\\"{name}\\"' in text, f"NeurotlonResult.cs не пишет ключ {name}"


def test_message_type_constants_match_schema() -> None:
    values = {
        v
        for k, v in (
            (k, unquote(v)) for k, v in consts(source("NeurotlonProtocol.cs"), "string").items()
        )
        if k.startswith("Message")
    }
    schema_types = {
        BD[name]["properties"]["type"]["const"]
        for name in ("Hello", "Sample", "Sensor", "Calibration", "Burst", "Calibrate", "Reset")
    }
    assert values == schema_types


ENUM_PREFIXES: list[tuple[str, set[str]]] = [
    ("SensorState", set(BD["SensorState"]["enum"])),
    ("Signal", set(BD["SignalName"]["enum"])),
    ("Step", set(BD["CalibrationStep"]["enum"])),
    ("Invalid", set(BD["InvalidReason"]["enum"])),
    ("Phase", set(BD["Phase"]["enum"])),
    ("EegMethod", set(BD["EegMethod"]["enum"])),
    ("Feature", set(BD["Feature"]["enum"])),
    ("CalibStatus", set(BD["Calibration"]["properties"]["status"]["enum"])),
    ("Discipline", set(LD["Discipline"]["enum"])),
    (
        "Side",
        set(LD["Launch"]["properties"]["participants"]["items"]["properties"]["side"]["enum"]),
    ),
    ("ResultStatus", set(LD["Result"]["properties"]["status"]["enum"])),
    ("Outcome", set(LD["Entry"]["properties"]["outcome"]["enum"])),
    ("NotDone", set(LD["Entry"]["properties"]["reason"]["enum"])),
]


@pytest.mark.parametrize(("prefix", "expected"), ENUM_PREFIXES, ids=[p for p, _ in ENUM_PREFIXES])
def test_enum_constants_match_schema(prefix: str, expected: set[str]) -> None:
    strings = {k: unquote(v) for k, v in consts(source("NeurotlonProtocol.cs"), "string").items()}
    # «Signal» не должен захватывать константы с более длинным общим префиксом
    longer = [p for p, _ in ENUM_PREFIXES if p != prefix and p.startswith(prefix)]
    found = {
        v
        for k, v in strings.items()
        if k.startswith(prefix) and not any(k.startswith(p) for p in longer)
    }
    assert found == expected


def test_every_protocol_constant_is_checked() -> None:
    strings = consts(source("NeurotlonProtocol.cs"), "string")
    known = [p for p, _ in ENUM_PREFIXES] + ["Message"]
    assert [k for k in strings if not any(k.startswith(p) for p in known)] == []


def test_numeric_limits_match_schema() -> None:
    ints = consts(source("NeurotlonProtocol.cs"), "int")
    assert int(ints["ProtocolVersion"]) == LD["Launch"]["properties"]["protocol"]["const"] == 1
    assert int(ints["ResultReasonMaxLength"]) == LD["Result"]["properties"]["reason"]["maxLength"]
    assert int(ints["ResultPointsMax"]) == LD["Entry"]["properties"]["points"]["maximum"]
    duration = LD["Launch"]["properties"]["duration_s"]
    assert int(ints["DurationMinSeconds"]) == duration["minimum"]
    assert int(ints["DurationMaxSeconds"]) == duration["maximum"]


def test_participant_code_pattern_matches_schema() -> None:
    text = (RUNTIME / "NeurotlonLaunch.cs").read_text(encoding="utf-8")
    assert f'new Regex("{LD["ParticipantCode"]["pattern"]}")' in text


def number(consts_map: dict[str, str], key: str) -> float:
    return float(consts_map[key].strip().rstrip("f"))


def test_game_does_not_calibrate_in_the_kit() -> None:
    """Калибровку проводит лаунчер: в ките нет шагов калибровки и команд `calibrate`."""
    assert not (RUNTIME / "NeurotlonCalibration.cs").exists()
    for name in sorted(p.name for p in RUNTIME.glob("*.cs")):
        text = source(name)
        assert "NeurotlonCalibration " not in text, name
        assert "CalibrateJson" not in text, name
        assert "Stage.Calibrating" not in text, name
    stages = re.search(r"enum Stage \{([^}]*)\}", source("NeurotlonGame.cs"))
    assert stages is not None
    order = [name.strip() for name in stages.group(1).split(",")]
    assert order == [
        "Connecting",
        "Tutorial",
        "Check",
        "Countdown",
        "Playing",
        "SensorLost",
        "ConfirmAbort",
        "Finished",
    ]


def test_readiness_reasons_match_python_sdk() -> None:
    strings = {k: unquote(v) for k, v in consts(source("NeurotlonReadiness.cs"), "string").items()}
    assert strings == {
        "NotCalibratedReason": app.NOT_CALIBRATED_REASON,
        "CalibrationResetReason": app.CALIBRATION_RESET_REASON,
    }
    assert len(strings["NotCalibratedReason"]) <= LD["Result"]["properties"]["reason"]["maxLength"]


def test_readiness_follows_the_protocol_contract() -> None:
    """Готовность по `hello.calibrated` и `calibration_state`, потеря по `not_calibrated`."""
    text = source("NeurotlonReadiness.cs")
    for name in ("FeatureCalibrationState", "SensorStateEmulated", "InvalidNotCalibrated"):
        assert f"NeurotlonProtocol.{name}" in text
    assert "calibration_state" in BD["Feature"]["enum"]
    assert "calibrated" in props(BD["Hello"])
    assert "not_calibrated" in BD["InvalidReason"]["enum"]
    assert "NeurotlonReadiness.Uncalibrated(" in source("NeurotlonGame.cs")
    assert "bool Calibrated(string signal)" in source("NeurotlonBridge.cs")


def test_calibration_loss_timing_matches_python_game_app() -> None:
    floats = consts(source("NeurotlonReadiness.cs"), "float")
    assert number(floats, "CalibrationLostSeconds") == app.GameApp.calibration_lost_abort_s


def test_unity_texts_keep_only_shared_player_phrases() -> None:
    names = set(consts(source("NeurotlonTexts.cs"), "string"))
    assert {"Tense", "Relax", "RelaxShort"} <= names
    assert names.isdisjoint({"BaselineLook", "CycleWeak", "CycleNoSignal"})


def test_unity_kit_texts_do_not_name_body_parts() -> None:
    values = re.findall(r'const string \w+ = "([^"]*)"', source("NeurotlonTexts.cs"))
    assert values
    for word in ("рук", "кулак", "ног"):
        assert word not in " ".join(values).lower()


def test_unity_bridge_exposes_burst_api() -> None:
    text = source("NeurotlonBridge.cs")
    for member in (
        "bool TryTakeBurst(string signal)",
        "void DiscardBursts(string signal)",
        "bool BurstSupported",
        "bool Supports(string feature)",
    ):
        assert member in text
    assert int(consts(text, "int")["MaxBursts"]) == 8


def test_bridge_timings_match_python_client() -> None:
    floats = consts(source("NeurotlonBridge.cs"), "float")
    assert number(floats, "StaleSeconds") == bridge_client.STALE_AFTER_S
    assert number(floats, "ReconnectSeconds") == bridge_client.RECONNECT_S
    size = consts(source("NeurotlonBridge.cs"), "int")["MaxLineBytes"]
    assert math.prod(int(part) for part in size.split("*")) == bridge_client.MAX_LINE_BYTES


def test_game_timings_match_python_game_app() -> None:
    floats = consts(source("NeurotlonGame.cs"), "float")
    assert number(floats, "ConnectTimeoutSeconds") == app.GameApp.connect_timeout_s
    assert number(floats, "CountdownSeconds") == app.GameApp.countdown_s
    assert number(floats, "LostAbortSeconds") == app.GameApp.lost_abort_s
    assert number(floats, "FinishShowSeconds") == app.GameApp.finish_show_s


@pytest.mark.parametrize("name", sorted(p.name for p in RUNTIME.glob("*.cs")))
def test_braces_and_parentheses_are_balanced(name: str) -> None:
    text = source(name)
    text = re.sub(r"'(?:[^'\\\n]|\\.)'", "''", text)  # символы
    text = re.sub(r'@?"(?:[^"\\\n]|\\.)*"', '""', text)  # строки
    for opening, closing in ("{}", "()", "[]"):
        assert text.count(opening) == text.count(closing), f"{name}: {opening}{closing}"


def test_kit_package_files_exist() -> None:
    kit = RUNTIME.parent
    package = json.loads((kit / "package.json").read_text(encoding="utf-8"))
    assert package["name"] == "ru.neurotlon.kit"
    assert (kit / "README.md").exists()
    assert (RUNTIME / "Neurotlon.Kit.asmdef").exists()


def test_max_points_limit_matches_schema() -> None:
    ints = consts(source("NeurotlonProtocol.cs"), "int")
    assert int(ints["MaxPointsMax"]) == LD["Launch"]["properties"]["max_points"]["maximum"]


def test_unity_result_checks_max_points() -> None:
    text = source("NeurotlonResult.cs")
    assert "launch.MaxPoints" in text
    assert "!launch.IsPong" in text


def test_unity_points_are_whole_numbers() -> None:
    text = source("NeurotlonResult.cs")
    assert re.search(r"public int points;", text)
    assert "float points" not in text
    assert "float points" not in source("NeurotlonProtocol.cs")
    assert LD["Entry"]["properties"]["points"]["type"] == "integer"
