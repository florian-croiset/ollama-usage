import os
import subprocess
import sys
import unittest
from pathlib import Path

EXAMPLES = sorted((Path(__file__).resolve().parents[2] / "examples").glob("*.py"))


class ExamplesTest(unittest.TestCase):
    def test_there_are_examples(self) -> None:
        self.assertTrue(EXAMPLES)

    def test_each_example_explains_a_missing_key_without_a_traceback(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "OLLAMA_API_KEY"}
        for example in EXAMPLES:
            with self.subTest(example=example.name):
                result = subprocess.run(
                    [sys.executable, str(example)],
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=60,
                    check=False,
                )
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("OLLAMA_API_KEY", result.stderr)
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
