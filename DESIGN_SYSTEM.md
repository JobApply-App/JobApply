# JobApply Design System: 'Editorial Intercom'

> **Being redesigned (November 2026).** `docs/design-redesign.md` holds the motion, material and layout rules every screen is moving to, and the order of the phases. Where the two disagree, that file wins: for example, section labels in tracked capitals are no longer used.

## 1. Core Philosophy

**Boxless UI:** Avoid wrapping inner content in nested boxes/cards. Rely on generous whitespace (`gap-8`, `mb-12`), typography hierarchy, and subtle bottom-borders for separation.

**Aesthetic:** Premium, serene, tech-forward. Strictly NO corporate blues (like LinkedIn).

---

## 2. Color Tokens (Tailwind)

| Role | Token | Hex |
|---|---|---|
| Primary | `bg-teal-600`, `text-teal-600` | `#0D9488` |
| Canvas Background | `bg-slate-50` | `#F8FAFC` |
| Surface Background | `bg-white` | `#FFFFFF` |
| Primary Text / Headings | `text-slate-900` | — |
| Secondary / Muted Text | `text-slate-500` | — |
| Borders | `border-slate-100` or `border-slate-200` | Ultra-thin, cool slate |

---

## 3. Shapes & Elevation

**Radii:**
- `rounded-2xl` — main cards and modals
- `rounded-lg` — buttons and inputs
- Avoid `rounded-full` (pill shapes) unless for specific status dots or small badges

**Shadows:** Use multi-layered micro-shadows (e.g., custom `shadow-elevation-1`). Avoid flat/harsh generic shadows.

Reference shadow values:
```
/* Floating card */
box-shadow: 0 2px 8px rgba(0,0,0,0.02), 0 20px 40px rgba(0,0,0,0.03);

/* Elevated (expanded/active) */
box-shadow: 0 4px 16px rgba(15,23,42,0.08), 0 1px 3px rgba(15,23,42,0.05);
```

---

## 4. Layout & Navigation

**Workspace:** Full-bleed fluid width up to 1920px — `max-w-[1920px] mx-auto`.

**Header / Tabs:**
- Active states must be plain text with a bottom border only
- Required classes: `border-b-2 border-slate-900 pb-5` (or equivalent teal variant for primary tabs)
- **Never** use full boxed borders, `rounded-full`, or pill shapes for main navigation tabs
- **Never** use `ring-*` classes on navigation links

**JobCard Container must use:**
```
bg-white rounded-2xl border border-slate-100
shadow-[0_2px_8px_rgba(0,0,0,0.02),0_20px_40px_rgba(0,0,0,0.03)]
```

---

## 5. AI Chat Component

**Token Efficiency:** AI must be On-Demand. No persistent split-screen listening.

**UI:** Triggered via specific contextual buttons or a bottom-right FAB, opening as a floating overlay — never embedded inline in the main workspace.

---

## 6. Typography Scale

| Usage | Classes |
|---|---|
| Page heading | `text-[22px] font-semibold text-slate-900 tracking-tight` |
| Section label | `text-[10.5px] font-bold tracking-widest uppercase text-slate-400` |
| Body / card text | `text-[13px] text-slate-700` |
| Secondary / meta | `text-[12px] text-slate-500` |
| Micro / badge | `text-[10px] font-semibold` |

---

## 7. Component Anti-Patterns (Forbidden)

- ❌ Nested card-in-card layouts for primary content
- ❌ Corporate blue (`#0A66C2`, `bg-blue-*`) as a primary accent
- ❌ `rounded-full` on navigation tabs or primary action buttons
- ❌ `ring-*` on navigation tabs
- ❌ Persistent split-screen AI chat panel
- ❌ Hard box shadows (`shadow-md`, `shadow-lg` without customization)
- ❌ Truncating experience arrays before passing to LLM (see CLAUDE.md scoring rules)
