"""Расширения протокола: цикл калибровки, burst, метод ЭЭГ, устойчивость к новым именам."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from neurotlon_bridge import protocol, source
from neurotlon_bridge.source import Reading, Segment

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "shared" / "bridge-protocol.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)

TENSE = Segment("tense", 5)
RELAX = Segment("relax", 5)


def test_decode_skips_unknown_signal_name_in_sample() -> None:
    line = (
        '{"type":"sample","t_ms":7,"signals":{"alpha":{"value":0.5,"valid":true},'
        '"emg":{"value":0.25,"valid":true}}}'
    )
    assert protocol.decode(line) == protocol.Sample(7, {"emg": Reading(0.25)})


def test_decode_sample_with_only_unknown_names_keeps_frame() -> None:
    line = '{"type":"sample","t_ms":7,"signals":{"gsr":{"value":0.5,"valid":true}}}'
    assert protocol.decode(line) == protocol.Sample(7, {})


def test_decode_skips_unknown_signal_name_in_hello() -> None:
    line = (
        '{"type":"hello","protocol":1,"signals":[{"name":"gsr","state":"connected"},'
        '{"name":"emg","state":"emulated"}]}'
    )
    assert protocol.decode(line) == protocol.Hello((("emg", "emulated"),))


def test_decode_still_rejects_bad_reading_of_known_signal() -> None:
    line = '{"type":"sample","t_ms":1,"signals":{"alpha":{"value":1,"valid":true},"emg":{}}}'
    with pytest.raises(ValueError):
        protocol.decode(line)


def test_hello_from_old_bridge_has_no_features() -> None:
    line = '{"type":"hello","protocol":1,"signals":[{"name":"emg","state":"emulated"}]}'
    assert protocol.decode(line) == protocol.Hello((("emg", "emulated"),))


def test_hello_ignores_unknown_feature_and_method() -> None:
    line = (
        '{"type":"hello","protocol":1,"signals":[{"name":"eeg","state":"connected"}],'
        '"features":["burst","teleport"],"eeg_method":"fft"}'
    )
    expected = protocol.Hello((("eeg", "connected"),), features=("burst",), eeg_method=None)
    assert protocol.decode(line) == expected


def test_burst_with_unknown_signal_is_ignored() -> None:
    assert protocol.decode('{"type":"burst","signal":"eeg","t_ms":1,"seq":1}') is None
    assert protocol.decode('{"type":"burst","signal":"emg_up","t_ms":1,"seq":1}') is None


@pytest.mark.parametrize(
    "line",
    [
        '{"type":"burst","signal":"emg","t_ms":1}',
        '{"type":"burst","signal":"emg","seq":1}',
        '{"type":"burst","signal":"emg","t_ms":1,"seq":"a"}',
        '{"type":"burst","t_ms":1,"seq":1}',
        '{"type":"calibrate","signal":"emg","step":"cycle","segments":"x"}',
        '{"type":"calibrate","signal":"emg","step":"cycle","segments":[{"phase":"hold","s":3}]}',
        '{"type":"calibrate","signal":"emg","step":"cycle","segments":[{"phase":"tense"}]}',
        '{"type":"calibrate","signal":"eeg","step":"baseline","duration_s":"x"}',
    ],
)
def test_malformed_new_messages_raise(line: str) -> None:
    with pytest.raises(ValueError):
        protocol.decode(line)


def test_burst_rise_is_clamped() -> None:
    msg = protocol.decode('{"type":"burst","signal":"emg","t_ms":1,"seq":1,"rise":4}')
    assert msg == protocol.Burst("emg", 1, 1, 1.0)
    VALIDATOR.validate(json.loads(protocol.encode(protocol.Burst("emg", 1, 1, 4.0))))


def test_unity_unset_fields_are_treated_as_absent() -> None:
    line = '{"type":"calibrate","signal":"emg","step":"rest","segments":[],"duration_s":0}'
    assert protocol.decode(line) == protocol.Calibrate("emg", "rest")


def test_calibration_progress_fields_are_decoded() -> None:
    line = (
        '{"type":"calibration","signal":"emg","step":"cycle","status":"running",'
        '"progress":0.4,"segment":2,"phase":"relax","phase_left_s":1.5}'
    )
    msg = protocol.decode(line)
    assert msg == protocol.Calibration("emg", "cycle", "running", 0.4, None, 2, "relax", 1.5)


def test_future_phase_is_dropped_not_fatal() -> None:
    line = '{"type":"calibration","signal":"emg","step":"cycle","status":"running","phase":"hold"}'
    assert protocol.decode(line) == protocol.Calibration("emg", "cycle", "running")


def test_limits_match_schema() -> None:
    defs = SCHEMA["$defs"]
    segments = defs["Calibrate"]["properties"]["segments"]
    segment_s = defs["Segment"]["properties"]["s"]
    duration = defs["Calibrate"]["properties"]["duration_s"]
    schema_limits = (
        segments["minItems"],
        segments["maxItems"],
        segment_s["minimum"],
        segment_s["maximum"],
        duration["minimum"],
        duration["maximum"],
    )
    code_limits = (
        source.SEGMENTS_MIN_COUNT,
        source.SEGMENTS_MAX_COUNT,
        source.SEGMENT_MIN_S,
        source.SEGMENT_MAX_S,
        source.BASELINE_MIN_S,
        source.BASELINE_MAX_S,
    )
    assert code_limits == schema_limits


@pytest.mark.parametrize(
    "msg",
    [
        protocol.Calibrate("emg", "cycle"),
        protocol.Calibrate("emg", "cycle", (TENSE, RELAX)),
        protocol.Calibrate("emg", "cycle", (Segment("tense", 15), Segment("relax", 15)) * 2),
        protocol.Calibrate("emg", "cycle", (Segment("tense", 2), Segment("relax", 2)) * 4),
        protocol.Calibrate("eeg", "baseline", duration_s=5),
        protocol.Calibrate("eeg", "baseline", duration_s=30),
        protocol.Calibrate("emg", "rest", (TENSE,), 1.0),  # поля чужого шага игнорируются
    ],
)
def test_calibrate_problem_none_for_valid(msg: protocol.Calibrate) -> None:
    assert protocol.calibrate_problem(msg) is None


@pytest.mark.parametrize(
    "msg",
    [
        protocol.Calibrate("emg", "cycle", (TENSE,)),
        protocol.Calibrate("emg", "cycle", (TENSE, RELAX) * 5),
        protocol.Calibrate("emg", "cycle", (TENSE, TENSE)),
        protocol.Calibrate("emg", "cycle", (RELAX, RELAX)),
        protocol.Calibrate("emg", "cycle", (Segment("tense", 1.9), RELAX)),
        protocol.Calibrate("emg", "cycle", (Segment("tense", 15.1), RELAX)),
        protocol.Calibrate(
            "emg", "cycle", (Segment("tense", 15), Segment("relax", 15)) * 2 + (TENSE,)
        ),
        protocol.Calibrate("eeg", "baseline", duration_s=4.9),
        protocol.Calibrate("eeg", "baseline", duration_s=30.1),
    ],
)
def test_calibrate_problem_text_for_invalid(msg: protocol.Calibrate) -> None:
    assert protocol.calibrate_problem(msg)
