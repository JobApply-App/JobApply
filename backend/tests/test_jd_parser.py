import pytest

from backend.agents.jd_parser import JDParserAgent

@pytest.mark.asyncio
async def test_jd_parser_noisy_html():
    parser = JDParserAgent()
    noisy_html = """
    <html>
        <body>
            <nav>Home | About Us | Careers</nav>
            <div class="cookie-banner">We use cookies to improve your experience.</div>
            <div class="job-content">
                <h1>Senior Python Engineer</h1>
                <p>Welcome to Acme Corp!</p>
                <h2>Requirements:</h2>
                <ul>
                    <li>5+ years of Python</li>
                    <li>Experience with Django and Postgres</li>
                </ul>
                <h2>Nice to have:</h2>
                <ul>
                    <li>AWS certification</li>
                </ul>
            </div>
            <footer>Copyright 2026 Acme Corp</footer>
        </body>
    </html>
    """
    
    parsed = await parser.parse_and_format_jd(noisy_html)
    
    assert "Acme Corp" in parsed.company_name, "Should extract company name"
    assert "Senior Python Engineer" in parsed.formatted_text
    assert "Python" in parsed.formatted_text
    assert "AWS" in parsed.formatted_text
    assert "cookie" not in parsed.formatted_text.lower(), "Should strip cookie banner"
    assert "home | about us" not in parsed.formatted_text.lower(), "Should strip nav menu"


@pytest.mark.asyncio
async def test_jd_parser_bilingual():
    parser = JDParserAgent()
    bilingual_text = """
    דרוש/ה מפתח/ת Full Stack לחברת TechFlow.
    דרישות חובה:
    - 3 שנות ניסיון ב-React ו-Node.js
    - היכרות מעמיקה עם AWS
    
    יתרון:
    - ניסיון עם Kubernetes
    """
    
    parsed = await parser.parse_and_format_jd(bilingual_text)
    
    assert "TechFlow" in parsed.company_name
    assert "Full Stack" in parsed.formatted_text
    assert "React" in parsed.formatted_text
    assert "Node.js" in parsed.formatted_text
    assert "Kubernetes" in parsed.formatted_text


@pytest.mark.asyncio
async def test_jd_parser_thin_jd_fallback():
    parser = JDParserAgent()
    thin_jd = """
    <div class="cookie-banner">Please accept our cookies to continue.</div>
    <p>Software Engineer</p>
    """
    
    parsed = await parser.parse_and_format_jd(thin_jd)
    
    # The formatted text should be very short because most fields will be empty/null
    assert len(parsed.formatted_text) < 300, "Thin JD must not be artificially padded"
    assert "cookie" not in parsed.formatted_text.lower()
