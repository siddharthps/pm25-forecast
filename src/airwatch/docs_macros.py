"""The docs macros (T11, D-016): `results/results.json` becomes the `results` variable.

Zensical's native macros extension imports this module (`modules` in `zensical.toml`) and calls
`define_env` once per page. Pages write `{{ results.design.variants }}`, or
`{{ results.headline.mae | show }}` for a value that is still null until its result exists.
"""

import json
from pathlib import Path
from typing import Any

RESULTS = Path("results") / "results.json"
PENDING = "*(pending)*"


def show(value: object) -> str:
    return PENDING if value is None else str(value)


def define_env(env: Any) -> None:
    path = Path(env.project_dir) / RESULTS
    env.variables["results"] = json.loads(path.read_text(encoding="utf-8"))
    env.filters["show"] = show
