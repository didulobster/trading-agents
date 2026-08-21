import logging
import re
from pathlib import Path

from bs4 import BeautifulSoup

from .models import ParsedSection

logger = logging.getLogger(__name__)

"""
What the code does

1. Strips noise: scripts, styles, hidden divs, and inline XBRL tags (which duplicate numbers and pollute text).
2. Flattens the DOM to ordered text blocks: paragraphs, list items, headings, table cells — each as one string, in document order.
3. Finds Item headings by regex on the block text. Crucially, it keeps only the last occurrence of each item, which filters out the table of contents (TOC headings appear first, real content headings appear later in the doc).
4. Slices content between headings: each Item gets the blocks from its heading up to the next Item's heading.

The TOC-dedup trick is the non-obvious one. Without it you'd get 16 empty "Item 1A" sections pointing at TOC entries. With it, you get one Item 1A section containing actual Risk Factors text.

10-K/10-Q/8-K and 20-F/6-K share the same "Item N[letter]." heading style, so
heading detection is shared; only the item-to-Part bucketing differs by
form_type (20-F has 3 Parts instead of the 10-K's 4). Some foreign private
issuers (e.g. filers using a combined IFRS annual report + 20-F cross-reference
table, like ASML) don't caption their real content with "Item N" headings at
all — only a reference table naming page numbers does — so this parser can't
recover real sections for those filings; it will legitimately find few or no
Item headings rather than mislabeling content.
"""

# Common 10-K Part headings used to bucket items
_ITEM_TO_PART = {
    # Part I
    "1": "Part I", "1A": "Part I", "1B": "Part I", "1C": "Part I",
    "2": "Part I", "3": "Part I", "4": "Part I",
    # Part II
    "5": "Part II", "6": "Part II", "7": "Part II", "7A": "Part II",
    "8": "Part II", "9": "Part II", "9A": "Part II", "9B": "Part II", "9C": "Part II",
    # Part III
    "10": "Part III", "11": "Part III", "12": "Part III",
    "13": "Part III", "14": "Part III",
    # Part IV
    "15": "Part IV", "16": "Part IV",
}

# Form 20-F's Part groupings (confirmed against real filings' own Item/Part
# cross-reference tables): Part I = items 1-12, Part II = items 13-16,
# Part III = items 17-19. Unlike the 10-K, this buckets cleanly by the
# leading item number regardless of letter suffix (e.g. "16G" -> 16 -> Part II),
# so a range lookup is used instead of an exhaustive dict.
_FORM_TYPES_20F = {"20-F", "20-F/A"}


def _item_to_part_20f(item_no: str) -> str:
    m = re.match(r"(\d{1,2})", item_no)
    if not m:
        return "Unknown"
    n = int(m.group(1))
    if 1 <= n <= 12:
        return "Part I"
    if 13 <= n <= 16:
        return "Part II"
    if 17 <= n <= 19:
        return "Part III"
    return "Unknown"


# Matches headings like "Item 1.", "Item 1A.", "ITEM 7A —", "Item 7A. Quantitative..."
# Anchored to start of a line/element so we don't match "Item 1" appearing mid-paragraph.
# This also covers 20-F's top-level items (1-19, including letter-suffixed
# items like "4A" and "16A"-"16K") since real 20-F filings use the same
# "Item N[letter]." caption style as 10-Ks — no separate regex is needed.
_ITEM_HEADING_RE = re.compile(
    r"^\s*(?:ITEM|Item)\s+(\d{1,2}[A-Za-z]?)\s*[.\-—–:]?\s*(.*?)\s*$"
)

# Rejects candidate titles that are checkbox/cross-reference rows rather than
# real headings, e.g. cover-page lines like "Item 17 [ ] Item 18 [ ]" that
# mention a second Item number inline.
_EMBEDDED_ITEM_MENTION_RE = re.compile(r"\bItem\s+\d", re.IGNORECASE)

# Rejects titles that are just glyphs/symbols (checkbox marks) with no
# alphanumeric content at all, e.g. a lone "☐".
_NO_ALNUM_RE = re.compile(r"^[^A-Za-z0-9]+$")

# Periodic reports (unlike event-driven 8-K/6-K filings) are expected to
# spread real content across many items. Some foreign private issuers file a
# combined IFRS annual report + 20-F cross-reference table instead of
# captioning content with "Item N" headings (e.g. ASML) — there, the only
# "Item N" text in the body is unrelated (AGM agenda items, a reference
# table), so heading detection produces a few bogus matches with one
# swallowing most of the document. Below this only shows up as one section
# holding a suspiciously large share of the document's content.
_PERIODIC_FORM_TYPES = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A"}
_DOMINANT_SECTION_RATIO = 0.65


def parse_filing(html_path: Path, form_type: str = "10-K") -> list[ParsedSection]:
    """
    Parse one 10-K/10-Q/8-K or 20-F/6-K HTML file into ordered ParsedSection
    objects. `form_type` only affects how items are bucketed into Parts
    (10-K's 4-part scheme vs 20-F's 3-part scheme) — heading detection
    itself is shared across form types.
    """

    logger.info("Parsing %s (form_type=%s)", html_path, form_type)
    html = html_path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "lxml")

    _strip_noise(soup)
    blocks = _flatten_to_text_blocks(soup)
    item_positions = _locate_item_headings(blocks)
    sections = _slice_sections(blocks, item_positions, form_type=form_type)

    if form_type.upper() in _PERIODIC_FORM_TYPES and sections:
        total_chars = sum(len(b) for b in blocks)
        largest = max(len(s.content) for s in sections)
        if total_chars and largest / total_chars > _DOMINANT_SECTION_RATIO:
            logger.warning(
                "Item-heading split looks unreliable for %s (one section holds "
                "%.0f%% of document content) — falling back to a single "
                "whole-document section",
                html_path, 100 * largest / total_chars,
            )
            sections = [
                ParsedSection(
                    section_path=["Unknown", "Full Document"],
                    order=0,
                    content="\n\n".join(blocks).strip(),
                )
            ]

    logger.info("Extracted %d non-empty sections", len(sections))
    return sections


def _strip_noise(soup: BeautifulSoup) -> None:
    """Remove tags that pollute extracted text."""
    for tag in soup(["script", "style", "head", "meta", "link"]):
        tag.decompose()
    # XBRL inline tags carry duplicate numeric content
    for tag in soup.find_all(re.compile(r"^ix:", re.IGNORECASE)):
        tag.unwrap()
    # Hidden elements
    for tag in soup.find_all(style=re.compile(r"display\s*:\s*none", re.IGNORECASE)):
        tag.decompose()

def _flatten_to_text_blocks(soup: BeautifulSoup) -> list[str]:
    """
    Walk the document and return a list of cleaned text blocks in order.

    A 'block' is roughly a paragraph or heading — text from a <p>, <div>,
    <h*>, <li>, or <td>. Whitespace is normalized. Empty blocks dropped.
    """
    BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "td", "tr", "section"}
    seen_ids: set[int] = set()
    blocks: list[str] = []

    for tag in soup.find_all(BLOCK_TAGS):
        # Avoid double-counting nested blocks; only emit at the leaf level
        if any(child.name in BLOCK_TAGS for child in tag.find_all()):
            continue
        text = tag.get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        # Cheap dedupe by id
        if id(tag) in seen_ids:
            continue
        seen_ids.add(id(tag))
        blocks.append(text)

    return blocks

def _locate_item_headings(blocks: list[str]) -> list[tuple[int, str, str]]:
    """
    Find blocks that look like 'Item N[A]. <title>' headings.

    Multiple occurrences of the same Item are common (TOC + content).
    We prefer the occurrence with the most content between it and the
    NEXT Item heading — that's the real section, not a TOC entry.
    """
    candidates: dict[str, list[tuple[int, str]]] = {}
    for i, block in enumerate(blocks):
        m = _ITEM_HEADING_RE.match(block)
        if not m:
            continue
        if len(block) > 200:
            continue
        item_no = m.group(1).upper()
        title = (m.group(2) or "").strip(" .:—–-")
        if title:
            # Checkbox/cross-reference rows, e.g. cover-page lines like
            # "Item 17 [ ] Item 18 [ ]" that mention a second Item inline.
            if _EMBEDDED_ITEM_MENTION_RE.search(title):
                continue
            # Glyph-only titles, e.g. a lone checkbox mark "☐".
            if _NO_ALNUM_RE.match(title):
                continue
            # Real headings start with a capitalized/numeric word; a
            # lowercase-first title means this is a mid-sentence match
            # (e.g. "...as well as NYSE Section 303A.11 requires...").
            if title[0].islower():
                continue
        candidates.setdefault(item_no, []).append((i, title))

    if not candidates:
        return []

    # Flatten all (block_idx, item_no, title) candidates and sort by position
    all_positions = sorted(
        (idx, item_no, title)
        for item_no, occurrences in candidates.items()
        for idx, title in occurrences
    )

    # For each item_no, pick the occurrence with the most blocks before
    # the NEXT heading-of-any-kind. Real content sections have body
    # between them; TOC entries are packed together.
    occurrence_scores: dict[str, list[tuple[int, str, int]]] = {}
    for n, (idx, item_no, title) in enumerate(all_positions):
        next_idx = (
            all_positions[n + 1][0]
            if n + 1 < len(all_positions)
            else len(blocks)
        )
        gap = next_idx - idx - 1  # blocks of body between this heading and next
        occurrence_scores.setdefault(item_no, []).append((idx, title, gap))

    located: list[tuple[int, str, str]] = []
    for item_no, occurrences in occurrence_scores.items():
        # Best occurrence = the one with the largest body gap. Ties (e.g.
        # two equally-short "Not applicable" stub sections) prefer the
        # later position, since TOC entries always precede real content.
        best = max(occurrences, key=lambda x: (x[2], x[0]))
        idx, title, _ = best
        located.append((idx, item_no, title))

    located.sort(key=lambda x: x[0])
    return located

def _slice_sections(
    blocks: list[str],
    item_positions: list[tuple[int, str, str]],
    form_type: str = "10-K",
) -> list[ParsedSection]:
    """Take blocks between consecutive Item headings as one section's content."""
    is_20f = form_type.upper() in _FORM_TYPES_20F
    sections: list[ParsedSection] = []
    for order, (start_idx, item_no, title) in enumerate(item_positions):
        end_idx = (
            item_positions[order + 1][0]
            if order + 1 < len(item_positions)
            else len(blocks)
        )
        body_blocks = blocks[start_idx + 1:end_idx]
        content = "\n\n".join(body_blocks).strip()
        if not content:
            continue

        part = _item_to_part_20f(item_no) if is_20f else _ITEM_TO_PART.get(item_no, "Unknown")
        path = [part, f"Item {item_no}"]
        if title:
            path.append(title)

        sections.append(
            ParsedSection(section_path=path, order=order, content=content)
        )

    return sections

