# Development

## The commands

```bash
uv sync --all-extras --dev   # everything
uv run pytest                # the whole suite
uv run ruff check .          # lint
uv run pyright               # types; CI pins Python 3.11
uv run lint-imports          # the architecture contract: core must not import a family
pre-commit install           # enable the pre-commit checks, including the data-file block
```

Data handling is in the README: the ignore rules, the pre-commit hook and the CI pass
over every tracked file. Synthetic data is generated on demand and its output is
gitignored, and the generators are documented in [data/README.md](../data/README.md).

**The tests are written to document properties, not to cover functions.** Each file opens
with what it is defending and why that matters, and several pin a mistake that was made
and corrected, so it cannot come back quietly: that a fill's spread statistic has to be
measured among the filled values rather than over the column, that a snapshot's
fingerprint has to be recomputable from the snapshot, that rounding a hash moves the
instability rather than removing it.

## Synthetic data

```bash
# Dataset A, with ground truth. What it produces is never committed.
uv run python data/generators/dataset_a.py --out /tmp/a.csv --preset realistic
uv run python data/generators/dataset_a.py --out /tmp/a.csv --preset high_power --instrument-kind binary
```

`realistic` matches the scale of the real ICU study (about 9.5% treated, about 4%
mortality) and is what demos and quality checks use. `high_power` raises the complier
share and event rate for numerical evals, at the realistic scale an IV analysis has a
standard error larger than the truth itself, and numerical tests drown in noise.
