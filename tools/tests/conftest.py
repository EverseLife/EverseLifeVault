# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Fixtures for the build's own tests.

The build is imported as a module, not run: what these tests check is the rule
inside it, on documents small enough to read in one screen. The real vault is
checked by `python tools/build.py --check`, and that is a different question --
whether the data is sound, not whether the rule is.
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
