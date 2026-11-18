from pathlib import Path

import pytest

from neurotlon_bridge.__main__ import main
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
