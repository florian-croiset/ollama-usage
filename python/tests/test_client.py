import re
import unittest

import ollama_cloud_usage
from ollama_cloud_usage import (
    ApiError,
    AuthError,
    Client,
    NetworkError,
    OllamaUsageError,
    RateLimitedError,
)
from ollama_cloud_usage._errors import from_native


class ClientTest(unittest.TestCase):
    def test_an_empty_key_is_refused_before_any_request(self) -> None:
        with self.assertRaises(AuthError):
            Client("  ")

    def test_an_unknown_range_is_refused_before_any_request(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected 24h, 7d or 30d"):
            Client("key").fetch("1y")  # type: ignore[arg-type]

    def test_the_timeout_must_be_positive(self) -> None:
        for timeout in (0, -1, float("nan")):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                Client("key", timeout=timeout)

    def test_the_key_never_shows_in_repr(self) -> None:
        self.assertNotIn("secret", repr(Client("secret")))


class ErrorTest(unittest.TestCase):
    def test_each_kind_maps_to_its_exception(self) -> None:
        for kind, expected in [
            ("auth", AuthError),
            ("rate_limited", RateLimitedError),
            ("network", NetworkError),
            ("api", ApiError),
            ("from_a_later_version", ApiError),
        ]:
            with self.subTest(kind=kind):
                error = from_native(kind, "message", None)
                self.assertIsInstance(error, expected)
                self.assertIsInstance(error, OllamaUsageError)
                self.assertEqual(str(error), "message")

    def test_a_rate_limit_carries_the_wait(self) -> None:
        error = from_native("rate_limited", "rate-limited", 30.0)
        self.assertEqual(error.retry_after, 30.0)


class MetadataTest(unittest.TestCase):
    def test_versions_are_exposed(self) -> None:
        self.assertRegex(ollama_cloud_usage.__version__, re.compile(r"^\d+\.\d+\.\d+"))
        self.assertEqual(ollama_cloud_usage.SCHEMA_VERSION, "1.0")


if __name__ == "__main__":
    unittest.main()
