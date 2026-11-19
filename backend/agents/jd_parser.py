import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Optional

from backend.agents.profile_analyzer import _parse_json
from backend.services.llm_client import call_llm

logger = logging.getLogger(__name__)

_JD_PARSER_SYSTEM_PROMPT = """\
Return ONLY raw JSON, no conversational filler, no markdown blocks.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BILINGUAL & RTL PROCESSING (HEBREW/ENGLISH)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
You must seamlessly comprehend mixed syntax, such as Hebrew sentences containing English technical terms or acronyms, without losing context or introducing translation artifacts.
Regardless of the input language (Hebrew, English, or mixed), all returned JSON structures MUST use English keys exclusively. Values may be in the source language, but keys must always be English.

You are an expert Job Description (JD) parser. Your goal is to extract structured requirements from a raw, potentially noisy job description HTML or text.
Ignore boilerplate, nav menus, cookie banners, or company marketing fluff.

Return this exact JSON shape — every key is required:

{
  "role_title": "<string, or null>",
  "company_name": "<string, or null>",
  "seniority": "<junior|mid|senior|staff|principal, or null>",
  "hard_skills": ["<skill>", ...],
  "must_haves": ["<requirement>", ...],
  "nice_to_haves": ["<nice-to-have requirement>", ...]
}

Extraction rules:
- role_title: The actual job title.
- company_name: The hiring company's name.
- seniority: Infer from requirements/responsibilities if not explicitly stated.
- hard_skills: Technical/hard skills mentioned in the JD.
- must_haves: Absolute mandatory requirements (e.g., years of experience, specific certifications, degrees).
- nice_to_haves: Preferred or bonus qualifications.
- If a field cannot be found or the input is just boilerplate, return null or empty lists for those fields.
"""

def _cache_key(raw_jd_text: str) -> str:
    digest = hashlib.sha256(f"{_JD_PARSER_SYSTEM_PROMPT}\n{raw_jd_text}".encode()).hexdigest()
    return f"jd_parse:{digest}"


def _cached_parse(key: str) -> Optional[str]:
    try:
        from backend.repositories import kv_repository
        entry = kv_repository.get(key)
        return entry.value if entry and entry.value else None
    except Exception as exc:
        logger.warning("jd_parser: cache read failed (parsing afresh): %s", exc)
        return None


def _store_parse(key: str, raw_reply: str) -> None:
    try:
        from backend.repositories import kv_repository
        kv_repository.upsert(key, raw_reply)
    except Exception as exc:
        logger.warning("jd_parser: cache write failed (next scoring parses again): %s", exc)


@dataclass
class ParsedJD:
    formatted_text: str
    company_name: Optional[str]


class JDParserAgent:
    def __init__(self, model: str = "claude-sonnet-4-6"):
        self.model = model

    async def parse_and_format_jd(self, raw_jd_text: str) -> ParsedJD:
        """
        Parse raw JD text and return a tightly formatted string omitting empty fields,
        along with the extracted company name (if any).
        """
        if not raw_jd_text or not raw_jd_text.strip():
            return ParsedJD(formatted_text="", company_name=None)
            
        user_message = f"Raw Job Description:\n{raw_jd_text}\n\nReturn the JSON object now."

        try:
            # The parsed ad feeds the scorer's prompt. Parsed afresh on every
            # scoring, the same ad came back worded differently each time and
            # the score moved with it; the first parse of an ad is now kept.
            cache_key = _cache_key(raw_jd_text)
            raw_reply = _cached_parse(cache_key)
            if raw_reply is None:
                result = await call_llm(
                    system=_JD_PARSER_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_message}],
                    model=self.model,
                    max_tokens=1024,
                    temperature=0.0,
                    purpose="jd_parser_parse_and_format",
                )
                raw_reply = result.text
                payload = _parse_json(raw_reply)
                _store_parse(cache_key, raw_reply)
            else:
                payload = _parse_json(raw_reply)

            # Format output without artificial padding
            formatted_lines = []
            
            role_title = payload.get("role_title")
            if role_title:
                formatted_lines.append(f"Role: {role_title}")
                
            company_name = payload.get("company_name")
            if company_name:
                formatted_lines.append(f"Company: {company_name}")
                
            seniority = payload.get("seniority")
            if seniority:
                formatted_lines.append(f"Seniority: {seniority}")
                
            hard_skills = payload.get("hard_skills") or []
            if hard_skills:
                formatted_lines.append(f"Hard Skills: {', '.join(hard_skills)}")
                
            must_haves = payload.get("must_haves") or []
            if must_haves:
                formatted_lines.append("Must Haves:")
                for item in must_haves:
                    formatted_lines.append(f"- {item}")
                    
            nice_to_haves = payload.get("nice_to_haves") or []
            if nice_to_haves:
                formatted_lines.append("Nice to Haves:")
                for item in nice_to_haves:
                    formatted_lines.append(f"- {item}")
                    
            formatted_text = "\n".join(formatted_lines).strip()
            
            return ParsedJD(
                formatted_text=formatted_text,
                company_name=company_name
            )

        except Exception as exc:
            logger.error("parse_and_format_jd failed: %s", exc)
            # In case of failure, return the raw text to gracefully degrade,
            # but empty company name.
            return ParsedJD(formatted_text=raw_jd_text, company_name=None)
