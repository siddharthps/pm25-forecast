"""The docs macros (T11, D-016, D-044): `results/results.json` becomes the `results` variable.

Zensical's native macros extension imports this module (`modules` in `zensical.toml`) and calls
`define_env` once per page. Pages write `{{ results.design.variants }}`. A result that is still
null shows as *(pending)*, so no filter is needed (a filter's `|` would break a table row).
"""

import json
from pathlib import Path
from typing import Any

RESULTS = Path("results") / "results.json"
PENDING = "*(pending)*"


def for_display(value: object) -> object:
    if isinstance(value, dict):
        return {key: for_display(item) for key, item in value.items()}
    if isinstance(value, list):
        return [for_display(item) for item in value]
    return PENDING if value is None else value


def define_env(env: Any) -> None:
    path = Path(env.project_dir) / RESULTS
    env.variables["results"] = for_display(json.loads(path.read_text(encoding="utf-8")))
