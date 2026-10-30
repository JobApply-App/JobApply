# What makes a tailored CV work — research notes and what we applied

Written 2026-10-30, after a founder test: a Hebrew CV for an English job description came out half in English, scored 12 on our own ATS breakdown while the panel showed 46.7%, and read as generic.

## Evidence quality, up front

Most public material on applicant tracking systems (ATS) comes from vendors and career blogs, not independent studies. Widely repeated figures, such as "75% of CVs are rejected by an ATS", "6–7 seconds per CV" and "99.7% of recruiters use keyword filters", trace back to vendor reports or to sources that can't be verified. Nothing below rests on those numbers. What follows is the consistent practitioner consensus, marked by how strong it is.

## Findings

| # | Finding | Strength | Sources |
|---|---|---|---|
| 1 | An ATS parses the CV into fields (contact, experience, education, skills), then matches it to the posting. Some systems match exact terms; newer ones match meaning or use an LLM. A CV has to survive both: use the posting's exact terms **and** make them read naturally. | Consensus across practitioner sources | [Dover](https://www.dover.com/blog/ats-tracking-systems-guide), [Enhancv](https://enhancv.com/blog/what-is-ats/), [Interview Guys](https://blog.theinterviewguys.com/what-ats-looks-for-in-resumes/) |
| 2 | Job titles and the summary carry extra weight in matching and in a recruiter's first scan. | Consistent claim, vendor-sourced | [Interview Guys](https://blog.theinterviewguys.com/what-ats-looks-for-in-resumes/), [scale.jobs](https://scale.jobs/blog/understanding-ats-scoring-algorithms) |
| 3 | Quantified achievements (what changed, by how much, how) are what recruiters look for. The strongest result belongs first, under the most recent role. | Consistent; exact percentages unverified | [Wonsulting XYZ](https://www.wonsulting.com/job-search-hub/the-power-of-quantifiable-results-how-to-use-the-xyz-formula-to-supercharge-your-resume) |
| 4 | **Match the CV language to the posting.** English is usual for international tech companies and startups; Hebrew matters for roles serving the local market. Keep both versions if you apply to both. | Consistent across Israel-specific guides | [olehjobs](https://www.olehjobs.com/guide/israeli-cv), [Resumly](https://www.resumly.ai/ai-resume-builder-israel) |
| 5 | A Hebrew CV is rebuilt for right-to-left reading, not mirrored. A literal translation reads badly: it should be checked by a native speaker. | Consistent | [olehjobs](https://www.olehjobs.com/guide/israeli-cv) |
| 6 | Israeli conventions: a "תמצית" (summary) of up to ~3 lines with keywords so screening software finds them; reverse-chronological experience; bold headings, right-aligned. Professional terms in English are viewed positively in tech. | Israeli job boards and guides | [Drushim — פסקת תמצות](https://www.drushim.co.il/article/456/), [WorkRights](https://www.workrights.co.il/%D7%A7%D7%95%D7%A8%D7%95%D7%AA-%D7%97%D7%99%D7%99%D7%9D), [John Bryce](https://www.johnbryce.co.il/lobby-magazine/articles/how-to-write-a-resume-without-experience-working-in-high-tech/) |
| 7 | Israeli tech uses Greenhouse, Lever, Workable and Comeet, which parse differently. Nothing public documents how Comeet parses Hebrew or RTL PDFs. | Gap — needs our own test | [Korotchaim](https://korotchaim.com/en/ai-resume-builder-israel) |

Two sources (olimadvice.com, hrlens.io) could not be fetched from the build environment's network.

## What we changed (PR after #134)

- **Hebrew localization pass** (`backend/services/cv_localize.py`), per findings 4–6.
  - Writes idiomatic Israeli-market Hebrew: "תמצית", no calques, first-person past-tense bullets.
  - Keeps the posting's keywords and the industry's English terms inside the Hebrew sentence, per finding 1. This is also why keyword overlap fell to 2/40 when they were translated.
  - Rejected if it changes any number, date, company or the number of entries.
- **Grammatical gender** for Hebrew titles is chosen by the user and saved to the profile. It is never guessed from the name.
- **Hebrew typography:** one embedded Hebrew font (Heebo) and no italics.
- **Language nudge:** the preview notes when the CV language differs from the posting's, per finding 4.
- **Tailor prompt:** the most relevant, strongest bullet comes first in each role. The posting's core terms go in the title and summary, and each must be backed by a bullet (findings 2–3).
- **Honest score panel:** shows the CV's own score, not the job's feed score.
- **Cleaner keywords:** regions, adverbs and soft adjectives are no longer counted as keywords.

## Open — not done yet, in priority order

1. **Test our PDFs in a real ATS** (Comeet, Greenhouse): upload an English and a Hebrew CV and read the parsed result (finding 7). Until then, Hebrew PDF parsing is an assumption. Text extractors return RTL lines in visual order.
2. **Measure what matters:** interview rate per CV version. Our ATS score is a proxy we wrote ourselves, not ground truth.
3. **Cross-language keyword matching:** the score matches literal terms. A Hebrew CV for an English posting scores low even when the meaning matches. A bilingual synonym table (as `title_search.py` already does for titles) would fix the score without changing the CV.
4. **Native-speaker review** of a sample of localized Hebrew CVs before relying on the pass at scale (finding 5).
