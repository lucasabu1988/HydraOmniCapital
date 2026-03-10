# i18n EN/ESP Toggle — Design Doc

**Date**: 2026-03-09
**Scope**: Add language toggle (EN/ESP) to omnicapital.onrender.com

## Approach

Client-side `data-i18n` + JS dictionary. No new dependencies.

## Architecture

- **New file**: `static/js/i18n.js` — loaded before `dashboard.js`
  - `TRANSLATIONS = { es: {...}, en: {...} }` — all translatable strings
  - `t(key)` — returns translation for active language
  - `setLang(lang)` — updates all `[data-i18n]` and `[data-i18n-html]` elements
  - `currentLang` global variable

- **HTML**: `data-i18n="key"` on translatable elements, `data-i18n-html="key"` for strings with embedded HTML (links, formatting)

- **JS dynamic strings**: replace hardcoded Spanish with `t('key')` calls in `dashboard.js`

## Toggle UI

- Pill-style button in header bar, next to dark mode toggle
- Shows `ES | EN` with active language highlighted
- Default: `es` (Spanish)
- Persisted in `localStorage` key `hydra-lang`
- Applied immediately on page load (no flash)

## Scope (~150-200 keys)

- Header: labels, market status, regime pills
- Tabs: Dashboard, Noticias/News, Roadmap, Algoritmo/Algorithm, ML
- Metric cards: labels, subs
- Regime/Overlay: labels, full explanations with FRED links
- Positions: headers, tooltips, labels
- Social feed: titles, filters
- Roadmap: phases, descriptions, checklist items
- Algoritmo page: full content
- ML page: labels
- Disclaimers

## Behavior

- Instant language switch — no page reload
- Dynamic components re-render on language change
- Chart.js tooltips update on next refresh or re-render
- SEO meta tags stay in English (crawlers don't execute toggle JS)
- `<details>` sections translated via `data-i18n-html`
