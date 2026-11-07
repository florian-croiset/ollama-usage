import os
import subprocess
import sys
import unittest


def run(*arguments: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "OLLAMA_API_KEY"}
    env["NO_COLOR"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "ollama_cloud_usage", *arguments],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


class CommandTest(unittest.TestCase):
    def test_version_names_the_command(self) -> None:
        result = run("--version")
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stdout.startswith("ollama-usage "), result.stdout)

    def test_invalid_arguments_exit_with_64(self) -> None:
        self.assertEqual(run("--range", "1y").returncode, 64)

    def test_a_missing_configuration_exits_with_64(self) -> None:
        self.assertEqual(run("--config", "does-not-exist.toml").returncode, 64)


if __name__ == "__main__":
    unittest.main()
