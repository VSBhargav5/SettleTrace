from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from settletrace.cli import _capture, main
from settletrace.models import InputError


class CaptureLimitTests(unittest.TestCase):
    def test_exact_byte_limit_accepts_and_one_more_rejects(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "data"
            source.write_bytes(b"12345")
            self.assertEqual(_capture(source, 5), b"12345")
            with self.assertRaisesRegex(InputError, "max-input-bytes=4"):
                _capture(source, 4)

    def test_oversize_read_is_bounded_before_parsing_or_allocating_whole_file(self):
        stream = io.BytesIO(b"x" * 1000)
        with patch.object(stream, "read", wraps=stream.read) as read:
            with patch.object(Path, "open", return_value=stream), self.assertRaises(InputError):
                _capture(Path("data"), 10)
            self.assertEqual(read.call_args.args, (11,))

    def test_cli_rejects_oversized_normalization_before_creating_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "stripe.csv"
            source.write_bytes(b"x" * 100)
            output = directory / "out"
            stderr = io.StringIO()
            with redirect_stderr(stderr), redirect_stdout(io.StringIO()):
                code = main(["normalize-stripe", "--input", str(source), "--output", str(output), "--max-input-bytes", "10"])
            self.assertEqual(code, 2)
            self.assertIn("max-input-bytes=10", stderr.getvalue())
            self.assertFalse(output.exists())
