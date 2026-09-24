"""Check local Markdown links and heading anchors in the repository."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
HTML_IMAGE = re.compile(r'<img\s+[^>]*src=["\']([^"\']+)["\']', re.IGNORECASE)
HEADING = re.compile(r"^#{1,6} (.+)$", re.MULTILINE)


def anchors(markdown: str) -> set[str]:
    seen: Counter[str] = Counter()
    result: set[str] = set()
    for heading in HEADING.findall(markdown):
        plain = re.sub(r"<[^>]+>", "", heading).lower()
        slug = re.sub(r"[^\w\- ]", "", plain).replace(" ", "-")
        suffix = seen[slug]
        seen[slug] += 1
        result.add(f"{slug}-{suffix}" if suffix else slug)
    return result


def main() -> int:
    documents = sorted(ROOT.glob("*.md"))
    documents += sorted((ROOT / "docs").rglob("*.md"))
    documents += sorted((ROOT / "frontend").glob("*.md"))
    documents += sorted((ROOT / "integrations").rglob("*.md"))
    failures: list[str] = []
    checked = 0
    for doc in documents:
        contents = doc.read_text(encoding="utf-8")
        links = MARKDOWN_LINK.findall(contents) + HTML_IMAGE.findall(contents)
        for raw in links:
            target = raw.strip().split(' "', 1)[0].strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or target.startswith("//"):
                continue
            checked += 1
            destination = (doc.parent / unquote(parsed.path)).resolve() if parsed.path else doc
            if not destination.is_relative_to(ROOT) or not destination.exists():
                failures.append(f"{doc.relative_to(ROOT)}: missing {target}")
            elif parsed.fragment and destination.suffix == ".md":
                if unquote(parsed.fragment).lower() not in anchors(destination.read_text(encoding="utf-8")):
                    failures.append(f"{doc.relative_to(ROOT)}: missing anchor {target}")
    print(f"Checked {checked} local links in {len(documents)} Markdown files")
    for failure in failures:
        print(failure)
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
