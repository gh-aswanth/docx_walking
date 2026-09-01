# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2026 Aswanth B S

"""``python -m docx_redline`` -- and also ``python docx_redline/__main__.py``.

Run as a module the package is already imported, so a relative import would do.
Run as a bare file path it is not: ``sys.path[0]`` is this directory rather than
the project root, ``__package__`` is empty, and ``from .cli import ...`` fails
with "attempted relative import with no known parent package". Putting the
project root on the path first makes both entry points work.
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

# Pick up ANTHROPIC_API_KEY / OPENAI_API_KEY from a local .env, so the
# model-backed reviewers work without exporting anything by hand.
load_dotenv()

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docx_redline.cli import _entry  # noqa: E402  -- must follow the sys.path fix above

_entry()
