"""Hermetic test fixtures: repoint the SQLite db at a temp file per test, so
tests never touch the real dashboard db and never hit the collector loop."""

import sys
from pathlib import Path

import pytest

# backend/ on path so `import db`, `import metrics`, `import config` resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import db  # noqa: E402


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "pentagon_db_path", str(tmp_path / "t.db"))
    db.reset_for_tests()
    db.init_db()
    yield
    db.reset_for_tests()
