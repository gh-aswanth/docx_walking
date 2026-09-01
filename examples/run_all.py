"""Run every example and report pass/fail.

    python examples/run_all.py            # run them all
    python examples/run_all.py -v         # ...and show each one's output
    python examples/run_all.py 12 13      # just these

Exits non-zero if any example fails, so it works as a CI gate: every example
here is executable documentation, and an example that stops running is a README
that has started lying.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def examples() -> list[Path]:
    return sorted(p for p in HERE.glob("[0-9][0-9]_*.py"))


def main(argv: list[str]) -> int:
    verbose = "-v" in argv or "--verbose" in argv
    wanted = [a for a in argv if a.isdigit() or (a.endswith(".py") and not a.startswith("-"))]

    scripts = examples()
    if wanted:
        scripts = [
            s
            for s in scripts
            if s.name in wanted or s.name.split("_")[0] in {w.zfill(2) for w in wanted}
        ]

    failures: list[tuple[str, str]] = []
    print(f"running {len(scripts)} example(s)\n")
    for script in scripts:
        started = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, str(script)], cwd=HERE, capture_output=True, text=True
        )
        elapsed = time.perf_counter() - started
        ok = proc.returncode == 0
        print(f"  [{'PASS' if ok else 'FAIL'}] {script.name:<34} {elapsed:5.2f}s")
        if verbose:
            print("\n".join("        " + line for line in proc.stdout.splitlines()))
        if not ok:
            failures.append((script.name, (proc.stderr or proc.stdout).strip()))

    print(f"\n{len(scripts) - len(failures)} passed, {len(failures)} failed")
    for name, detail in failures:
        print(f"\n--- {name} ---\n{detail[-1200:]}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
