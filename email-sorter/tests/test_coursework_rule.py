import unittest

from app.classifiers.sender_rules import coursework_by_rule
from app.server import create_app


class CourseworkRuleTests(unittest.TestCase):
    def test_course_mail_with_a_date_needs_action(self):
        result = coursework_by_rule("DSS5105 Assignment 1 due 8 Nov", "Submit on Kaggle.", True, False)
        self.assertEqual(result[:2], ("general", "needs_action"))

    def test_exam_notice_is_a_reminder(self):
        result = coursework_by_rule("DSS5105 final exam 24 Nov", "Details inside.", True, True)
        self.assertEqual(result[:2], ("general", "reminder"))

    def test_course_mail_without_a_date_needs_nothing(self):
        result = coursework_by_rule("DSS5105 lecture slides", "Slides are on Canvas.", False, False)
        self.assertEqual(result[:2], ("general", "no_immediate_action"))

    def test_needs_both_a_course_code_and_coursework_words(self):
        self.assertIsNone(coursework_by_rule("Career fair 12 Nov", "Meet recruiters.", True, False))
        self.assertIsNone(coursework_by_rule("Sale ends soon", "Order ABC1234 today.", False, False))

    def test_route_skips_the_model_for_course_mail(self):
        client = create_app(provider="graphtoken").test_client()
        response = client.post(
            "/api/classify",
            json={
                "email": {
                    "id": "course-1",
                    "subject": "DSS5101 CA4 due 8 Nov 2026",
                    "sender": "Prof Lim <prof@nus.edu.sg>",
                    "body": "Please submit your slides by 8 Nov 2026.",
                    "received": "2026-11-01T09:00:00+08:00",
                },
                "backend": "llama",
            },
        )
        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["content_category"], "general")
        self.assertEqual(data["reply_nature"], "needs_action")
        self.assertIn("Course rule", data["model_name"])


if __name__ == "__main__":
    unittest.main()
