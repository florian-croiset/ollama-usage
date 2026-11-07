# Contributing

Thank you for your interest in **ollama-usage**.

## Layout

| Path | What it is |
| --- | --- |
| `crates/ollama-usage` | The Rust core: HTTP client, response parsing, the report |
| `crates/ollama-usage-cli` | The `ollama-usage` command |
| `crates/ollama-usage-py` | The native module of the Python package |
| `python/ollama_cloud_usage` | The Python API, built on the report's JSON form |
| `examples/` | Python scripts using the package, run without a key by the tests |
| `schemas/` | The JSON schema of the report |
| `fixtures/api/` | API responses used by the tests |
| `fixtures/reports/` | The reports expected from them, shared by the Rust and Python tests |

## Setting up

You need a stable Rust toolchain ([rustup](https://rustup.rs)) and Python 3.10 or
later.

```bash
git clone https://github.com/florian-croiset/ollama-usage
cd ollama-usage
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install maturin pyright ruff
maturin develop                    # builds the extension into the virtualenv
```

## Checks

CI runs all of these; run them before opening a pull request.

```bash
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
ruff check python examples && ruff format --check python examples
pyright                            # strict type checking
python -m unittest discover -s python/tests
```

Clippy runs with the pedantic lints. Allow one only at the item that needs it,
with a reason when it is not obvious.

## Tests and test data

The tests never reach ollama.com: the client is tested against recorded
responses in `fixtures/api/`.

**Never commit data from a real account**, not even rounded or shifted:
percentages, amounts, request counts, reset dates (they reveal the sign-up date),
the models you use, names or e-mail addresses. Use obviously invented values,
like those already in `fixtures/`. This applies to tests, documentation, commit
messages and pull requests.

When the report changes, update `fixtures/reports/` and the schema together: CI
checks that the reference reports match it. Within 1.x the schema only gains
fields.

## Submitting a change

1. Create a branch from `main`.
2. Make the change, with tests.
3. Add an entry under `## Unreleased` in `CHANGELOG.md` for anything users notice.
4. Open a pull request saying what changed and why.

Commit messages start with a prefix:

| Prefix | Use for |
| --- | --- |
| `feat:` | New feature |
| `fix:` | Bug fix |
| `docs:` | Documentation only |
| `test:` | Tests only |
| `ci:` | Continuous integration |
| `chore:` | Maintenance: dependencies, configuration, releases |

A scope may follow, e.g. `fix(cli): …` or `feat(python): …`.

## Releasing

1. Set the new version in `Cargo.toml`, both under `[workspace.package]` and for
   `ollama-usage` under `[workspace.dependencies]`, and run `cargo check` to update
   `Cargo.lock`. The Python package takes its version from there.
2. In `CHANGELOG.md`, rename `## Unreleased` to `## [X.Y.Z] - YYYY-MM-DD` and open
   a new, empty `## Unreleased` above it. In `README.md` and `docs/index.html`,
   point the `pip install` line at the new tag and version.
3. Merge that change, then tag the merge commit and push the tag:
   `git tag vX.Y.Z && git push origin vX.Y.Z`.
4. The *Release* workflow builds the command for Linux, macOS and Windows and the
   Python wheels, and drafts a GitHub Release with them, their checksums and the
   changelog section, its wrapped lines joined since a release page shows every
   line break. Review the draft, then publish it.

Running the *Release* workflow by hand from the Actions tab builds everything
without releasing, which is a way to try the builds before tagging.

## License

By contributing, you agree that your code will be released under the
[MIT License](LICENSE).
