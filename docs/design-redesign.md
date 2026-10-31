# JobApply redesign (November 2026)

The product is being redesigned screen by screen so that it looks designed rather than generated, with motion and materials inspired by Apple. Each phase ships as its own pull request and reaches production when it is merged. This file holds the rules every phase follows and the order of the phases.

Audience: `docs/target-audience.md` (31 October 2026). Prototypes Ron approved the direction of: `.hallmark/` in the main checkout (English landing prototype, 31 October).

## What does not change

- **The palette, exactly.** Every `ja-*` token: teal `#0D9488` and its hover `#0F766E`, the teal-50 surface, harbor `#134E4A`, ink-deep `#0A1F1C`, Ariel violet `#7C3AED` and violet-50, the slate canvas and ink, and the score-band colours in `src/lib/scoreBand.ts`. New colours are not added; new transparencies of existing ones are.
- **The fonts.** Inter for Latin, Assistant for Hebrew.
- **The logo.** `src/components/ui/Logo.tsx` (teal square, two lines and a check). It may be replaced later; until then every surface uses it.
- **Ariel's chat colours, as the product has them.** The user's message sits on teal-50, Ariel's answer on white with a slate-100 border, Ariel's avatar is the violet-to-teal gradient with an "A". Violet marks Ariel's identity (avatar, header, focus ring of her input), not her message bubbles.
- **Accessibility.** Body text at 4.5:1 contrast or better, a visible focus ring on every control, the accessibility menu's preferences, right-to-left layout.

## The rules

**Motion**
- One curve: `cubic-bezier(0.23, 1, 0.32, 1)` (`ease-ja-out`, `--ja-ease-out`), now Tailwind's default for every `transition` class.
- Three durations: 120ms for press feedback (`duration-ja-press`), 240ms for a UI change (`duration-ja-ui`), 400ms for something arriving (`duration-ja-enter`). Nothing a user waits on is longer than 400ms.
- Controls answer on press (`ja-press`, scale 0.97), not on release.
- Things leave the way they came: a sheet that rises from the bottom drops back to it, and a popover scales from the control that opened it.
- Animate `transform` and `opacity` only. Never `transition-all` in new code.
- Reduced motion: movement collapses to its end state, and looping loaders keep running so a wait never looks frozen. This now applies app-wide (`globals.css`), on top of the accessibility menu's own switch.
- Motion has a reason: it shows where something came from, confirms an action, or draws the eye to a change (a score going up). Decoration that runs on every visit is cut.

**Material and depth**
- Chrome that content scrolls under is translucent (`ja-glass`): the header first, then the tab bar and sticky toolbars. Solid white for viewers who ask the OS for less transparency.
- Elevation comes from layered, teal-tinted shadows (`shadow-elevation-1`, `shadow-elevation-2`, `shadow-floating`), never a flat `shadow-md`/`shadow-lg`.
- One dark surface per page at most (the `ja-gradient-abyss` band), used for the moment that matters, such as Ariel on the landing page.

**Type and layout**
- Large headings take negative tracking (about -0.03em to -0.045em at display size); body text none.
- Hierarchy comes from weight and size together; emphasis from weight, not colour.
- One idea per screen on marketing pages; short copy, few calls to action. Fullness comes from showing the product, not from more words.
- No eyebrows or tracked capitals above headings, no invented numbers, quotes or logos. Real figures only (nearly 10,000 LinkedIn jobs; daily limits of 10 analyses, 4 tailored CVs, 40 Ariel messages). Never write "free".

## Phases

Each phase is one pull request. A phase is done when it builds, has been checked in the browser on desktop and phone, and Ron has merged it.

1. **Foundation** (this PR). Motion and material tokens, the app-wide easing, teal-tinted shadows, a richer modal entrance for all eleven modals that share it, app-wide reduced motion, the translucent header.
2. **Public landing page.** Rebuild `LandingPage` in `src/app/page.tsx` on the English prototype, in Hebrew and English through the locales, with Ron's notes from 31 October: the real logo, Ariel in the product's own colours, more product and more motion without more copy or calls to action, a more engaging questions section. Public header and footer.
3. **App shell.** Header layout, mobile tab bar, site footer, page and tab transitions, the shared `Button`, `IconBtn`, `Pill` and `Toggle` adopted where screens hand-roll them.
4. **Core screens.** Overview, Matches (`JobFeed`, `JobCard`, `MatchScorePanel`), All jobs.
5. **Ariel.** Chat overlay and launcher, message motion, the welcome state.
6. **Modals and drawers.** Tailored CV, Verify fit, Interview simulator, Outreach, Direct pitch, Email setup, Report drawer, Controls sheet: shared enter and exit, bottom sheets on phones.
7. **Sign-up, log-in and onboarding.** Auth layout, career-stage cards, profile builder, CV upload and its progress.
8. **The rest.** Applications, Analytics, Capabilities (Trust dashboard), legal and accessibility pages, empty and error states.
