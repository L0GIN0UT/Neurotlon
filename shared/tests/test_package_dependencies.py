import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def dependencies(package_dir: str) -> list[str]:
    data = tomllib.loads((ROOT / package_dir / "pyproject.toml").read_text(encoding="utf-8"))
    return [d.split(">")[0].split("=")[0].strip() for d in data["project"]["dependencies"]]


def test_launcher_does_not_depend_on_games() -> None:
    deps = dependencies("launcher")
    assert "neurotlon_games" not in deps
    assert "neurotlon_contracts" in deps


def test_contracts_depend_on_no_workspace_package() -> None:
    assert dependencies("shared/python") == ["jsonschema"]


def test_games_use_contracts_bridge_and_launcher() -> None:
    assert {"neurotlon_contracts", "neurotlon_bridge", "neurotlon_launcher"} <= set(
        dependencies("games")
    )
