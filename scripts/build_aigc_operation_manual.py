from __future__ import annotations

import argparse
from pathlib import Path

from qwenpaw.aigc.operation_contract import (
    build_operation_manual,
    load_operation_catalog,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--manual-out", type=Path, required=True)
    parser.add_argument("--catalog-out", type=Path, required=True)
    args = parser.parse_args()
    catalog = load_operation_catalog(args.contract)
    build_operation_manual(catalog, args.manual_out, args.catalog_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
