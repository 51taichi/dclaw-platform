#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Preview or apply the one-time historical shadow-charge backfill."""
from __future__ import annotations

import argparse
import json

from qwenpaw.app.billing.shadow_backfill import ShadowChargeBackfill
from qwenpaw.app.storage.engine import get_app_engine


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="commit ledger charges; without this flag the command is read-only",
    )
    args = parser.parse_args()
    result = ShadowChargeBackfill(get_app_engine()).run(apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
