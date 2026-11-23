"""Automated Design System static guard test (P3-A6)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GUARD_PATH = REPO_ROOT / "docs" / "design-rules" / "tokens_guard.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location("tokens_guard", GUARD_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_design_tokens_guard_zero_violations() -> None:
    guard = _load_guard()
    violations = guard.run_check()
    assert violations == [], f"Design token violations found: {violations}"
