"""Build the reproducible platform FFmpeg capability artifact."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import zipfile


ROOT = Path(__file__).resolve().parent
MEMBERS = ("runner.py", "input.schema.json", "result.schema.json", "checkpoint.schema.json")


def build(target: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member in MEMBERS:
            info = zipfile.ZipInfo(member, (2026, 11, 15, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (ROOT / member).read_bytes())
    return hashlib.sha256(target.read_bytes()).hexdigest()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: build_artifact.py OUTPUT.zip")
    print(build(Path(sys.argv[1])))
