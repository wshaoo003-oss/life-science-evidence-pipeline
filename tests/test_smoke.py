"""Offline integrity and failure-path checks; no downloads or parser models."""
import ast
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from pipeline_common import looks_like_pdf, safe_relative_path, ensure_run_layout
from validate_run import validate_evidence_record


class PackageChecks(unittest.TestCase):
    def test_python_syntax_and_json(self):
        for path in ROOT.rglob('*.py'):
            ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        corpus = json.loads((ROOT / 'assets/validation-corpus.json').read_text(encoding='utf-8'))
        self.assertEqual(len(corpus['papers']), 5)
        self.assertEqual(len({p['pmcid'] for p in corpus['papers']}), 5)

    def test_skill_resources_exist(self):
        text = (ROOT / 'SKILL.md').read_text(encoding='utf-8')
        for relative in re.findall(r'(?:references|scripts|assets)/[a-zA-Z0-9_.-]+', text):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_cli_help(self):
        for name in ['check_runtime', 'build_manifest', 'fetch_open_access', 'parse_batch', 'validate_run']:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts' / (name + '.py')), '--help'],
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_reject_html_as_pdf_and_path_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake = root / 'article.pdf'
            fake.write_text('<html>Sign in</html>', encoding='utf-8')
            self.assertFalse(looks_like_pdf(fake))
            with self.assertRaises(ValueError):
                safe_relative_path(root, root.parent / 'outside.pdf')

    def test_missing_evidence_fields_rejected(self):
        self.assertTrue(validate_evidence_record({'claim': 'unsupported'}))

    def test_empty_run_cannot_pass_release(self):
        with tempfile.TemporaryDirectory() as temp:
            run = ensure_run_layout(Path(temp) / 'run')
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/validate_run.py'),
                                     '--run', str(run), '--expected-papers', '5', '--expected-evidence', '25'],
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            report = json.loads((run / 'release/release_manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(report['overall_status'], 'failed')
            self.assertFalse(report['gates']['all evidence verified'])


if __name__ == '__main__':
    unittest.main()
