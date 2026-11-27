#!/usr/bin/env python3
"""Check the local Python environment used by diagnostic scripts."""

from importlib.metadata import PackageNotFoundError, version
import os
import re
import sys


def main():
    if sys.prefix == sys.base_prefix and not os.environ.get("CONDA_PREFIX"):
        raise ValueError("use a project-isolated Python environment")
    try:
        installed = version("jsonschema")
        from jsonschema import Draft202012Validator, FormatChecker
    except (ImportError, PackageNotFoundError) as exc:
        raise ValueError("install jsonschema[format]>=4.20,<5 in this environment") from exc
    match = re.match(r"^(\d+)\.(\d+)(?:\.|$)", installed)
    if not match or not (4, 20) <= tuple(map(int, match.groups())) < (5, 0):
        raise ValueError(f"jsonschema {installed} is outside the supported range >=4.20,<5")
    Draft202012Validator.check_schema({"$schema": "https://json-schema.org/draft/2020-12/schema"})
    if not FormatChecker().conforms("2026-11-13T10:36:21Z", "date-time"):
        raise ValueError("jsonschema date-time format validation is unavailable")
    print(f"Diagnostics Python ready: {sys.executable} (jsonschema {installed})")


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        raise SystemExit(
            f"Local diagnostics environment not ready: {exc}. "
            "See references/python-environment.md; this is not a DClaw platform-contract error. "
            f"Interpreter: {sys.executable}"
        )
