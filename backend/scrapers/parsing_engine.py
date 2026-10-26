import html as html_lib
import re
import logging
from typing import Optional, Dict, Any, List, Union

from bs4 import BeautifulSoup, Tag
from backend.utilities.html_guard import html_visible_text, visible_text

logger = logging.getLogger(__name__)

# One step in a JSON extraction path: a dict key or a list index.
JsonPathStep = Union[str, int]

class ParsingEngine:
    """
    Centralized parsing utility to standardize data extraction from 
    unstructured HTML and JSON payloads. Prevents errors when DOM elements are missing.
    """

    @staticmethod
    def parse_html(html_str: str) -> BeautifulSoup:
        """Parse raw HTML into a BeautifulSoup object."""
        return BeautifulSoup(html_str, "html.parser")

    @staticmethod
    def extract_text_by_selector(soup: BeautifulSoup, selector: str) -> Optional[str]:
        """
        Safely extract text from the first element matching the CSS selector.
        Returns None if not found or empty.
        """
        element = soup.select_one(selector)
        if element:
            text = element.get_text(separator=" ", strip=True)
            return text if text else None
        return None

    @staticmethod
    def extract_all_texts_by_selector(soup: BeautifulSoup, selector: str) -> List[str]:
        """
        Extract text from all elements matching the CSS selector.
        """
        elements = soup.select(selector)
        return [
            text for el in elements 
            if (text := el.get_text(separator=" ", strip=True))
        ]

    @staticmethod
    def clean_html(html_str: str) -> str:
        """
        Removes all HTML tags, scripts, and styles, standardizing whitespace.
        Useful for building raw_text for the LLM.
        """
        soup = BeautifulSoup(html_str, "html.parser")
        
        # Remove script and style elements
        for script in soup(["script", "style", "noscript", "meta"]):
            script.decompose()

        # Extract text
        text = visible_text(soup, separator=" ", strip=True)

        # Collapse multiple spaces
        return re.sub(r'\s+', ' ', text).strip()

    @staticmethod
    def html_to_text(raw_html: str) -> str:
        """
        Convert an HTML fragment to newline-separated plain text.

        Unlike clean_html (which collapses everything to one line for keyword
        matching), this preserves line structure — required for jd_text that
        feeds the JD parser and thin-JD length gates. ATS JSON payloads
        (Greenhouse/Lever) sometimes entity-encode their markup (e.g.
        `&lt;div&gt;`), so entities are unescaped before parsing.
        """
        if not raw_html:
            return ""
        unescaped = html_lib.unescape(raw_html)
        soup = BeautifulSoup(unescaped, "html.parser")
        for element in soup(["script", "style", "noscript", "meta"]):
            element.decompose()
        text = visible_text(soup, separator="\n").strip()
        # Collapse runs of blank lines but keep single line breaks
        return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+\n", "\n", text))

    @staticmethod
    def extract_json_metadata(
        json_data: dict,
        schema_paths: Dict[str, List[JsonPathStep]],
    ) -> Dict[str, Any]:
        """
        Safely pull nested keys from a JSON dictionary based on a mapping of
        desired keys to their paths. Path steps may be dict keys (str) or list
        indices (int) — ATS payloads nest objects inside arrays (e.g. Lever's
        "lists", Greenhouse's "offices").

        Example:
            schema_paths = {
                "title":    ["job", "title"],
                "location": ["job", "location", "name"],
                "office":   ["offices", 0, "name"],
            }
        """
        result = {}
        for target_key, path in schema_paths.items():
            current: Any = json_data
            for step in path:
                if isinstance(step, int):
                    if isinstance(current, list) and -len(current) <= step < len(current):
                        current = current[step]
                    else:
                        current = None
                        break
                elif isinstance(current, dict) and step in current:
                    current = current[step]
                else:
                    current = None
                    break
            result[target_key] = current
        return result
