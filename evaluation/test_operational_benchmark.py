"""Unit tests for the operational benchmark.

These do not call Llama, Ollama, or BERT. Run from the repo root:

    .venv/bin/python -m unittest evaluation.test_operational_benchmark
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.operational_benchmark import (  # noqa: E402
    CallRecord,
    _agreement_rows,
    _bootstrap_proportion,
    _llama_raw_status,
    render_report,
)


def _raw(content: str):
    return SimpleNamespace(content=content)


def _record(
    review_id: str,
    phase: str,
    run: int,
    category: str,
    action: str,
    mode: str = "full",
) -> CallRecord:
    return CallRecord(
        backend="llama",
        review_id=review_id,
        phase=phase,
        run=run,
        input_mode=mode,
        input_chars=100,
        latency_ms=1.0,
        category=category,
        action=action,
        raw_valid=True,
        invalid_reason=None,
        input_tokens=10,
        output_tokens=5,
        server_load_ms=None,
        true_action="",
        true_category="",
        raw_excerpt="",
    )


class RawStatusTests(unittest.TestCase):
    def test_valid_json_and_labels(self) -> None:
        result = {
            "raw": _raw('{"content_category": "medical", "reply_nature": "reminder"}'),
            "parsed": object(),
            "parsing_error": None,
        }
        valid, reason, _ = _llama_raw_status(result)
        self.assertTrue(valid)
        self.assertIsNone(reason)

    def test_invalid_label(self) -> None:
        result = {
            "raw": _raw('{"content_category": "Medical?", "reply_nature": "reminder"}'),
            "parsed": object(),
            "parsing_error": None,
        }
        valid, reason, _ = _llama_raw_status(result)
        self.assertFalse(valid)
        self.assertIn("invalid_category", reason or "")

    def test_non_json(self) -> None:
        result = {"raw": _raw("not json"), "parsed": object(), "parsing_error": None}
        valid, reason, _ = _llama_raw_status(result)
        self.assertFalse(valid)
        self.assertEqual(reason, "raw_not_json")

    def test_parsing_error(self) -> None:
        result = {
            "raw": _raw("{}"),
            "parsed": None,
            "parsing_error": "bad schema",
        }
        valid, reason, _ = _llama_raw_status(result)
        self.assertFalse(valid)
        self.assertIn("parsing_error", reason or "")


class AgreementTests(unittest.TestCase):
    def test_bootstrap_bounds(self) -> None:
        point, lo, hi = _bootstrap_proportion([True, True, False], 200, 7)
        self.assertAlmostEqual(point, 2 / 3)
        self.assertLessEqual(lo, point)
        self.assertGreaterEqual(hi, point)

    def test_consistency_and_length(self) -> None:
        records = [
            _record("a", "main", 1, "medical", "reminder"),
            _record("a", "main", 2, "medical", "reminder"),
            _record("a", "length_short", 0, "medical", "reminder", "short"),
            _record("b", "main", 1, "medical", "reminder"),
            _record("b", "main", 2, "medical", "needs_reply"),
            _record("b", "length_short", 0, "medical", "needs_action", "short"),
        ]
        args = SimpleNamespace(runs=2)
        consistency, length = _agreement_rows("llama", records, args)
        self.assertEqual(len(consistency), 2)
        by_id = {r["review_id"]: r for r in consistency}
        self.assertTrue(by_id["a"]["exact"])
        self.assertFalse(by_id["b"]["exact"])
        self.assertTrue(by_id["b"]["category_consistent"])
        self.assertFalse(by_id["b"]["action_consistent"])

        length_by_id = {r["review_id"]: r for r in length}
        self.assertTrue(length_by_id["a"]["both_agree"])
        self.assertTrue(length_by_id["b"]["category_agree"])
        self.assertFalse(length_by_id["b"]["action_agree"])


class ReportTests(unittest.TestCase):
    def test_nan_error_cell_is_not_an_error(self) -> None:
        summary = pd.DataFrame(
            [
                {
                    "backend": "bert",
                    "error": float("nan"),
                    "sample_n": 1,
                    "load_ms": 100.0,
                    "cold_call_ms": 10.0,
                    "warm_p50_ms": 5.0,
                    "warm_p95_ms": 6.0,
                    "peak_total_mb": 500.0,
                    "model_size_mb": 100.0,
                    "input_tokens_mean": 10.0,
                    "output_tokens_mean": 0.0,
                    "energy_kwh": 0.0001,
                    "invalid_format_rate": None,
                    "consistency_exact": 1.0,
                    "length_both": 1.0,
                }
            ]
        )
        manifest = {
            "sample_n": 1,
            "total_rows": 1,
            "runs": 5,
            "seed": 42,
            "body_char_limit": 3000,
            "short_chars": 200,
            "sample_action_counts": {},
        }
        report = render_report(summary, manifest)
        self.assertNotIn("ERROR", report)
        self.assertIn("bert", report)


if __name__ == "__main__":
    unittest.main()
