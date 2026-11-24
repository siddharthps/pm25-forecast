# Development

The one home for the project's commands. `CLAUDE.md` imports this file, so agent sessions and
people read the same copy.

Run every command from the project folder (`cd ~/code/pm25-forecast`). Scripts that change
anything outside this PC are dry runs unless given `--apply`. Keys live in the gitignored `.env`
(names in [.env.example](.env.example); register in [notes/TOKENS.md](notes/TOKENS.md)).

## Checks

```bash
uv sync --frozen                       # install exactly what uv.lock says
uv run ruff check . && uv run ruff format --check .
uv run mypy                            # strict; config in pyproject.toml
uv run pytest                          # fast offline core suite, 4 workers (D-035; goal: median of 3 quiet runs under 30 s, D-057; -n 0 = serial); -m slow / -m live are opt-in
SUITE_BUDGET_S=75 uv run pytest        # as CI does: fails if the run takes over 75 s (D-046)
uv run pytest tests/property --hypothesis-profile=explore   # fresh random search (default is derandomized)
uv run pre-commit run --all-files      # every hook: gitleaks, markdownlint, Vale, Biome, docs check, terraform fmt
node --test tests/site/                # the page's JavaScript tests (Node from .nvmrc)
terraform -chdir=infra test            # infra safety rules on the plan, mock AWS provider, offline
```

## The write-up (docs)

```bash
uv run --group docs zensical build --strict  # build docs/ into site_build/; fails on undefined macros, broken links or anchors
uv run --group docs zensical serve     # preview at http://localhost:8000 while editing
uv run python -m airwatch.devtools.docs_check  # typed numbers, unresolved macros, page length (D-022)
uv run pre-commit run vale --all-files # the style sheet's banned words (notes/STYLE.md)
```

CI also runs lychee over `site_build/` as the separate link and anchor checker (D-016).

## Mutation testing (Linux only: WSL or CI; D-048)

mutmut needs `fork`, so on this PC it runs in WSL, from a clone in the Linux home folder (the
Windows `.venv` can't be shared, and `/mnt/c` is slow). WSL's uv must meet the pyproject floor;
if it doesn't, prefix each `uv` with `uvx --from uv==<floor>`. The paths it mutates are in
`pyproject.toml`'s `[tool.mutmut]`: add a module by extending `only_mutate`.

```bash
uv sync --frozen && uv run mutmut run  # in WSL; about 2 min for timeutil, config and weather.leads
uv run mutmut results                  # every mutant not killed; `uv run mutmut show <name>` for one
gh workflow run mutmut.yml --ref <branch>  # the same on GitHub (UTC); results in the run's summary
```

Each survivor is killed by a new test or explained in the journal. Run it after changing a
mutated module, before its merge.

Started from Git Bash on Windows, `wsl.exe` drops the quotes inside a `bash -c "…"` command and
Git Bash rewrites `/mnt/c/…` paths. Put the commands in a script with Linux line endings and run
it as a login shell (WSL's `uv` is only on a login shell's path), with path rewriting off:

```bash
MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu -- bash -l /mnt/c/<path>/script.sh
```

## Data, forecast and AWS

```bash
aws sso login --profile pm25           # AWS access (never use long-lived keys); lasts 8 hours
uv run pytest -m live -o log_cli=true --log-cli-level=INFO   # opt-in real-API checks, counts only
AWS_PROFILE=pm25 uv run python scripts/aqs_bulk.py           # AQS history to S3: dry run; --apply acts
AWS_PROFILE=pm25 uv run python scripts/weather_bulk.py       # ERA5, GFS archive, CAMS history to S3 (paced): dry run; --apply acts
AWS_PROFILE=pm25 uv run python -m airwatch.weather.coverage  # every hour and value of that download (reads only; report in data/reports/weather/)
AWS_PROFILE=pm25 uv run python scripts/cams_gap.py            # D-052's CAMS gap, about 1 h (reads only; --days 2 to time it; data/reports/cams_gap/)
uv run python scripts/city_check.py    # the frozen D-006 city check (reads only; cached in data/)
AWS_PROFILE=pm25 uv run python -m airwatch.validation.report --source all  # D-033/D-054 report (reads only; AQS key from .env)
AWS_PROFILE=pm25 uv run python -m airwatch.forecast.run   # D+1 forecast: dry run; --publish acts
```

## Dependencies: the 7-day wait (D-056)

The weekly lock job (`uv-lock-upgrade.yml`, started by the watchdog on Mondays, D-058) takes
a release only once it is 7 days old. A local
`uv lock` keeps the locked versions, so it never undoes the wait.

- **Adding a package or raising a minimum:** pick a release at least 7 days old
  (`uv add "pkg>=<that version>"`). A newer minimum makes the job fail, and uv's error names it.
- **An urgent release** (a security fix inside the week):
  1. on a branch: `uv lock --upgrade-package <pkg>`, then both exports below, and a PR;
  2. in the same PR, append `--exclude-newer-package=<pkg>=false` to the job's `uv lock` line, or
     the next weekly run downgrades it (with `--upgrade` uv re-resolves under the cutoff);
  3. a week later, drop the exemption.

## After a `uv.lock` change, and before a Terraform plan

```bash
uv export --frozen --no-dev --no-emit-project --no-header --format requirements.txt > requirements/prefect-run.txt  # after any uv.lock change (D-040)
uv export --frozen --only-group watchdog --no-emit-project --no-header --format requirements.txt > requirements/watchdog.txt  # likewise (D-041)
uv run python -m airwatch.watchdog.build  # the watchdog Lambda's zip, into infra/build/, before any terraform plan (D-041)
```

Infrastructure lives in `infra/`. The owner runs `plan` and `apply`, following
[infra/README.md](infra/README.md). CI never has AWS credentials.
