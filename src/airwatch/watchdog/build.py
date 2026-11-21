"""Build the watchdog Lambda's zip (#16, T9; D-041): `uv run python -m airwatch.watchdog.build`.

The zip holds `handler.py` at its root, plus the packages in `requirements/watchdog.txt` (boto3
and tzdata at uv.lock's versions, hash-checked), installed as wheels for Lambda's Linux arm64
Python 3.12. AWS recommends shipping the SDK rather than relying on the runtime's copy, and the
bundled tzdata means Chicago dates don't depend on the image's time-zone files.

The zip is reproducible: sorted entries, fixed timestamps and modes, no bytecode. The same sources
give the same bytes, so `terraform plan` shows no change until the code or the lock changes.
"""

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from airwatch.watchdog import handler

__all__ = ["HANDLER_MODULE", "OUT", "REQUIREMENTS", "build", "install_command", "write_zip"]

ROOT = Path(__file__).resolve().parents[3]
REQUIREMENTS = ROOT / "requirements" / "watchdog.txt"
OUT = ROOT / "infra" / "build" / "watchdog.zip"
HANDLER_MODULE = "handler.py"
PLATFORM = "aarch64-manylinux2014"
PYTHON = "3.12"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
FILE_MODE = 0o100644
SCRIPTS_DIR = "bin"


def install_command(target: Path) -> list[str]:
    """`uv pip install` for the Lambda's platform, wheels only, every hash checked."""
    return [
        "pip",
        "install",
        "--target",
        str(target),
        "--require-hashes",
        "--no-deps",
        "--only-binary",
        ":all:",
        "--python-platform",
        PLATFORM,
        "--python-version",
        PYTHON,
        "-r",
        str(REQUIREMENTS),
    ]


def _shipped(rel: Path) -> bool:
    """Not bytecode, and not the console scripts pip puts in a top-level bin/."""
    return "__pycache__" not in rel.parts and rel.suffix != ".pyc" and rel.parts[0] != SCRIPTS_DIR


def _files(root: Path) -> list[Path]:
    found = (p for p in root.rglob("*") if p.is_file() and _shipped(p.relative_to(root)))
    return sorted(found, key=lambda p: p.relative_to(root).as_posix())


def write_zip(root: Path, out: Path) -> str:
    """Zip `root` reproducibly into `out`; returns the zip's SHA-256."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in _files(root):
            info = zipfile.ZipInfo(path.relative_to(root).as_posix(), date_time=FIXED_TIME)
            info.external_attr = FILE_MODE << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, path.read_bytes(), compresslevel=9)
    return hashlib.sha256(out.read_bytes()).hexdigest()


def build(out: Path = OUT) -> str:
    """Install the locked packages, add the handler, zip; returns the zip's SHA-256."""
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv must be on PATH")
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "package"
        subprocess.run(  # noqa: S603  (uv from PATH, fixed arguments, no user input)
            [uv, *install_command(staging)], check=True, capture_output=True
        )
        shutil.copyfile(handler.__file__, staging / HANDLER_MODULE)
        return write_zip(staging, out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT, help=f"zip path (default {OUT})")
    args = parser.parse_args(argv)
    sha = build(args.out)
    size_kb = args.out.stat().st_size // 1024
    print(f"{args.out} ({size_kb} KiB) sha256 {sha}")  # noqa: T201
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
