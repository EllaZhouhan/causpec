#!/usr/bin/env python3
"""Entry point for calling causpec from the skill form.

Mirrors design.md section 3. There is no MCP server on claude.ai, so the skill goes
through this script. Both forms call the same causpec functions and produce the same
run-directory layout; the manifest records execution_mode as skill.

**This path is best-effort.** An agent is technically able to bypass this script and
compute things from the data itself, so in skill form "only code produces numbers"
rests on the agent following the rules rather than on the framework enforcing them.
The report header notes this. MCP form does not have the problem: there the model can
only reach the data through declared tools.

The practical problem this script solves is that the sandbox may not have causpec
installed. In order:

1. Already importable -> use it
2. A wheel sits in the sibling ``assets/`` -> put it on sys.path (a pure-Python wheel
   is a zip and imports directly), leaving the system environment alone
3. Still not importable -> pip install that wheel
4. Still failing -> say what is missing and how to install it, rather than raising an
   ImportError traceback

Usage matches the causpec CLI exactly::

    python scripts/run.py quality  --spec spec.yaml --data cohort.csv
    python scripts/run.py estimate --spec spec.yaml --data cohort.csv --report
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
ASSETS = SKILL_ROOT / "assets"

INSTALL_HINT = """\
Cannot load causpec.

The skill package should contain a wheel at assets/causpec-*.whl. If it does not,
build one from the repository root:

    uv build --wheel
    cp dist/causpec-*.whl skill/causpec-analyst/assets/

Estimation additionally needs causpec[hte] (econml, scikit-learn). When that cannot be
installed in the sandbox, the quality checks and report rendering still work but
estimation does not, say so plainly rather than computing a number some other way.
"""


def _bundled_wheel() -> Path | None:
    wheels = sorted(ASSETS.glob("causpec-*.whl"))
    return wheels[-1] if wheels else None


def _importable() -> bool:
    try:
        import causpec  # noqa: F401
    except ImportError:
        return False
    return True


def ensure_causpec() -> None:
    """Make ``causpec`` importable, explaining what to do if it cannot be."""
    if _importable():
        return

    wheel = _bundled_wheel()
    if wheel is None:
        raise SystemExit(INSTALL_HINT)

    # A pure-Python wheel is a zip: putting it on sys.path is enough to import from,
    # and it leaves the system environment untouched.
    sys.path.insert(0, str(wheel))
    if _importable():
        return

    # Only install for real when the dependencies are incomplete. --no-input keeps it
    # from hanging in a non-interactive environment.
    sys.path.pop(0)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-input", "--quiet", str(wheel)],
        capture_output=True,
        text=True,
        check=False,
    )
    if not _importable():
        detail = (result.stderr or result.stdout).strip()
        raise SystemExit(f"{INSTALL_HINT}\npip output:\n{detail[-2000:]}")


def main(argv: list[str] | None = None) -> int:
    ensure_causpec()
    from causpec.cli import main as cli_main

    return cli_main(argv if argv is not None else sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
