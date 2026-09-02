# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2026 Aswanth B S

"""The demo server, shipped with the package.

Needs the ``web`` extra::

    pip install "docx-redline[web]"
    docx-redline serve

Imported lazily -- ``import docx_redline`` must not require FastAPI, so nothing
here is re-exported from the top-level package.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # for type checkers and linters; never imported at runtime
    from .main import app, serve

__all__ = ["app", "serve"]


def __getattr__(name: str):
    if name in __all__:
        from .main import app, serve

        return {"app": app, "serve": serve}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
