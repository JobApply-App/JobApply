# Security review, November 2026

Scope: the FastAPI backend, the Next.js frontend and its API routes, dependencies, and the production configuration in `render.yaml`. Live probing from the review environment was not possible (its network proxy blocks Render and Supabase), so everything below comes from the code, the production logs and local reproduction.

## Fixed in this change

| # | Finding | Severity | Fix |
|---|---|---|---|
| 1 | **SSRF.** `/api/jobs/analyze`, `/api/jobs/analyze-job` and `/api/jobs/scrape` fetched any URL the user sent, following redirects. A link such as `http://10.x.x.x/...`, `http://localhost:8000/...` or `http://169.254.169.254/...` made the server read its own internal network, and the page text was stored on a job the user could read back. Routing by substring (`"linkedin.com" in url`) also sent `http://10.0.0.1/?linkedin.com` to the LinkedIn scraper. | High | `backend/utilities/safe_url.py`: http(s) only, the host must resolve to public addresses only, and every redirect hop is checked. Enforced in the three scraper entry points every fetch passes through, plus a clear `invalid_job_url` error at the API. The company-scrape list is capped at 10 entries. |
| 2 | **Anonymous rate limit shared by everyone.** Behind Render's load balancer every anonymous request arrived from one of about four internal 10.x addresses (production logs), so one abuser could exhaust the public chat's limit for all visitors. | Medium | The client is the last `X-Forwarded-For` entry, which the balancer appends. Entries the client sent itself are ignored, so the key cannot be spoofed. |
| 3 | **JWT algorithm taken from the token.** The algorithm used to verify a token came from the token's own header. A forged `HS256`/`none` token was still refused, but only because the key happens to be passed as a JWK dict. Verified by forging tokens locally. | Low (hardening) | Only asymmetric algorithms (RS/ES/EdDSA) are accepted. |
| 4 | **Vulnerable dependencies.** | Mixed | Upgraded `requests`, `python-multipart`, `pymupdf`, `python-dotenv`, `python-jose`, `pdfplumber` (and `pdfminer.six`), `aiohttp`, `lxml`, `next` (14.2.29 to 14.2.35), `zod`. |

## Checked and in good shape

- **Secrets:** none in the code or the git history (placeholders only).
- **Authentication:** every API route needs a signed-in user except `/health` and the anonymous support chat.
- **Admin routes** check the admin flag. Routes with a `user_id` in the path refuse anyone else's id.
- **Ownership:** background tasks, chat sessions, interviews, applications, jobs and agent controls are all looked up by the signed-in user.
- **SQL:** parameterised throughout. The few f-strings interpolate fixed column names or integers.
- **CV PDFs:** every field is HTML-escaped in all five templates and the legacy one (tested by injecting markup into every field), and no user value is placed in an HTML attribute.
- **Uploads:** 10 MB per file, 10 files, file signature checked against the extension.
- **Email webhook:** secret compared in constant time. Production refuses to start without it (`STRICT_CONFIG`).
- **Production mode:** API docs off, CORS limited to the configured origins, HSTS, `nosniff` and `X-Frame-Options: DENY` on the backend, `frame-ancestors 'none'` on the frontend.
- **Supabase RLS:** enabled by migration on every tenant table the code creates (`b19a4c6d2e71`, `e34f0ea56e30`). Legacy tables were dropped.
- **Frontend:** no `dangerouslySetInnerHTML` or `eval` in app code.

## Open, needs a decision or a bigger change

1. **Email enumeration on sign-up.** `POST /api/auth/check-email` (public) tells anyone whether an email address has an account. On a job-search product that reveals that a person is looking for work. Each call also lists every user with the service-role key, which makes it a cheap way to load Supabase. Options:
   - Remove it, and show "if you already have an account, sign in" after sign-up. This is the safest option, at the cost of a slightly less direct message.
   - Keep it with a per-IP limit, which still leaks, just more slowly.
2. **FastAPI/Starlette upgrade.** Starlette 0.41.3 has denial-of-service advisories, fixed only in versions that need a newer FastAPI (0.115 to current). That is a framework upgrade of its own, with a full test pass.
3. **Next.js 14 is out of support.** 14.2.35 is the last 14.x patch. The remaining advisories are fixed only in Next 16 (React 19). The worst of them (remote code execution) are in the image optimizer, which this app does not use (`next/image` is not imported), and some are mitigated by Vercel's platform. The upgrade should still be planned.
4. **Supabase Security Advisor.** RLS was verified from the migrations, not against the live database. Run Dashboard, then Advisors, then Security, once, to confirm there is no table without RLS. The same goes for anything created by hand in the dashboard.
5. **Chunked request bodies** skip the `Content-Length` size check. Multipart uploads are still capped per file. A JSON body sent chunked is read whole. Render's proxy may already limit this; worth a check under load.
6. **DNS rebinding** can still pass the SSRF check: a host that resolves to a public address when checked and a private one when connected. Closing it means pinning the resolved address into the connection. Low priority after the fix above.
