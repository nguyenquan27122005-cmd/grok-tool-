"""OTP parser for Genspark verification mail."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIB = ROOT.parent / "genspark"
if str(SIB) not in sys.path:
    sys.path.insert(0, str(SIB))

from gsparkreg.mail import extract_verify  # noqa: E402


class GensparkOtpTest(unittest.TestCase):
    def test_labeled_code(self) -> None:
        tok = extract_verify("Your Genspark verification code is 482917. It expires soon.")
        self.assertEqual(tok.get("code"), "482917")

    def test_skip_yearish(self) -> None:
        tok = extract_verify("Genspark signup 202601 then code 339944 in the body")
        self.assertEqual(tok.get("code"), "339944")

    def test_skip_trivial(self) -> None:
        tok = extract_verify("Genspark verification 123456 is fake; real 774411")
        self.assertEqual(tok.get("code"), "774411")


if __name__ == "__main__":
    unittest.main()
