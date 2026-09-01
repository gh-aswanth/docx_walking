# Contributing

## The short version

`docx-redline` is [MPL-2.0](LICENSE). That means:

- **Use it in your product, commercial or not.** No fee, no permission, no
  obligation to open-source your own code.
- **Files you add are yours.** Code that merely *calls* this library stays
  entirely under whatever licence you like.
- **Files of ours you modify stay open.** If you change a file under
  `docx_redline/`, that file's modified source has to be available under
  MPL-2.0 to whoever you ship the result to.

That last point is the only obligation, and it is per *file* — not per project.

## Please send the change upstream

The licence obliges you to publish a modified file. It does not oblige you to
send it here, and we would rather you did.

If you have had to patch `docx_redline/` to make it work, that is a bug report
with the fix already attached. Opening a PR means you stop carrying the patch
across upgrades, and the next person hits a library that already works. Both
sides come out ahead of a fork nobody can see.

## What a good PR looks like

1. **A failing test first.** Every fix in `tests/` corresponds to a defect that
   reported success while doing the wrong thing. Add the case that catches
   yours, then fix it.
2. **Both directions asserted.** `accept_all()` and `reject_all()` are how this
   library proves correctness without a copy of Word. A redline is only right if
   accepting it produces the intended document *and* rejecting it restores the
   original.
3. **The whole gate green.**

   ```bash
   uv sync
   uv run pre-commit install
   uv run pre-commit run --all-files
   ```

   That runs ruff (lint + format), isort, mypy, `uv lock --check`, the 350-test
   suite, and all 26 examples. All of it must pass.
4. **Examples stay honest.** `examples/` is executable documentation. If you
   change an option, update the example that demonstrates it —
   `python examples/run_all.py` fails the build if one stops running.

## Layout

Four subpackages, strictly layered, and a test asserts it. Each may import
downward and never up:

```
oxml  ->  structure  ->  editing  ->  planning  ->  cli
```

If a change needs an upward import, that is a sign the code is in the wrong
layer — see the `allowed_types` move in the git history for what the fix
usually looks like.

## New files

Add the Exhibit A notice at the top of anything new under `docx_redline/`:

```python
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
```

By opening a PR you agree your contribution ships under MPL-2.0.
