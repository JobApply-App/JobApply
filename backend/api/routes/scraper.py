from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl
from typing import Optional
from datetime import datetime, timezone
import httpx
import logging

from backend.scrapers.base_scraper import BaseScraper
from backend.schemas.job import RawJobPosting

logger = logging.getLogger(__name__)

router = APIRouter()

class PreviewRequest(BaseModel):
    url: HttpUrl
    html: Optional[str] = None

class PreviewScraper(BaseScraper):
    """
    A generic scraper for the preview tool that leverages the integrated
    proxy_manager and parsing_engine from BaseScraper.
    """
    def __init__(self, url: str):
        super().__init__(company_name="Preview", company_url=url)
        self.url = url

    async def fetch_jobs(self):
        pass  # Not used for preview
        
    async def preview(self, html: Optional[str] = None) -> RawJobPosting:
        if not html:
            try:
                response = await self.proxy_manager.fetch_with_retry(self.url)
                html = response.text
            except httpx.TimeoutException:
                raise HTTPException(status_code=504, detail="Request to target URL timed out")
            except Exception as e:
                logger.error(f"[PreviewScraper] Failed to fetch {self.url}: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to fetch URL: {str(e)}")

        if not html:
            raise HTTPException(status_code=500, detail="Empty response from target URL")

        try:
            # Parse using the integrated parsing engine
            soup = self.parser.parse_html(html)
            raw_text = self.parser.clean_html(html)
            
            # Attempt to extract generic metadata
            title = self.parser.extract_text_by_selector(soup, "h1") or "Unknown Title"
            
            return RawJobPosting(
                id="preview-12345",
                title=title,
                company="Preview Company",
                source_url=self.url,
                raw_text=raw_text,
                scraped_at=datetime.now(timezone.utc).isoformat()
            )
        except Exception as e:
            logger.error(f"[PreviewScraper] Parsing failed for {self.url}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to parse HTML: {str(e)}")

@router.post("/preview", response_model=RawJobPosting)
async def preview_scraper(payload: PreviewRequest):
    """
    Exposes the core scraping architecture for frontend preview.
    Fetches the URL using the proxy manager (unless raw HTML is provided),
    parses it with the parsing engine, and returns a structured RawJobPosting.
    """
    scraper = PreviewScraper(url=str(payload.url))
    return await scraper.preview(html=payload.html)
