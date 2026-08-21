import re
from typing import AsyncGenerator

# Phrases to remove entirely
PHRASES_TO_REMOVE = [
    r"(?i)as an ai(?: language model)?\b,?\s*",
    r"(?i)i am an ai(?: language model)?\b,?\s*",
    r"(?i)i hope this helps!?\s*"
]

# Any run of em-dashes, en-dashes, or 2+ hyphens becomes a single plain
# hyphen. The dash itself (not just runs of it) is the tell — an LLM's
# single "—" is far more common in real output than "---", and the old
# regex only caught the latter (and, worse, turned "--" INTO a real
# em-dash instead of removing it).
_DASH_RUN_RE = re.compile(r'[-‐-‒–—―]{1,}')

# Words to replace to reduce "AI feel" without destroying meaning.
# (pattern, lowercase_replacement) — case of the match is preserved by
# _replace_preserving_case below, so every value here stays lowercase.
WORD_REPLACEMENTS: dict[str, str] = {
    r"(?i)\bspearheaded\b":    "led",
    r"(?i)\bspearhead\b":      "lead",
    r"(?i)\borchestrated\b":   "managed",
    r"(?i)\borchestrate[sd]?\b": "manage",
    r"(?i)\bnavigated\b":      "managed",
    r"(?i)\bnavigate[sd]?\b":  "manage",
    r"(?i)\bharnessed\b":      "used",
    r"(?i)\bharness\b":        "use",
    r"(?i)\bleveraged\b":      "used",
    r"(?i)\bleverages?\b":     "use",
    r"(?i)\bfostered\b":       "built",
    r"(?i)\bfoster(?:ing)?\b": "build",
    r"(?i)\bcatalyzed\b":      "drove",
    r"(?i)\bsynergized\b":     "aligned",
    r"(?i)\bdelved\b":         "explored",
    r"(?i)\bdelves?\b":        "explore",
    r"(?i)\bembarked?\b":      "started",
    r"(?i)\bunderscored?\b":   "highlighted",
    r"(?i)\bparamount\b":      "critical",
    r"(?i)\bmeticulously\b":   "carefully",
    r"(?i)\bmeticulous\b":     "thorough",
    r"(?i)\btransformative\b": "significant",
    r"(?i)\btestament\b":      "proof",
    r"(?i)\bpivotal\b":        "key",
    r"(?i)\bcommendable\b":    "strong",
    r"(?i)\bintricate\b":      "complex",
    r"(?i)\bnuanced\b":        "detailed",
    r"(?i)\brobust\b":         "strong",
    r"(?i)\btapestry\b":       "collection",
    r"(?i)\bboast(?:s|ed|ing)?\b": "has",
    r"(?i)\bvibrant\b":        "active",
    r"(?i)\bshowcase[sd]?\b":  "shows",
    r"(?i)\bshowcasing\b":     "showing",
    r"(?i)\benhance[sd]?\b":   "improve",
    r"(?i)\benhancing\b":      "improving",
    r"(?i)\balign(?:ed|s)? with\b": "matches",
    r"(?i)\bgarner(?:ed|s)?\b": "earned",
    r"(?i)\bcrucial\b":        "key",
    r"(?i)\bseamless(?:ly)?\b": "smooth",
    r"(?i)\bcutting-edge\b":   "modern",
    r"(?i)\bgame-changing\b":  "significant",
    r"(?i)\bunwavering\b":     "steady",
    r"(?i)\binvaluable\b":     "valuable",
    r"(?i)\bgroundbreaking\b": "new",
    r"(?i)\brenowned\b":       "known",
    r"(?i)\bbolster(?:ed|s)?\b": "strengthened",
    r"(?i)\bcultivat(?:e|ed|es|ing)\b": "built",
    r"(?i)\butiliz(?:e|ed|es|ing)\b": "used",
    r"(?i)\bfacilitat(?:e|ed|es|ing)\b": "helped",
    r"(?i)\bstreamlin(?:e|ed|es|ing)\b": "simplified",
    r"(?i)\bmultifaceted\b":   "varied",
    r"(?i)\bplethora\b":       "range",
    r"(?i)\bmyriad\b":         "many",
}
_WORD_REPLACEMENTS_COMPILED = [(re.compile(p), r) for p, r in WORD_REPLACEMENTS.items()]


def _replace_preserving_case(pattern: re.Pattern, replacement: str, text: str) -> str:
    def _rep(m: re.Match) -> str:
        orig = m.group(0)
        if orig.isupper():
            return replacement.upper()
        if orig[0].isupper():
            return replacement[0].upper() + replacement[1:]
        return replacement
    return pattern.sub(_rep, text)


def clean_ai_text(text: str) -> str:
    """
    Applies regex to find and replace known AI tells in a string: disclaimer
    phrases, overused vocabulary, and em/en-dashes (real human writing in
    this product's voice uses a hyphen, a comma, or two sentences instead).
    """
    for phrase in PHRASES_TO_REMOVE:
        text = re.sub(phrase, "", text)

    for pattern, replacement in _WORD_REPLACEMENTS_COMPILED:
        text = _replace_preserving_case(pattern, replacement, text)

    text = _DASH_RUN_RE.sub("-", text)

    return text

def scrub_dict(data: dict) -> dict:
    """
    Recursively applies clean_ai_text to all string values in a dictionary.
    Safe for JSON payloads where we don't want to modify keys.
    """
    if isinstance(data, dict):
        return {k: scrub_dict(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [scrub_dict(item) for item in data]
    elif isinstance(data, str):
        return clean_ai_text(data)
    else:
        return data

class AIScrubberBuffer:
    """
    A stateful buffer that accumulates text chunks and flushes cleaned sentences.
    Useful for integrating into complex stream loops.
    """
    def __init__(self):
        self.buffer = ""
        self.boundary_pattern = re.compile(r'([.!?]\s+|\n+)')

    def process_chunk(self, chunk: str) -> str:
        self.buffer += chunk
        output = ""

        match = self.boundary_pattern.search(self.buffer)
        while match:
            split_idx = match.end()
            sentence = self.buffer[:split_idx]
            self.buffer = self.buffer[split_idx:]

            cleaned = clean_ai_text(sentence)
            if cleaned:
                output += cleaned

            match = self.boundary_pattern.search(self.buffer)

        return output

    def flush(self) -> str:
        output = ""
        if self.buffer:
            cleaned = clean_ai_text(self.buffer)
            if cleaned:
                output += cleaned
            self.buffer = ""
        return output

async def stream_clean_ai_text(async_gen: AsyncGenerator[str, None]) -> AsyncGenerator[str, None]:
    """
    Wraps an async generator (like SSE chunk streams), buffering text until
    a sentence boundary is reached, scrubbing the buffer, and yielding it.
    This prevents AI phrases split across network chunks from escaping.
    """
    scrubber = AIScrubberBuffer()

    async for chunk in async_gen:
        cleaned = scrubber.process_chunk(chunk)
        if cleaned:
            yield cleaned

    final_cleaned = scrubber.flush()
    if final_cleaned:
        yield final_cleaned
