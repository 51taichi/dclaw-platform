import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import fetch_developer_pack as fetch  # noqa: E402


def make_pack(path, *, prefix="developer-pack/", member="README.md", extra=None):
    payload = b"developer pack fixture"
    digest = hashlib.sha256(payload).hexdigest()
    manifest = {
        "version": "1.10.14",
        "devkit_version": "1.9.7",
        "standard": {"version": "2.38"},
        "files": [{"path": member, "sha256": digest, "size_bytes": len(payload)}],
    }
    manifest_bytes = json.dumps(manifest).encode("utf-8")
    sums = (
        f"{hashlib.sha256(manifest_bytes).hexdigest()}  PACKAGE-MANIFEST.json\n"
        f"{digest}  {member}\n"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(prefix + "PACKAGE-MANIFEST.json", manifest_bytes)
        archive.writestr(prefix + "SHA256SUMS", sums)
        archive.writestr(prefix + member, payload)
        if extra:
            archive.writestr(prefix + extra, b"unlisted")
    return {"version": "1.10.14", "devkit_version": "1.9.7",
            "standard": {"version": "2.38"}, "archive_prefix": prefix.rstrip("/")}


class FetchDeveloperPackTests(unittest.TestCase):
    def test_rejects_non_origin_base_urls_before_network_access(self):
        for url in ("https://example.invalid/#fragment", "https://user:secret@example.invalid"):
            with self.subTest(url=url), \
                    mock.patch.object(sys, "argv", ["fetch_developer_pack.py", "--base-url", url,
                                                    "--output-dir", "unused"]), \
                    mock.patch.object(fetch, "request_json") as request:
                with self.assertRaises(SystemExit):
                    fetch.main()
                request.assert_not_called()

    def test_valid_pack_verifies_all_listed_files(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory) / "pack.zip"
            metadata = make_pack(path)
            self.assertEqual(fetch.verify_pack(path, metadata)["files_verified"], 1)

    def test_rejects_drive_absolute_archive_prefix(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory) / "pack.zip"
            metadata = make_pack(path, prefix="C:/")
            with self.assertRaisesRegex(ValueError, "unsafe"):
                fetch.verify_pack(path, metadata)

    def test_rejects_backslash_member(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory) / "pack.zip"
            metadata = make_pack(path, member="sub\\script.py")
            with self.assertRaisesRegex(ValueError, "unsafe|invalid"):
                fetch.verify_pack(path, metadata)

    def test_rejects_unlisted_member(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory) / "pack.zip"
            metadata = make_pack(path, extra="unlisted.txt")
            with self.assertRaisesRegex(ValueError, "outside package manifest"):
                fetch.verify_pack(path, metadata)


if __name__ == "__main__":
    unittest.main()
