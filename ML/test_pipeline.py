import unittest

import pandas as pd

from compare_models import split_comparison_data
from train_email_ml import map_label_values


class LabelValidationTests(unittest.TestCase):
    def test_missing_labels_are_reported(self):
        with self.assertRaisesRegex(ValueError, "2 missing category labels"):
            map_label_values(
                pd.Series(["", None]),
                {"general": "General"},
                "category",
                "labels",
            )

    def test_unknown_labels_are_reported(self):
        with self.assertRaisesRegex(ValueError, "unknown category labels"):
            map_label_values(
                pd.Series(["unexpected"]),
                {"general": "General"},
                "category",
                "labels",
            )

    def test_known_labels_are_mapped(self):
        mapped = map_label_values(
            pd.Series(["General", "career"]),
            {"general": "General", "career": "Career"},
            "category",
            "labels",
        )
        self.assertEqual(mapped.tolist(), ["General", "Career"])


class HoldoutTests(unittest.TestCase):
    def test_holdout_is_disjoint_and_deterministic(self):
        frame = pd.DataFrame(
            {
                "email_id": [f"email-{i}" for i in range(40)],
                "text": [f"message {i}" for i in range(40)],
                "label": ["first", "second"] * 20,
            }
        )

        train, test = split_comparison_data(frame)
        train_again, test_again = split_comparison_data(frame)

        self.assertTrue(set(train["email_id"]).isdisjoint(test["email_id"]))
        self.assertEqual(train["email_id"].tolist(), train_again["email_id"].tolist())
        self.assertEqual(test["email_id"].tolist(), test_again["email_id"].tolist())
        self.assertEqual(len(test), 8)


if __name__ == "__main__":
    unittest.main()
