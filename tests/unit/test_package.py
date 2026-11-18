"""The package installs and reports the version recorded in pyproject.toml."""

import tomllib
from importlib.metadata import version
from pathlib import Path

import airwatch

ROOT = Path(__file__).resolve().parents[2]


def test_version_matches_pyproject() -> None:
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert airwatch.__version__ == declared["version"] == version("airwatch")
