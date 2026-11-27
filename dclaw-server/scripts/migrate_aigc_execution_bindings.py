#!/usr/bin/env python3
"""Offline binding migration. Stop application writers; dry-run by default."""

import argparse
import json
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from qwenpaw.app.super_experts.binding_migration import migrate_bindings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-root", type=Path, required=True,
                        help="Directory containing aigc_material_tasks.json")
    parser.add_argument("--studio-root", type=Path, required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--apply", action="store_true", help="Write core bindings; default is read-only")
    args = parser.parse_args()
    engine = None
    try:
        url = make_url(args.database_url)
        if url.get_backend_name() == "sqlite":
            # Connecting to a nonexistent SQLite path creates a file, even for
            # a preview. Require a real, previously initialized database.
            if not url.database or not Path(url.database).is_file():
                raise ValueError("SQLITE_DATABASE_MISSING")
        elif url.get_backend_name() != "postgresql":
            raise ValueError("DATABASE_BACKEND_UNSUPPORTED")
        engine = create_engine(url)
        result = migrate_bindings(legacy_root=args.legacy_root, studio_root=args.studio_root,
                                  engine=engine, apply=args.apply)
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result["conflicts"] else 0
    except Exception as exc:
        safe = {"SQLITE_DATABASE_MISSING", "CORE_SCHEMA_NOT_INITIALIZED", "DATABASE_BACKEND_UNSUPPORTED",
                "LEGACY_TASK_STORE_MISSING", "LEGACY_TASK_STORE_INVALID"}
        print(str(exc) if str(exc) in safe else "MIGRATION_FAILED", file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
