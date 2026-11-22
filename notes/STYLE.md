# Style sheet: the write-up (D-022, D-044)

One page, covering `docs/` and the README. The checks named here enforce it in CI; a rule
that can't be checked is marked *(review)*.

## Docs or notes?

| Goes in `docs/` (published) | Goes in `notes/` (working records) |
| --- | --- |
| What was found, with its numbers, for a reader who wasn't there | How and when it was found: the journal |
| The method, at the level needed to trust the result | Every decision and its why: DECISIONS.md, cited as `D-0xx` |
| Limits and failures that change how far to trust a number | Traps, fixes, dead ends, tool trouble |

A docs page cites a decision by its ID and doesn't restate it. One home per fact; other pages
link to it.

## Readers

The bottom line and the README are for anyone: plain words, no unexplained terms. The chapters
are for a technical reader, with each term defined at first use *(review)*.

## Numbers

- **Never type a number into prose.** Each comes from `results/results.json` through a macro,
  such as `{{ results.design.variants }}`. A result that is still null shows *(pending)*.
- **Counts as words are numbers too:** "two" to "twelve" are banned in `docs/`
  (`styles/AirWatchDocs/NumberWords.yml`). "One" is allowed.
- **Allowed as typed text:** dates, years, clock times, decision and task IDs, issue numbers,
  `PM2.5`, `D+1`, versions with a `v`, list markers and link targets. The full list lives in
  `src/airwatch/devtools/docs_check.py`, which fails the build on anything else.
- **Charts are numbers:** each is drawn at build time from a data file in `results/`, never saved
  by hand.
- **Wins are verdicts, not adjectives:** a comparison with a baseline quotes the pipeline's
  verdict (`better`, `no clear difference` or `worse`, by D-045's rule). The prose never claims
  more than the verdict *(review, until the verdict text is checked)*.
- **Live numbers are dated:** quoted as of the snapshot date (`results.live.as_of`), with a link
  to the live page.

## Words

- **Banned words:** the list lives in `styles/AirWatch/Banned.yml` (Vale, an error in CI). They
  are hype or hedges that say nothing checkable. Replace each one with what happened and its
  number.
- **Absolute words** ("never", "every", "only", "always"): test each against the failure path (a
  retry, a late run, a missing day) before keeping it *(review)*.
- When tightening, keep a sentence that qualifies a nearby claim. Cutting it can turn a hedged
  claim into a false guarantee *(review)*.

## Page template

```markdown
# Title: what the page answers

!!! note "Skeleton"      ← only until the prose is written after the freeze

## The answer            ← the result first, with its macros
## How we know           ← the method, citing D-entries
## How far to trust it   ← limits, gaps, what would change the answer
## Where to look next    ← links to the pages that build on this one
```

## Length

- The bottom line (`docs/index.md`) has a 400-word cap, and any other page 1,000 words.
  `docs_check.py` holds the caps and fails the build above them.
- Line length 100 (markdownlint).

## When prose gets written

- Skeletons (headings, bullets, charts) may come early. Chapter prose comes only once its results
  are frozen (research freeze, 2026-12-23).
- Check every claim against the actual output before it goes into a title, caption or page.
  Look up every cited study; never quote research from memory *(review)*.
