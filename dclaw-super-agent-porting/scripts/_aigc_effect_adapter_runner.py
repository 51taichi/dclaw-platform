#!/usr/bin/env python3
"""Execute a project adapter and attest that it called the current runtime file."""

import argparse
import io
import json
import runpy
import sys
from contextlib import redirect_stdout
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--entry", required=True)
    parser.add_argument("--case", required=True)
    args = parser.parse_args()
    target = args.runtime.resolve()
    function_calls = 0

    def profile(frame, event, _arg):
        nonlocal function_calls
        if (event == "call" and frame.f_code.co_name != "<module>"
                and Path(frame.f_code.co_filename).resolve() == target):
            function_calls += 1

    stdout = io.StringIO()
    sys.argv = [str(args.adapter), "--runtime", str(args.runtime),
                "--entry", args.entry, "--case", args.case]
    try:
        sys.setprofile(profile)
        with redirect_stdout(stdout):
            runpy.run_path(str(args.adapter), run_name="__main__")
    finally:
        sys.setprofile(None)
    if stdout.tell() > 32768:
        return 1
    observation = json.loads(stdout.getvalue())
    print(json.dumps({"runtime_function_calls": function_calls,
                      "observation": observation}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
