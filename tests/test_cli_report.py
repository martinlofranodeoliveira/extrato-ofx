import copy
import csv
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from extrato_ofx import parse_ofx, to_json, to_csv, to_markdown, Limits, OfxError
from extrato_ofx import cli
from helpers import fixture


class ReportTests(unittest.TestCase):
    def test_json_roundtrip_no_mutation(self):
        report = parse_ofx(fixture())
        before = copy.deepcopy(report)
        self.assertEqual(json.loads(to_json(report)), report)
        to_csv(report)
        to_markdown(report)
        self.assertEqual(report, before)

    def test_csv_exact_decimal_identity_and_line_endings(self):
        report = parse_ofx(fixture(amount="-3,200"))
        text = to_csv(report)
        self.assertTrue(text.endswith("\r\n"))
        self.assertNotIn("\n", text.replace("\r\n", ""))
        row = list(csv.DictReader(StringIO(text)))[0]
        self.assertEqual(row["amount"], "-3.2")
        self.assertEqual(row["amount_raw"], "'-3,200")
        self.assertEqual(row["account_id"], "000123")
        self.assertEqual(row["posted_utc"], "2024-01-02T06:00:00Z")

    def test_csv_formula_guard_and_explicit_raw_api_option(self):
        for token in ("=1+1", "  +SUM(A1:A2)", "-danger", "@call", "\t=cmd"):
            report = parse_ofx(fixture(name=token))
            expected = token.strip()
            guarded = next(csv.DictReader(StringIO(to_csv(report))))["name"]
            self.assertEqual(guarded, "'" + expected)
            original = next(csv.DictReader(StringIO(to_csv(report, spreadsheet_safe=False))))["name"]
            self.assertEqual(original, expected)

    def test_unknown_fields_block_csv_but_json_marks_incomplete(self):
        report = parse_ofx(fixture(extra="<UNSUPPORTED><VALUE>PRIVATE-CONTENT</VALUE></UNSUPPORTED>"))
        self.assertEqual(report["status"], "incomplete")
        self.assertNotIn("PRIVATE-CONTENT", to_json(report))
        with self.assertRaises(OfxError) as raised:
            to_csv(report)
        self.assertEqual(raised.exception.code, "incomplete_csv")
        row = next(csv.DictReader(StringIO(to_csv(report, allow_incomplete=True))))
        self.assertEqual(row["coverage"], "incomplete")

    def test_markdown_does_not_inject_html_links_or_rows(self):
        from markdown_it import MarkdownIt
        report = parse_ofx(fixture(name='<script>alert(1)</script> [x](https://example.invalid) | ![img](x)', memo="one\ntwo"))
        rendered = MarkdownIt("commonmark", {"html": True}).enable("table").render(to_markdown(report))
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<a ", rendered)
        self.assertNotIn("<img ", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("one ⏎ two", rendered)

    def test_each_exporter_enforces_utf8_byte_cap(self):
        report = parse_ofx(fixture(name="é" * 30))
        for function in (to_json, to_csv, to_markdown):
            expected = function(report)
            size = len(expected.encode("utf-8"))
            self.assertEqual(function(report, limits=Limits(max_output_bytes=size)), expected)
            with self.assertRaises(OfxError) as raised:
                function(report, limits=Limits(max_output_bytes=size - 1))
            self.assertEqual(raised.exception.code, "output_size")

    def test_bad_reports_are_controlled(self):
        valid = parse_ofx(fixture())
        for changes in ({"stats": {"float": 1.2}}, {"stats": {"not_json": object()}}, {"coverage": None}):
            changed = {**valid, **changes}
            with self.assertRaises(OfxError):
                to_json(changed)
        cyclic = copy.deepcopy(valid)
        cyclic["stats"]["cycle"] = cyclic
        with self.assertRaises(OfxError):
            to_json(cyclic)

    def test_non_string_statuses_never_escape_as_type_errors(self):
        valid = parse_ofx(fixture())
        for value in ([], {}, None, True, 1):
            for changed in ({**valid, "status": value}, {**valid, "coverage": {"status": value}}):
                for exporter in (to_json, to_csv, to_markdown):
                    with self.subTest(value=value, exporter=exporter.__name__), self.assertRaises(OfxError):
                        exporter(changed)

    def test_edited_report_cannot_bypass_output_escapes(self):
        from markdown_it import MarkdownIt
        report = parse_ofx(fixture())
        report["statements"][0]["transactions"][0]["amount"]["value"] = "=1+1"
        with self.assertRaises(OfxError):
            to_csv(report)
        report = parse_ofx(fixture())
        report["statements"][0]["totals"]["reportedCount"] = "<script>alert(1)</script>"
        rendered = MarkdownIt("commonmark", {"html": True}).render(to_markdown(report))
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)


class CliTests(unittest.TestCase):
    def run_cli(self, *args, raw=None, cwd=None):
        return subprocess.run([sys.executable, "-m", "extrato_ofx", *args], input=raw,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, timeout=20)

    def test_stdin_json_csv_markdown(self):
        for fmt in ("json", "csv", "markdown"):
            result = self.run_cli("-", "--format", fmt, raw=fixture())
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, b"")
            self.assertIn(b"000123", result.stdout)

    def test_incomplete_exit_and_csv_gate(self):
        raw = fixture(extra="<OTHERBLOCK>value</OTHERBLOCK>")
        result = self.run_cli("-", raw=raw)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["status"], "incomplete")
        rejected = self.run_cli("-", "--format", "csv", raw=raw)
        self.assertEqual(rejected.returncode, 3)
        self.assertEqual(rejected.stdout, b"")
        allowed = self.run_cli("-", "--format", "csv", "--allow-incomplete-csv", raw=raw)
        self.assertEqual(allowed.returncode, 2)

    def test_file_publication_exclusive_and_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "source.ofx", Path(directory) / "result.json"
            source.write_bytes(fixture())
            first = self.run_cli(str(source), "--output", str(target))
            self.assertEqual(first.returncode, 0, first.stderr)
            saved = target.read_bytes()
            self.assertEqual(json.loads(saved)["status"], "ok")
            second = self.run_cli(str(source), "--output", str(target))
            self.assertEqual(second.returncode, 3)
            self.assertEqual(target.read_bytes(), saved)
            self.assertEqual(first.stdout, b"")
            self.assertEqual(list(Path(directory).glob(".extrato-ofx-*.tmp")), [])

    def test_failed_or_limited_parse_creates_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "new.json"
            result = self.run_cli("-", "--output", str(target), "--max-input-bytes", "20", raw=fixture())
            self.assertEqual(result.returncode, 3)
            self.assertFalse(target.exists())

    def test_diagnostics_do_not_echo_private_values(self):
        secret = "PRIVATE-BANK-ACCOUNT-TEST"
        for args, raw in ((("--format", secret, "-"), b""), (("-", "--max-nodes", secret), b""), (("/" + secret,), None), (("-",), fixture(amount=secret))):
            result = self.run_cli(*args, raw=raw)
            self.assertEqual(result.returncode, 3)
            self.assertEqual(result.stdout, b"")
            self.assertNotIn(secret.encode(), result.stderr)
            self.assertNotIn(b"Traceback", result.stderr)

    def test_directory_and_fifo_are_not_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self.run_cli(directory).returncode, 3)
            if hasattr(os, "mkfifo"):
                pipe = Path(directory) / "fifo"
                os.mkfifo(pipe)
                self.assertEqual(self.run_cli(str(pipe)).returncode, 3)

    def test_help_version_and_invalid_limits(self):
        for flag in ("--help", "--version"):
            self.assertEqual(self.run_cli(flag).returncode, 0)
        for token in ("0", "-1", "1000000000", "١٢", "9" * 5000):
            self.assertEqual(self.run_cli("-", "--max-nodes", token, raw=fixture()).returncode, 3)

    def test_publish_race_keeps_other_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "race.json"
            def concurrent_writer(source, destination):
                Path(destination).write_bytes(b"OTHER-WRITER")
                raise FileExistsError()
            with patch.object(cli.os, "link", concurrent_writer), self.assertRaises(OfxError):
                cli._publish_new(target, "NEW")
            self.assertEqual(target.read_bytes(), b"OTHER-WRITER")
            self.assertEqual(list(Path(directory).glob(".extrato-ofx-*.tmp")), [])

    @unittest.skipIf(os.name == "nt", "Anonymous broken-pipe behavior differs on Windows")
    def test_broken_pipe_is_controlled(self):
        process = subprocess.Popen([sys.executable, "-m", "extrato_ofx", "-"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process.stdout.close()
        process.stdin.write(fixture())
        process.stdin.close()
        stderr = process.stderr.read()
        self.assertEqual(process.wait(timeout=20), 3)
        self.assertNotIn(b"Traceback", stderr)
        self.assertNotIn(b"Exception ignored", stderr)
        process.stderr.close()
