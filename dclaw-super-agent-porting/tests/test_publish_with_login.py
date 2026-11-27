import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import publish_with_login  # noqa: E402


class PublishWithLoginTests(unittest.TestCase):
    def test_rejects_credentials_in_base_url_before_login(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            devkit = Path(directory) / "dclaw_agent_devkit.py"
            devkit.touch()
            argv = ["publish_with_login.py", "--base-url", "https://user:secret@example.invalid",
                    "--devkit", str(devkit), "list"]
            with mock.patch.object(sys, "argv", argv), mock.patch("builtins.input") as prompt:
                with self.assertRaises(SystemExit):
                    publish_with_login.main()
            prompt.assert_not_called()

    def test_rejects_output_alias_before_login(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            root = Path(directory)
            devkit = root / "dclaw_agent_devkit.py"
            package = root / "signed.zip"
            devkit.touch()
            package.touch()
            argv = ["publish_with_login.py", "--base-url", "https://example.invalid",
                    "--devkit", str(devkit), "--output", str(root / "receipt.json"),
                    "--readback-output", str(root / "sub" / ".." / "receipt.json"),
                    "upload", "--package", str(package)]
            with mock.patch.object(sys, "argv", argv), mock.patch("builtins.input") as prompt:
                with self.assertRaises(SystemExit):
                    publish_with_login.main()
            prompt.assert_not_called()

    def test_rejects_receipt_symlink_before_login(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            root = Path(directory)
            devkit = root / "dclaw_agent_devkit.py"
            devkit.touch()
            output = root / "receipt.json"
            argv = ["publish_with_login.py", "--base-url", "https://example.invalid",
                    "--devkit", str(devkit), "--output", str(output), "list"]
            original = Path.is_symlink
            with mock.patch.object(sys, "argv", argv), mock.patch("builtins.input") as prompt, \
                    mock.patch.object(Path, "is_symlink", autospec=True,
                                      side_effect=lambda path: path == output or original(path)):
                with self.assertRaises(SystemExit):
                    publish_with_login.main()
            prompt.assert_not_called()

    def test_receipt_created_during_publish_is_not_overwritten(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            root = Path(directory)
            devkit = root / "dclaw_agent_devkit.py"
            devkit.touch()
            receipt = root / "receipt.json"
            argv = ["publish_with_login.py", "--base-url", "https://example.invalid",
                    "--devkit", str(devkit), "--output", str(receipt), "list"]

            def create_conflicting_receipt(*args, **kwargs):
                receipt.write_text("original", encoding="utf-8")
                return {"items": []}

            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(publish_with_login.sys, "stdin") as stdin, \
                    mock.patch("builtins.input", return_value="developer"), \
                    mock.patch.object(publish_with_login.getpass, "getpass", return_value="secret"), \
                    mock.patch.object(publish_with_login, "request_json",
                                      side_effect=[{"token": "private-token"}, {}]), \
                    mock.patch.object(publish_with_login, "run_official_publish",
                                      side_effect=create_conflicting_receipt):
                stdin.isatty.return_value = True
                with self.assertRaises(FileExistsError):
                    publish_with_login.main()
            self.assertEqual(receipt.read_text(encoding="utf-8"), "original")

    def run_upload(self, outputs):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            root = Path(directory)
            devkit = root / "dclaw_agent_devkit.py"
            package = root / "signed.zip"
            receipt = root / "receipt.json"
            readback = root / "readback.json"
            devkit.touch()
            package.touch()
            argv = [
                "publish_with_login.py", "--base-url", "https://example.invalid",
                "--devkit", str(devkit), "--output", str(receipt),
                "--readback-output", str(readback), "upload", "--package", str(package),
            ]
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(publish_with_login.sys, "stdin") as stdin, \
                    mock.patch("builtins.input", return_value="developer"), \
                    mock.patch.object(publish_with_login.getpass, "getpass", return_value="secret"), \
                    mock.patch.object(publish_with_login, "request_json", side_effect=[{"token": "private-token"}, {}]), \
                    mock.patch.object(publish_with_login.subprocess, "run", side_effect=outputs) as run, \
                    mock.patch("builtins.print") as printed:
                stdin.isatty.return_value = True
                error = None
                try:
                    publish_with_login.main()
                except ValueError as exc:
                    error = exc
            receipt_data = json.loads(receipt.read_text(encoding="utf-8")) if receipt.exists() else None
            readback_data = json.loads(readback.read_text(encoding="utf-8")) if readback.exists() else None
            return receipt_data, readback_data, run.call_args_list, printed.call_args_list, error

    def test_non_ascii_upload_and_list_use_utf8(self):
        upload = subprocess.CompletedProcess([], 0, '{"name":"专家","version":"0.2.3"}'.encode("utf-8"), b"")
        listing = subprocess.CompletedProcess([], 0, '{"items":[{"name":"专家"}]}'.encode("utf-8"), b"")
        receipt, readback, calls, printed, error = self.run_upload([upload, listing])
        self.assertIsNone(error)
        self.assertEqual(receipt["name"], "专家")
        self.assertEqual(readback["items"][0]["name"], "专家")
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call.args[0].isascii() for call in printed))
        for call in calls:
            self.assertNotIn("text", call.kwargs)
            self.assertEqual(call.kwargs["env"]["PYTHONUTF8"], "1")
            self.assertEqual(call.kwargs["env"]["PYTHONIOENCODING"], "utf-8")

    def test_list_decode_failure_preserves_upload_receipt(self):
        upload = subprocess.CompletedProcess([], 0, b'{"version":"0.2.3"}', b"")
        listing = subprocess.CompletedProcess([], 0, b"\xff", b"")
        receipt, readback, calls, _, error = self.run_upload([upload, listing])
        self.assertEqual(receipt["version"], "0.2.3")
        self.assertIsNone(readback)
        self.assertEqual(len(calls), 2)
        self.assertIn("list after upload returned non-UTF-8 JSON", str(error))

    def test_non_json_success_requires_readback_before_upload_retry(self):
        upload = subprocess.CompletedProcess([], 0, b"completed without receipt", b"")
        receipt, readback, calls, printed, error = self.run_upload([upload])
        self.assertIsNone(receipt)
        self.assertIsNone(readback)
        self.assertEqual(len(calls), 1)
        self.assertFalse(printed)
        self.assertEqual(
            str(error),
            "official publish upload returned invalid JSON; check publish list before retrying upload",
        )
        self.assertNotIn("completed without receipt", str(error))

    def test_upload_failure_reports_only_http_and_state_category(self):
        body = {"detail": {"code": "state_format_mismatch", "message": "customer text private-token"}}
        stdout = json.dumps({
            "status": "invalid",
            "error": "Super Expert upload returned HTTP 409: " + json.dumps(body),
        }).encode("utf-8")
        failed = subprocess.CompletedProcess([], 1, stdout, b"")
        receipt, readback, calls, printed, error = self.run_upload([failed])
        self.assertIsNone(receipt)
        self.assertIsNone(readback)
        self.assertEqual(len(calls), 1)
        self.assertFalse(printed)
        self.assertEqual(str(error), "official publish upload failed: HTTP 409, state_format_mismatch")
        self.assertNotIn("customer text", str(error))
        self.assertNotIn("private-token", str(error))

    def test_unstructured_failure_does_not_echo_stdout_or_stderr(self):
        failed = subprocess.CompletedProcess(
            [], 1, b'{"status":"invalid","error":"customer text private-token"}',
            b"secret private-key\n",
        )
        receipt, readback, calls, printed, error = self.run_upload([failed])
        self.assertIsNone(receipt)
        self.assertIsNone(readback)
        self.assertEqual(len(calls), 1)
        self.assertFalse(printed)
        self.assertEqual(str(error), "official publish upload failed: exit 1")

    def test_http_error_without_exact_state_code_reports_status_only(self):
        body = {"detail": {"message": "state_format_mismatch customer text private-token"}}
        stdout = json.dumps({
            "status": "invalid",
            "error": "Super Expert upload returned HTTP 409: " + json.dumps(body),
        }).encode("utf-8")
        failed = subprocess.CompletedProcess([], 1, stdout, b"")
        _, _, _, _, error = self.run_upload([failed])
        self.assertEqual(str(error), "official publish upload failed: HTTP 409")


if __name__ == "__main__":
    unittest.main()
