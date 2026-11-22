"""The watchdog's zip (#16, T9; D-041): lock-exact packages, for Lambda's platform, reproducible.

The fast tests check the requirements file and the zip writer offline; the `slow` test runs the
real build twice (it needs uv's cache or the network).
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

from airwatch.devtools import uv_lock_pr
from airwatch.watchdog import build

ROOT = Path(__file__).resolve().parents[3]
EXPORT = [
    "uv",
    "export",
    "--frozen",
    "--only-group",
    "watchdog",
    "--no-emit-project",
    "--no-header",
    "--format",
    "requirements.txt",
]
TERRAFORM = (ROOT / "infra" / "watchdog.tf").read_text(encoding="utf-8")


def test_the_requirements_file_matches_uv_lock() -> None:
    uv = shutil.which("uv")
    assert uv, "uv must be on PATH"
    out = subprocess.run(
        [uv, *EXPORT[1:]], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    assert build.REQUIREMENTS.read_text(encoding="utf-8") == out, (
        "regenerate: " + " ".join(EXPORT) + " > requirements/watchdog.txt"
    )


def test_it_ships_only_boto3_and_tzdata_pinned_and_hashed() -> None:
    text = build.REQUIREMENTS.read_text(encoding="utf-8")
    pins = set(re.findall(r"^([A-Za-z0-9_.-]+)==\S+", text, flags=re.MULTILINE))
    assert {"boto3", "botocore", "tzdata"} <= pins
    assert not pins & {"airwatch", "prefect", "pandas", "httpx"}
    blocks = re.split(r"\n(?=[A-Za-z0-9_.-]+==)", text.strip())
    assert all("--hash=sha256:" in b for b in blocks)


def test_the_weekly_lock_upgrade_regenerates_it_too() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "uv-lock-upgrade.yml").read_text(encoding="utf-8")
    )
    runs = [str(s.get("run", "")) for job in workflow["jobs"].values() for s in job["steps"]]
    assert " ".join(EXPORT) + " > requirements/watchdog.txt" in [r.strip() for r in runs]
    assert "requirements/watchdog.txt" in uv_lock_pr.FILES
    assert any("src/airwatch/devtools/uv_lock_pr.py" in r for r in runs)


def test_the_install_is_hash_checked_and_for_lambdas_platform(tmp_path: Path) -> None:
    cmd = build.install_command(tmp_path)
    assert cmd[:2] == ["pip", "install"]
    for flag in ("--require-hashes", "--no-deps"):
        assert flag in cmd
    assert cmd[cmd.index("--only-binary") + 1] == ":all:"
    assert cmd[cmd.index("--target") + 1] == str(tmp_path)
    assert cmd[cmd.index("-r") + 1] == str(build.REQUIREMENTS)
    platform = cmd[cmd.index("--python-platform") + 1]
    python = cmd[cmd.index("--python-version") + 1]
    assert platform.startswith("aarch64-")
    assert re.search(r'architectures\s*=\s*\["arm64"\]', TERRAFORM)
    assert re.search(rf'runtime\s*=\s*"python{re.escape(python)}"', TERRAFORM)
    project = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    assert python == ".".join(project.split(".")[:2])


def test_the_lambda_handler_setting_names_the_zipped_module() -> None:
    assert re.search(rf'handler\s*=\s*"{build.HANDLER_MODULE[:-3]}\.lambda_handler"', TERRAFORM)


def _tree(root: Path, mtime: int) -> None:
    for rel, body in {
        "handler.py": b"x = 1\n",
        "boto3/__init__.py": b"",
        "boto3/__pycache__/__init__.cpython-312.pyc": b"junk",
        "tzdata/zoneinfo/America/Chicago": b"TZif",
        "bin/jp.py": b"#!python\n",
        ".lock": b"",
    }.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        os.utime(path, (mtime, mtime))


def test_the_zip_is_reproducible_and_clean(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _tree(a, 1_700_000_000)
    _tree(b, 1_800_000_000)
    sha_a = build.write_zip(a, tmp_path / "a.zip")
    sha_b = build.write_zip(b, tmp_path / "b.zip")
    assert sha_a == sha_b == hashlib.sha256((tmp_path / "a.zip").read_bytes()).hexdigest()
    with zipfile.ZipFile(tmp_path / "a.zip") as z:
        names = z.namelist()
        infos = z.infolist()
    assert names == sorted(names)
    assert names == ["boto3/__init__.py", "handler.py", "tzdata/zoneinfo/America/Chicago"]
    assert {i.date_time for i in infos} == {(1980, 1, 1, 0, 0, 0)}
    assert {i.external_attr >> 16 for i in infos} == {0o100644}


@pytest.mark.slow
def test_the_real_build_is_reproducible_and_importable(tmp_path: Path) -> None:
    first = build.build(tmp_path / "one.zip")
    second = build.build(tmp_path / "two.zip")
    assert first == second
    unpacked = tmp_path / "unpacked"
    with zipfile.ZipFile(tmp_path / "one.zip") as z:
        names = set(z.namelist())
        z.extractall(unpacked)
    assert {"handler.py", "boto3/__init__.py", "tzdata/zoneinfo/America/Chicago"} <= names
    probe = (
        "import sys; sys.path.insert(0, sys.argv[1]); import handler, boto3; "
        "from zoneinfo import ZoneInfo; import tzdata; "
        "assert handler.__file__.startswith(sys.argv[1]); "
        "assert boto3.__file__.startswith(sys.argv[1]); print('ok')"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", probe, str(unpacked)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert done.stdout.strip() == "ok"


def test_the_command_line_builds_and_reports_the_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "w.zip"

    def fake_build(path: Path) -> str:
        path.write_bytes(b"z" * 2048)
        return "abc123"

    monkeypatch.setattr(build, "build", fake_build)
    assert build.main(["--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "abc123" in printed and "2 KiB" in printed


def test_the_build_needs_uv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("airwatch.watchdog.build.shutil.which", lambda _: None)
    with pytest.raises(RuntimeError, match="uv"):
        build.build(tmp_path / "w.zip")
