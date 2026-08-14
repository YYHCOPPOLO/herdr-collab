"""Unit tests for the pure/guard logic in the herdr-collab scripts.

Run from anywhere:  py -m unittest discover -s tests   (Windows)
                    python3 -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Job files go to a throwaway dir, never into a real repo's .herdr/.
os.environ["HERDR_JOBS"] = tempfile.mkdtemp(prefix="herdr-collab-test-")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import herdr_finish as hf  # noqa: E402
import herdr_peer as hp  # noqa: E402


class ParseCommandTest(unittest.TestCase):
    def test_list_passthrough_str_items(self):
        self.assertEqual(hf.parse_command(["py", "a b.py", 3]), ["py", "a b.py", "3"])

    def test_string_posix_quoting(self):
        self.assertEqual(hf.parse_command('py -c "print(1 2)"'), ["py", "-c", "print(1 2)"])

    def test_unbalanced_quotes_raise(self):
        with self.assertRaises(ValueError):
            hf.parse_command('py -c "oops')


class FinishEnvTest(unittest.TestCase):
    def test_empty_means_inherit(self):
        self.assertIsNone(hf.finish_env({}))

    def test_merge_over_environ_and_str_values(self):
        env = hf.finish_env({"SMOKE_VAR": 42})
        self.assertEqual(env["SMOKE_VAR"], "42")
        self.assertIn("PATH", env)  # inherits the clerk's environment


class SafeCleanupTest(unittest.TestCase):
    def test_under_herdr_and_temp_allowed(self):
        hf.safe_cleanup(".herdr/jobs/x.txt")
        hf.safe_cleanup("temp/x.txt")

    def test_outside_repo_rejected(self):
        with self.assertRaises(SystemExit):
            hf.safe_cleanup("../evil.txt")

    def test_other_repo_dir_rejected(self):
        with self.assertRaises(SystemExit):
            hf.safe_cleanup("scripts/x.py")


class AppendHandshakeTest(unittest.TestCase):
    def test_appends_instructions_once(self):
        out = hp.append_handshake("do the thing", "42")
        self.assertIn("42.done.json", out)
        self.assertIn("handoff", out)
        self.assertTrue(out.startswith("do the thing"))

    def test_idempotent_when_path_present(self):
        out = hp.append_handshake("do the thing", "42")
        self.assertEqual(hp.append_handshake(out, "42"), out)


class DefaultsTest(unittest.TestCase):
    def test_default_timeout(self):
        self.assertEqual(hf.DEFAULT_TIMEOUT_SEC, 180)


if __name__ == "__main__":
    unittest.main()
