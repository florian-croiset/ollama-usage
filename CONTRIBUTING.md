# Contributing

Thank you for your interest in contributing to **ollama-usage**!

## Getting started

```bash
git clone https://github.com/florian-croiset/ollama-usage
cd ollama-usage
pip install -e ".[dev]"
```

## Running the tests

```bash
pytest
```

## Submitting a change

1. Fork the repository and create a branch from `main`.
2. Make your changes and add tests if relevant.
3. Make sure all tests pass.
4. Open a pull request with a clear description of what you changed and why.

## Commit style

Use short, descriptive prefixes:

| Prefix | Use for |
|--------|---------|
| `feat:` | New feature |
| `fix:` | Bug fix |
| `chore:` | Maintenance (deps, config, changelog…) |
| `docs:` | Documentation only |
| `test:` | Tests only |

Example: `fix: handle None cookie when browser has no ollama.com session`

## Changelog

For every user-facing change, add an entry in `CHANGELOG.md` under the `## Unreleased` section (between the last release and the top of the file).

## License

By contributing, you agree that your code will be released under the [MIT License](LICENSE).