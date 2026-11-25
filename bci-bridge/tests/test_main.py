from __future__ import annotations

import json
from pathlib import Path

import pytest

from neurotlon_bridge import hardware_source
from neurotlon_bridge.__main__ import build_parser, main
from neurotlon_bridge.devices.base import (
    BluetoothUnavailableError,
    DeviceBackend,
    SdkUnavailableError,
)
from neurotlon_bridge.devices.fakes import FakeBackend, FakeRawSensor


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "bridge.toml"
    path.write_text(body, encoding="utf-8")
    return path


def factory_for(backend: FakeBackend):  # type: ignore[no-untyped-def]
    def factory(scan_s: float) -> DeviceBackend:
        return backend

    return factory


def test_without_config_exits_2(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main([], backend_factory=factory_for(FakeBackend())) == 2
    assert "bridge.example.toml" in capsys.readouterr().err


def test_missing_serial_for_profile_exits_2(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    config = write_config(tmp_path, '[devices]\neeg = "BB1"\n')
    backend = FakeBackend()
    code = main(
        ["--profile", "darts", "--config", str(config)], backend_factory=factory_for(backend)
    )
    assert code == 2
    assert "emg" in capsys.readouterr().err
    assert backend.open_calls == []


def test_unknown_profile_rejected() -> None:
    with pytest.raises(SystemExit):
        main(["--emulate", "--profile", "chess"])


def test_scan_lists_devices(capsys: pytest.CaptureFixture[str]) -> None:
    backend = FakeBackend([FakeRawSensor("brainbit", "BB-777"), FakeRawSensor("callibri", "CA-1")])
    assert main(["--scan"], backend_factory=factory_for(backend)) == 0
    out = capsys.readouterr().out
    assert "BB-777" in out
    assert "CA-1" in out
    assert "BrainBit" in out
    assert "Callibri" in out
    assert backend.closed


def test_scan_nothing_found(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--scan"], backend_factory=factory_for(FakeBackend())) == 0
    assert "не найдены" in capsys.readouterr().out


def test_scan_without_bluetooth_exits_3(capsys: pytest.CaptureFixture[str]) -> None:
    backend = FakeBackend()
    backend.check_error = BluetoothUnavailableError("Bluetooth-адаптер не найден")
    assert main(["--scan"], backend_factory=factory_for(backend)) == 3
    assert "Bluetooth" in capsys.readouterr().err
    assert backend.closed


def test_sdk_load_failure_exits_3(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    config = write_config(tmp_path, '[devices]\neeg = "BB1"\nemg = "C1"\n')

    def broken(scan_s: float) -> DeviceBackend:
        raise SdkUnavailableError("Не удалось загрузить NeuroSDK")

    assert main(["--config", str(config)], backend_factory=broken) == 3
    assert "NeuroSDK" in capsys.readouterr().err
    assert main(["--scan"], backend_factory=broken) == 3


def test_hardware_without_bluetooth_exits_3(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    config = write_config(tmp_path, '[devices]\nemg_left = "L"\nemg_right = "R"\n')
    backend = FakeBackend()
    backend.check_error = BluetoothUnavailableError("Bluetooth-адаптер не найден или выключен")
    code = main(
        ["--profile", "pong", "--config", str(config)], backend_factory=factory_for(backend)
    )
    assert code == 3
    assert "Bluetooth" in capsys.readouterr().err
    assert backend.closed
    assert backend.open_calls == []


def test_scan_json_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    backend = FakeBackend([FakeRawSensor("brainbit", "BB-777"), FakeRawSensor("callibri", "CA-1")])
    assert main(["--scan", "--json"], backend_factory=factory_for(backend)) == 0
    from neurotlon_bridge.__main__ import SCAN_JSON_MARK

    out = capsys.readouterr().out
    line = next(line for line in out.splitlines() if line.startswith(SCAN_JSON_MARK))
    data = json.loads(line[len(SCAN_JSON_MARK) :])
    assert {item["serial"] for item in data} == {"BB-777", "CA-1"}
    assert {item["kind"] for item in data} == {"brainbit", "callibri"}
    assert all(set(item) == {"kind", "name", "serial", "address"} for item in data)


class _RecordingServer:
    """Подмена BridgeServer: запоминает аргументы и сразу завершает работу."""

    instances: list[_RecordingServer] = []  # noqa: RUF012 - тестовая подмена

    def __init__(self, source: object, **kwargs: object) -> None:
        self.kwargs = kwargs
        _RecordingServer.instances.append(self)

    async def serve_forever(self) -> None:
        return None


@pytest.fixture
def recording_server(monkeypatch: pytest.MonkeyPatch) -> list[_RecordingServer]:
    _RecordingServer.instances = []
    monkeypatch.setattr("neurotlon_bridge.__main__.BridgeServer", _RecordingServer)
    return _RecordingServer.instances


def test_eeg_method_defaults_to_alpha_and_rejects_unknown() -> None:
    assert build_parser().parse_args([]).eeg_method == "alpha"
    assert build_parser().parse_args(["--eeg-method", "emotions"]).eeg_method == "emotions"
    with pytest.raises(SystemExit):
        main(["--emulate", "--eeg-method", "fft"])


@pytest.mark.parametrize("method", ["alpha", "emotions"])
def test_emulator_announces_eeg_method(
    recording_server: list[_RecordingServer], method: str
) -> None:
    assert main(["--emulate", "--headless", "--eeg-method", method]) == 0
    assert recording_server[0].kwargs["eeg_method"] == method


def test_emulator_default_method_is_alpha(recording_server: list[_RecordingServer]) -> None:
    assert main(["--emulate", "--headless"]) == 0
    assert recording_server[0].kwargs["eeg_method"] == "alpha"


@pytest.mark.parametrize("method", ["alpha", "emotions"])
def test_hardware_passes_method_to_source_and_server(
    recording_server: list[_RecordingServer],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    method: str,
) -> None:
    seen: list[object] = []
    real = hardware_source.HardwareSource

    class Recording(real):  # type: ignore[valid-type, misc]
        def __init__(self, *args: object, **kwargs: object) -> None:
            seen.append(kwargs.get("eeg_method"))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(hardware_source, "HardwareSource", Recording)
    config = write_config(tmp_path, '[devices]\neeg = "BB1"\nemg = "C1"\n')
    backend = FakeBackend([FakeRawSensor("brainbit", "BB1"), FakeRawSensor("callibri", "C1")])
    code = main(
        ["--headless", "--config", str(config), "--eeg-method", method],
        backend_factory=factory_for(backend),
    )
    assert code == 0
    assert seen == [method]
    assert recording_server[0].kwargs["eeg_method"] == method
