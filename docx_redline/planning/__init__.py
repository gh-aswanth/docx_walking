# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2026 Aswanth B S

"""Deciding edits: the action-item vocabulary, the planner that derives their
consequences, the reviewers that propose them, and the staged pipeline.

This layer decides *what* to change; :mod:`docx_redline.editing` does it.
"""
