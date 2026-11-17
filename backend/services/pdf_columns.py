"""
Reading order for multi-column CV pages.

Most design-tool CVs (77% of Canva's templates, almost every Hebrew one) put a
sidebar beside the main column. A reader that goes line by line across the
page — pdfplumber's `extract_text(layout=True)`, which the upload path uses —
then prints the sidebar and the main column on one line:

    "Innovative and disciplined leader with 2019 - Present SENIOR OPERATIONS MANAGER"

This module finds the columns on a page and returns the text in groups that
can each be read top to bottom on their own:

- Words are joined into *segments*: runs of words on one line with no gap
  wider than about one letter height. Two columns on the same line are two
  segments; a role and its right-aligned date are also two segments.
- A *gutter* is an x position that few segments cross. Segments that do
  cross it (a centred name in the header, a full-width section heading) are
  *separators*: they split the page into horizontal bands, and inside each
  band the left and right columns are read one after the other.
- A gutter is accepted only when it looks like two real columns side by side,
  not a one-column CV whose dates sit at the right margin (see
  `_is_column_split`). When nothing qualifies the caller keeps its old path,
  so one-column pages read exactly as before.
- Each column is searched again (one more level) for three-column pages.

Right-to-left pages read the right column first.

All functions here work on plain tuples, so the same logic serves pdfplumber
(the main path) and PyMuPDF (the fallback).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_RTL_CHARS = re.compile(r"[֐-׿؀-ۿ]")
_LATIN_CHARS = re.compile(r"[A-Za-z]")

# Tuning. Each value is explained where it is used.
_SEGMENT_GAP_EM = 0.8        # word gap (in letter heights) that ends a segment
_EDGE_MARGIN = 0.10          # gutter must lie inside the middle 80% of the text width
_MIN_GUTTER_PT = 6.0         # narrowest gap accepted as a gutter
_MIN_SIDE_SEGMENTS = 3       # each column needs at least this many segments
_MIN_SIDE_CHARS = 0.10       # ... and at least this share of the characters
_MIN_STACKED = 0.5           # ... and this share of its segments in stacked runs
_MIN_Y_OVERLAP = 0.5         # the columns must sit side by side, not one above the other
_MAX_INNER_SEPARATORS = 0.10 # crossing segments allowed *between* the columns' lines
_MAX_DEPTH = 2               # top-level split + one more inside each column


@dataclass
class Segment:
    x0: float
    top: float
    x1: float
    bottom: float
    text: str
    words: list = field(default_factory=list)   # the source word objects, untouched

    @property
    def height(self) -> float:
        return max(self.bottom - self.top, 1.0)

    @property
    def ycenter(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def nchars(self) -> int:
        return len(self.text.replace(" ", ""))


def page_is_rtl(text: str) -> bool:
    """A page is right-to-left when Hebrew/Arabic letters are a large share
    of its letters. Hebrew CVs carry plenty of English (tools, companies), so
    a simple majority would be too strict."""
    rtl = len(_RTL_CHARS.findall(text))
    latin = len(_LATIN_CHARS.findall(text))
    return rtl > 0 and rtl >= 0.4 * (rtl + latin)


def build_segments(words) -> list[Segment]:
    """
    `words`: iterable of (x0, top, x1, bottom, text, source) tuples. Words on
    the same visual line are joined left to right until a gap wider than
    `_SEGMENT_GAP_EM` letter heights; that gap starts a new segment.
    """
    words = sorted(words, key=lambda w: (w[1], w[0]))
    lines: list[list] = []
    for w in words:
        yc = (w[1] + w[3]) / 2
        # Same line when the word's centre falls within the line's vertical
        # span. A bold 11pt role and a 9pt date on one row still match.
        for line in reversed(lines[-4:]):
            top = min(x[1] for x in line)
            bottom = max(x[3] for x in line)
            if top <= yc <= bottom:
                line.append(w)
                break
        else:
            lines.append([w])

    segments: list[Segment] = []
    for line in lines:
        line.sort(key=lambda w: w[0])
        current = [line[0]]
        for w in line[1:]:
            prev = current[-1]
            height = max(prev[3] - prev[1], w[3] - w[1], 1.0)
            if w[0] - prev[2] > _SEGMENT_GAP_EM * height:
                segments.append(_segment(current))
                current = [w]
            else:
                current.append(w)
        segments.append(_segment(current))
    return segments


def _segment(words) -> Segment:
    return Segment(
        x0=min(w[0] for w in words), top=min(w[1] for w in words),
        x1=max(w[2] for w in words), bottom=max(w[3] for w in words),
        text=" ".join(w[4] for w in words), words=[w[5] for w in words],
    )


def reading_regions(segments: list[Segment], rtl: bool) -> list[list[Segment]] | None:
    """
    None when the page is one column (no split found at the top level), so
    the caller can keep its original extraction. Otherwise a list of regions
    in reading order; each region is read top to bottom on its own.
    """
    if _find_split(segments) is None:
        return None
    return _regions(segments, rtl, depth=0)


def _regions(segments: list[Segment], rtl: bool, depth: int) -> list[list[Segment]]:
    split = _find_split(segments) if depth < _MAX_DEPTH else None
    if split is None:
        return [segments]
    left, right, separators = split
    first, second = (right, left) if rtl else (left, right)
    # Text in the second column that lies wholly above the first column (a
    # centred name that happens to sit over the main column) is a header:
    # read it before both columns, not after the first.
    first_top = min(s.top for s in first)
    lifted = [s for s in second if s.bottom <= first_top]
    if lifted:
        second = [s for s in second if s.bottom > first_top]
        separators = separators + lifted
    columns = [first, second]
    separators = sorted(separators, key=lambda s: s.ycenter)

    out: list[list[Segment]] = []
    pending: list[Segment] = []          # consecutive separators read as one region
    bounds = [float("-inf")] + [s.ycenter for s in separators] + [float("inf")]
    for i in range(len(bounds) - 1):
        lo, hi = bounds[i], bounds[i + 1]
        band = [[s for s in col if lo <= s.ycenter < hi] for col in columns]
        if any(band):
            if pending:
                out.append(pending)
                pending = []
            for part in band:
                if part:
                    out.extend(_regions(part, rtl, depth + 1))
        if i < len(separators):
            pending.append(separators[i])
    if pending:
        out.append(pending)
    return out


def _find_split(segments: list[Segment]):
    """(left, right, separators) for the best qualifying gutter, or None."""
    if len(segments) < 2 * _MIN_SIDE_SEGMENTS:
        return None
    x_lo = min(s.x0 for s in segments)
    x_hi = max(s.x1 for s in segments)
    width = x_hi - x_lo
    if width < 50:
        return None
    start = int(x_lo + _EDGE_MARGIN * width)
    stop = int(x_hi - _EDGE_MARGIN * width)
    if stop <= start:
        return None

    # coverage[i] = how many segments cross x = start + i
    coverage = [0] * (stop - start + 1)
    for s in segments:
        a = max(int(s.x0) + 1, start)
        b = min(int(s.x1), stop)
        for x in range(a, b + 1):
            coverage[x - start] += 1

    # Runs of equal coverage, cheapest first, then widest. A real gutter is a
    # wide run with (almost) no crossings; a header name crossing it adds one.
    runs = []
    i = 0
    while i < len(coverage):
        j = i
        while j + 1 < len(coverage) and coverage[j + 1] == coverage[i]:
            j += 1
        if j - i + 1 >= _MIN_GUTTER_PT:
            runs.append((coverage[i], -(j - i + 1), start + (i + j) / 2))
        i = j + 1
    runs.sort()

    for _, _, gutter in runs[:6]:
        left = [s for s in segments if s.x1 <= gutter]
        right = [s for s in segments if s.x0 >= gutter]
        cross = [s for s in segments if s.x0 < gutter < s.x1]
        if _is_column_split(left, right, cross):
            return left, right, cross
    return None


def _is_column_split(left, right, cross) -> bool:
    """
    Accept a gutter only when both sides look like columns of running text.
    The case to reject is a one-column CV: its right edge holds dates or
    locations ("2019 - Present"), which also leave a clean vertical gap.
    """
    if len(left) < _MIN_SIDE_SEGMENTS or len(right) < _MIN_SIDE_SEGMENTS:
        return False

    # Volume: a dates-only strip holds a few percent of the characters.
    lc = sum(s.nchars for s in left)
    rc = sum(s.nchars for s in right)
    if min(lc, rc) < _MIN_SIDE_CHARS * (lc + rc):
        return False

    # Side by side: the two vertical spans must overlap.
    l_top, l_bot = min(s.top for s in left), max(s.bottom for s in left)
    r_top, r_bot = min(s.top for s in right), max(s.bottom for s in right)
    overlap = min(l_bot, r_bot) - max(l_top, r_top)
    if overlap < _MIN_Y_OVERLAP * min(l_bot - l_top, r_bot - r_top):
        return False

    # Few crossings *between* the columns' lines. In a one-column CV every
    # wrapped bullet crosses the "gutter"; in a two-column CV only a header
    # or footer does, or the odd full-width heading.
    lo, hi = max(l_top, r_top), min(l_bot, r_bot)
    inner = sum(1 for s in cross if lo < s.ycenter < hi)
    if inner > max(2, _MAX_INNER_SEPARATORS * (len(left) + len(right))):
        return False

    # Running text: most segments have a neighbour directly above or below.
    # Isolated date strings, one per role, do not.
    return _stacked_share(left) >= _MIN_STACKED and _stacked_share(right) >= _MIN_STACKED


def _stacked_share(side: list[Segment]) -> float:
    ordered = sorted(side, key=lambda s: s.top)
    stacked = 0
    for idx, s in enumerate(ordered):
        for t in ordered[max(0, idx - 6): idx + 7]:
            if t is s:
                continue
            gap = max(t.top - s.bottom, s.top - t.bottom)
            if gap <= 1.0 * max(s.height, t.height) and min(s.x1, t.x1) > max(s.x0, t.x0):
                stacked += 1
                break
    return stacked / len(side)


def region_bbox(region: list[Segment], pad: float = 1.0) -> tuple[float, float, float, float]:
    return (min(s.x0 for s in region) - pad, min(s.top for s in region) - pad,
            max(s.x1 for s in region) + pad, max(s.bottom for s in region) + pad)
