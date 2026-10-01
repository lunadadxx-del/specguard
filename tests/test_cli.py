import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from specguard.cli import main

V1 = """\
openapi: 3.0.0
info: {title: t, version: '1'}
paths:
  /a:
    get:
      responses:
        '200': {description: ok}
"""

V2 = """\
openapi: 3.0.0
info: {title: t, version: '2'}
paths:
  /a:
    get:
      responses:
        '200': {description: ok}
  /b:
    post:
      responses:
        '201': {description: created}
"""


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.v1 = Path(self.tmp.name) / "v1.yaml"
        self.v2 = Path(self.tmp.name) / "v2.yaml"
        self.v1.write_text(V1)
        self.v2.write_text(V2)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([str(self.v1), str(self.v2), *args])
        return code, buf.getvalue()

    def test_non_breaking_only_exits_zero_by_default(self):
        code, out = self._run()
        self.assertEqual(code, 0)
        self.assertIn("non-breaking", out)

    def test_fail_on_any_exits_two(self):
        code, _ = self._run("--fail-on", "any")
        self.assertEqual(code, 2)

    def test_json_format_parses(self):
        code, out = self._run("--format", "json", "--fail-on", "never")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertIn("summary", payload)
        self.assertTrue(any(c["location"] == "POST /b" for c in payload["changes"]))

    def test_markdown_format(self):
        code, out = self._run("--format", "markdown", "--fail-on", "never")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("# API Change Report"))

    def test_missing_file_exits_one(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([str(self.v1), "/nonexistent.yaml"])
        self.assertEqual(code, 1)

    def test_ignore_rules(self):
        ignore = Path(self.tmp.name) / "ignore.yaml"
        ignore.write_text("- {path: '/b', method: POST}\n")
        code, out = self._run("--ignore", str(ignore), "--format", "json",
                              "--fail-on", "never")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["changes"], [])


if __name__ == "__main__":
    unittest.main()
