"""Prints the changelog section of a version as release notes.

The changelog is wrapped at 80 columns, which a Markdown file renders as
flowing text; a GitHub release renders each line break, so the lines of a
paragraph or a list item are joined.

Usage: python .github/scripts/release_notes.py VERSION [CHANGELOG.md]
"""

import re
import sys
from pathlib import Path

BLOCK_START = re.compile(r"(#{1,6} |[-*+] |\d+\. |\||>|```)")


def section(changelog: str, version: str) -> list[str]:
    """The lines under the heading of ``version``, up to the next heading."""
    lines = changelog.splitlines()
    heading = f"## [{version}]"
    start = next((i for i, line in enumerate(lines) if line.startswith(heading)), None)
    if start is None:
        return []
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start + 1 : end]


def unwrap(lines: list[str]) -> list[str]:
    """Joins the lines of each paragraph and list item; code blocks are kept."""
    out: list[str] = []
    fenced = False
    for line in lines:
        text = line.strip()
        if text.startswith("```"):
            fenced = not fenced
            out.append(line)
            continue
        previous = out[-1].strip() if out else ""
        joins = (
            not fenced
            and text
            and previous
            and not BLOCK_START.match(text)
            and not previous.startswith(("#", "|", "```"))
        )
        if joins:
            out[-1] = f"{out[-1].rstrip()} {text}"
        else:
            out.append(line)
    return out


def main() -> int:
    """Prints the notes of the version given on the command line."""
    version = sys.argv[1]
    changelog = Path(sys.argv[2] if len(sys.argv) > 2 else "CHANGELOG.md")
    notes = unwrap(section(changelog.read_text(encoding="utf-8"), version))
    text = "\n".join(notes).strip()
    print(text or f"No changelog section for {version}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
