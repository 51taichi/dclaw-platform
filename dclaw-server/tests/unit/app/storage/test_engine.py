# -*- coding: utf-8 -*-
from __future__ import annotations

from qwenpaw.app.storage.engine import create_engine_from_settings, db_dialect_name
from qwenpaw.app.storage.settings import get_storage_settings


def test_sqlite_engine_applies_pragmas(tmp_path):
    settings = get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "qwenpaw.db")})
    engine = create_engine_from_settings(settings)

    with engine.connect() as conn:
        assert db_dialect_name(engine) == "sqlite"
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() >= 5000
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
