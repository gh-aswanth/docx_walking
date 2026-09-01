# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2026 Aswanth B S

"""Exception hierarchy, kept in its own module so every layer can share it."""

from __future__ import annotations


class RedlineError(RuntimeError):
    """Base class: a requested edit could not be located or applied."""


class ClauseError(RedlineError):
    """A clause number could not be resolved against the document."""


class StalePlanError(RedlineError):
    """A redline plan was computed against a different version of the document."""
