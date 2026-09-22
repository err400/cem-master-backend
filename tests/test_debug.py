import asyncio
import os
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import debug as diagnostics


class DebugTests(unittest.TestCase):
    def test_environment_flag(self):
        for value, enabled in [("", False), ("false", False), ("0", False),
                               ("true", True), ("1", True), (" YES ", True)]:
            with self.subTest(value=value):
                result = subprocess.run(
                    [sys.executable, "-c", "from app.debug import debug; debug('probe', count=3)"],
                    env={**os.environ, "DEBUG": value}, capture_output=True, text=True, check=True,
                )
                self.assertEqual("probe" in result.stderr, enabled)
                self.assertEqual(result.stdout, "")

    def test_disabled_does_not_serialize(self):
        class MustNotSerialize:
            def __str__(self):
                raise AssertionError("disabled logs serialized a value")

        with patch.object(diagnostics, "DEBUG", False):
            diagnostics.debug("quiet", value=MustNotSerialize())

    def test_streaming_response_is_unchanged_and_secrets_are_not_logged(self):
        messages = [
            {"type": "http.response.start", "status": 206, "headers": []},
            {"type": "http.response.body", "body": b"audio", "more_body": True},
            {"type": "http.response.body", "body": b"tail", "more_body": False},
        ]
        received = []

        async def app(scope, receive, send):
            scope["route"] = SimpleNamespace(path="/clips/{filename}")
            for message in messages:
                await send(message)

        async def receive():
            raise AssertionError("middleware must not consume the request body")

        async def send(message):
            received.append(message)

        scope = {"type": "http", "method": "GET", "path": "/clips/private.wav",
                 "query_string": b"token=secret", "headers": [(b"authorization", b"secret")]}
        with patch.object(diagnostics, "DEBUG", True), patch.object(diagnostics, "debug") as log:
            asyncio.run(diagnostics.DebugRequests(app)(scope, receive, send))
            self.assertEqual(received, messages)
            self.assertEqual(log.call_args.kwargs["status"], 206)
            self.assertEqual(log.call_args.kwargs["route"], "/clips/{filename}")
            self.assertNotIn("secret", str(log.call_args_list))
            self.assertNotIn("private.wav", str(log.call_args_list))

    def test_exception_propagates_and_does_not_leak_details(self):
        async def app(scope, receive, send):
            raise RuntimeError("private database password or schema detail")

        with patch.object(diagnostics, "DEBUG", True), \
             patch.object(diagnostics, "debug") as log_debug, \
             patch.object(diagnostics, "error") as log_error:
            with self.assertRaises(RuntimeError):
                asyncio.run(diagnostics.DebugRequests(app)({"type": "http", "method": "GET"}, None, None))
            self.assertEqual(log_debug.call_args.kwargs["status"], 500)
            self.assertNotIn("private database password or schema detail", str(log_debug.call_args_list))
            self.assertNotIn("private database password or schema detail", str(log_error.call_args_list))
            self.assertEqual(log_error.call_args.kwargs["error"], "RuntimeError")
            self.assertNotIn("message", log_error.call_args.kwargs)


    def test_log_level_env(self):
        cases = [
            ("debug", True, True, True),
            ("info", False, True, True),
            ("error", False, False, True),
        ]
        for level, expect_debug, expect_info, expect_error in cases:
            with self.subTest(level=level):
                code = (
                    "from app.debug import debug, info, error; "
                    "debug('dbg_msg'); info('inf_msg'); error('err_msg')"
                )
                result = subprocess.run(
                    [sys.executable, "-c", code],
                    env={**os.environ, "LOG_LEVEL": level, "DEBUG": ""},
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertEqual("dbg_msg" in result.stderr, expect_debug)
                self.assertEqual("inf_msg" in result.stderr, expect_info)
                self.assertEqual("err_msg" in result.stderr, expect_error)

    def test_file_logging(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            code = (
                "from app.debug import info; "
                "info('file_probe', test_key='test_val')"
            )
            subprocess.run(
                [sys.executable, "-c", code],
                env={**os.environ, "LOG_DIR": tmpdir, "LOG_LEVEL": "info"},
                capture_output=True,
                text=True,
                check=True,
            )
            log_path = os.path.join(tmpdir, "app.log")
            self.assertTrue(os.path.isfile(log_path))
            with open(log_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("file_probe", content)
            self.assertIn('"test_key": "test_val"', content)


if __name__ == "__main__":
    unittest.main()

