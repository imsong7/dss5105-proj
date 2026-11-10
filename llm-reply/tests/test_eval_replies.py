from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import eval_replies as e  # noqa: E402


class EvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = e.load_cases(e.DEFAULT_CASES)
        cls.by_id = {case["id"]: case for case in cls.cases}

    def test_cases_are_unique_and_diverse(self) -> None:
        self.assertEqual(len(self.cases), 9)
        self.assertEqual(len(self.by_id), len(self.cases))
        self.assertGreaterEqual(len({case["eval"]["type"] for case in self.cases}), 6)

    def test_all_ideal_replies_pass(self) -> None:
        for case in self.cases:
            with self.subTest(case=case["id"]):
                self.assertEqual(e.evaluate_reply(case, case["eval"]["ideal_reply"]), [])

    def test_any_fact_accepts_alternative(self) -> None:
        case = self.by_id["eval-group-meeting"]
        reply = "Hi Wei,\n\nTuesday afternoon works for me. Please confirm.\n\nBest,\nAmelia"
        self.assertEqual(e.evaluate_reply(case, reply), [])

    def test_missing_fact_fails(self) -> None:
        case = self.by_id["eval-consultation"]
        issues = e.evaluate_reply(case, "Hello Anggi,\n\nI would like to attend.\n\nBest,\nAmelia")
        self.assertTrue(any("missing key fact: 6 October" in issue for issue in issues))

    def test_banned_phrase_fails(self) -> None:
        case = self.by_id["eval-access"]
        issues = e.evaluate_reply(case, "The password is TempPass123.\n\nBest,\nAmelia")
        self.assertTrue(any("banned phrase" in issue for issue in issues))

    def test_raw_address_fails(self) -> None:
        case = self.by_id["eval-extension"]
        issues = e.evaluate_reply(
            case,
            "Please email prof.tan@example.edu about the extension.\n\nBest,\nAmelia",
        )
        self.assertTrue(any("raw email address" in issue for issue in issues))

    def test_too_many_sentences_fails(self) -> None:
        case = self.by_id["eval-feedback"]
        reply = (
            "Hi NUSync,\n\nThank you for the reminder. "
            "I have completed the feedback form. "
            "It was a useful event. "
            "I look forward to the next one.\n\nBest,\nAmelia"
        )
        issues = e.evaluate_reply(case, reply)
        self.assertTrue(any("too many sentences" in issue for issue in issues))

    def test_placeholder_is_required_when_expected(self) -> None:
        case = dict(self.cases[0])
        case["eval"] = dict(case["eval"], requires_placeholder=True)
        issues = e.evaluate_reply(case, case["eval"]["ideal_reply"])
        self.assertTrue(any("expected a placeholder" in issue for issue in issues))

    def test_load_drafts_and_find_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "drafts.json"
            path.write_text(
                json.dumps({"drafts": [{"id": "eval-consultation", "reply": "Thanks."}]}),
                encoding="utf-8",
            )
            drafts = e.load_drafts(path)
            case = self.by_id["eval-consultation"]
            self.assertEqual(e.find_draft(case, drafts)["reply"], "Thanks.")


if __name__ == "__main__":
    unittest.main()
