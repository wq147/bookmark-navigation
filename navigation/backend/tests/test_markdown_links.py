import re
from pathlib import Path
from urllib.parse import unquote, urlsplit


REPOSITORY_ROOT = Path(__file__).parents[3]
IGNORED_PARTS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "playwright-report",
    "test-results",
    "venv",
}
MARKDOWN_LINK = re.compile(r"!?\[[^]]*\]\(([^)]+)\)")
FENCE_OPEN = re.compile(r" {0,3}(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"`[^`\n]*`")


def _link_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        target = target[1 : target.index(">")]
    else:
        target = target.split(maxsplit=1)[0]
    return unquote(target.split("#", 1)[0])


def _strip_fenced_code(content: str) -> str:
    remaining = []
    fence_character = ""
    fence_length = 0
    for line in content.splitlines(keepends=True):
        if fence_character:
            closing = re.fullmatch(
                rf" {{0,3}}{re.escape(fence_character)}{{{fence_length},}}[ \t]*(?:\r?\n)?",
                line,
            )
            if closing:
                fence_character = ""
                fence_length = 0
            continue
        opening = FENCE_OPEN.match(line)
        if opening:
            fence = opening.group(1)
            fence_character = fence[0]
            fence_length = len(fence)
        else:
            remaining.append(line)
    return "".join(remaining)


def find_broken_local_markdown_links(root: Path) -> list[str]:
    root = root.resolve()
    broken = []
    for document in root.rglob("*.md"):
        if IGNORED_PARTS.intersection(document.parts):
            continue
        content = _strip_fenced_code(document.read_text(errors="replace"))
        content = INLINE_CODE.sub("", content)
        for raw_target in MARKDOWN_LINK.findall(content):
            target = _link_target(raw_target)
            if not target or urlsplit(target).scheme:
                continue
            resolved = (document.parent / target).resolve()
            label = f"{document.relative_to(root)} -> {target}"
            if not resolved.is_relative_to(root) or not resolved.exists():
                broken.append(label)
    return sorted(broken)


def test_link_checker_reports_missing_local_target(tmp_path):
    (tmp_path / "README.md").write_text("[missing](docs/missing.md)\n")

    assert find_broken_local_markdown_links(tmp_path) == [
        "README.md -> docs/missing.md"
    ]


def test_link_checker_ignores_fenced_code_examples(tmp_path):
    (tmp_path / "README.md").write_text(
        "```markdown\n[example](docs/not-a-real-link.md)\n```\n"
    )

    assert find_broken_local_markdown_links(tmp_path) == []


def test_link_checker_ignores_fenced_example_with_embedded_backticks(tmp_path):
    (tmp_path / "README.md").write_text(
        "```python\n"
        "def example(tmp_path):\n"
        "    (tmp_path / \"README.md\").write_text(\n"
        "        \"```markdown\\n[example](docs/not-a-real-link.md)\\n```\\n\"\n"
        "    )\n"
        "```\n"
    )

    assert find_broken_local_markdown_links(tmp_path) == []


def test_repository_markdown_links_resolve():
    assert find_broken_local_markdown_links(REPOSITORY_ROOT) == []
