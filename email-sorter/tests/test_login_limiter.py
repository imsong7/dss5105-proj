import unittest

from app.accounts import LoginLimiter


class LoginLimiterTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.limiter = LoginLimiter(window=60, per_email=3, per_client=5, clock=lambda: self.now)

    def test_allows_until_the_limit_then_waits(self):
        for _ in range(3):
            self.assertEqual(self.limiter.wait_seconds("a@x", "1.1.1.1"), 0)
            self.limiter.record_failure("a@x", "1.1.1.1")

        self.assertGreater(self.limiter.wait_seconds("a@x", "1.1.1.1"), 0)

    def test_failures_expire_after_the_window(self):
        for _ in range(3):
            self.limiter.record_failure("a@x", "1.1.1.1")
        self.now += 61

        self.assertEqual(self.limiter.wait_seconds("a@x", "1.1.1.1"), 0)

    def test_one_address_is_limited_across_many_emails(self):
        for index in range(5):
            self.limiter.record_failure(f"user{index}@x", "9.9.9.9")

        self.assertGreater(self.limiter.wait_seconds("fresh@x", "9.9.9.9"), 0)
        self.assertEqual(self.limiter.wait_seconds("fresh@x", "2.2.2.2"), 0)

    def test_without_an_email_only_the_client_is_limited(self):
        # Token sign-ins have no email: failures from different people must not add up.
        for index in range(4):
            self.limiter.record_failure(None, f"1.1.1.{index}")
        self.assertEqual(self.limiter.wait_seconds(None, "9.9.9.9"), 0)

        for _ in range(5):
            self.limiter.record_failure(None, "9.9.9.9")
        self.assertGreater(self.limiter.wait_seconds(None, "9.9.9.9"), 0)
        self.assertEqual(self.limiter.wait_seconds(None, "2.2.2.2"), 0)

    def test_success_clears_the_email(self):
        for _ in range(3):
            self.limiter.record_failure("a@x", "1.1.1.1")
        self.limiter.record_success("a@x")

        self.assertEqual(self.limiter.wait_seconds("a@x", "2.2.2.2"), 0)


if __name__ == "__main__":
    unittest.main()
