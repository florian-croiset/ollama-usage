"""Tests for ollama_usage.exceptions and the public package API."""

from __future__ import annotations

import pytest

import ollama_usage
from ollama_usage import exceptions

SUBCLASSES = [
    exceptions.AuthError,
    exceptions.ParseError,
    exceptions.NetworkError,
    exceptions.BrowserNotFoundError,
    exceptions.UnsupportedOSError,
]


class TestHierarchy:

    @pytest.mark.parametrize("exc", SUBCLASSES)
    def test_subclass_of_base(self, exc) -> None:
        assert issubclass(exc, exceptions.OllamaUsageError)

    def test_base_is_exception(self) -> None:
        assert issubclass(exceptions.OllamaUsageError, Exception)

    @pytest.mark.parametrize("exc", SUBCLASSES)
    def test_message_preserved(self, exc) -> None:
        assert str(exc("boom")) == "boom"

    @pytest.mark.parametrize("exc", SUBCLASSES)
    def test_catchable_as_base(self, exc) -> None:
        with pytest.raises(exceptions.OllamaUsageError):
            raise exc("x")

    def test_subclasses_are_distinct(self) -> None:
        assert len(set(SUBCLASSES)) == len(SUBCLASSES)
        for a in SUBCLASSES:
            for b in SUBCLASSES:
                if a is not b:
                    assert not issubclass(a, b)


class TestPublicApi:

    def test_all_names_exist(self) -> None:
        for name in ollama_usage.__all__:
            assert hasattr(ollama_usage, name), name

    def test_expected_exports(self) -> None:
        assert {"get_usage", "get_usage_api", "iter_periods", "OllamaUsageError"} <= set(ollama_usage.__all__)

    @pytest.mark.parametrize("name", ["get_usage", "get_usage_api", "iter_periods"])
    def test_functions_callable(self, name: str) -> None:
        assert callable(getattr(ollama_usage, name))

    def test_no_runtime_dependencies(self) -> None:
        import pathlib
        import re
        pyproject = pathlib.Path(__file__).parents[1] / "pyproject.toml"
        match = re.search(r"^dependencies\s*=\s*\[(.*?)\]", pyproject.read_text(encoding="utf-8"), re.M | re.S)
        assert match is not None
        assert match.group(1).strip() == ""

    @pytest.mark.parametrize("module", ["cryptography", "colorama", "win32crypt"])
    def test_removed_dependencies_not_imported(self, module: str) -> None:
        import pathlib
        package = pathlib.Path(ollama_usage.__file__).parent
        for source in package.glob("*.py"):
            assert f"import {module}" not in source.read_text(encoding="utf-8"), source.name
