# Kill Hero Section — Design Spec

**Date:** 2026-03-22
**Status:** Approved
**Objective:** Remove the 934px landing hero from the dashboard so the user sees financial data immediately on page load.

## Problem

The landing hero occupies 934px (128% of viewport). It contains static backtest stats (CAGR, Sharpe, MaxDD), decorative elements, and marketing copy. The primary user (portfolio owner) must scroll past a full screen of branding every time they open the dashboard to reach actionable data.

All hero content is redundant:
- Brand identity → already in header bar
- Backtest stats → already in "Track Record" section
- Disclaimer → already in footer
- Strategy list → already in "Posiciones / Estrategias Activas" section

## Solution

Delete the entire `<div class="landing-hero">` block and all associated CSS/JS. No replacement element. The dashboard opens directly on "Estado Actual — Rendimiento en Tiempo Real".

## Scope

### HTML — `templates/dashboard.html`
- Delete `<div class="landing-hero">...</div>` (~130 lines, lines 233–360)
- This includes: 3 glow orbs, accent line, brand group, tagline, stats carousel (4 slides), carousel controls, feature pills, disclaimer

### CSS — `static/css/dashboard.css`
- Delete all `.landing-hero` rules (base + dark mode + light mode)
- Delete all `.lh-*` rules: `.lh-glow`, `.lh-accent-line`, `.lh-brand`, `.lh-icon`, `.lh-title`, `.lh-title-group`, `.lh-version`, `.lh-tagline`, `.lh-stats-carousel`, `.lh-stats`, `.lh-stat`, `.lh-stat-*`, `.lh-carousel-*`, `.lh-dot`, `.lh-features`, `.lh-feature`, `.lh-feature-dot`, `.lh-disclaimer`, `.lh-chalkboard`, `.lh-chalk-*`
- Delete `@keyframes glowFloat`, `@keyframes shimmerLine`, `@keyframes statsFadeIn`
- Delete associated `@media` responsive overrides for all above selectors
- Estimated: ~350 lines removed

### JS — `static/js/dashboard.js`
- Delete hero carousel logic (auto-rotation, dot clicks, pause button, slide transitions)
- Search for all references to `heroCarousel`, `heroCarouselPause`, `lh-dot`, `lh-stats-slide`

### Not touched
- Header bar (logo, RISK ON/OFF, regime, S&P 500, market status)
- "Estado Actual" section and everything below it
- Footer disclaimer
- "Track Record" section (already has all backtest stats)
- Comparativa page hero (separate element, different page)
- Any other page's hero sections (algo-hero on Comparativa page references `.lh-glow` — verify if shared)

## Verification

1. Dashboard loads with "Estado Actual" as first visible content below the tab bar
2. No orphaned CSS classes referencing deleted elements
3. No JS errors in console from missing carousel elements
4. Dark mode and light mode both work
5. Mobile layout still works
6. Comparativa page unaffected (check if it shares any `.lh-*` classes)
7. All existing tests pass

## Risk

**Low.** Pure deletion of self-contained UI block. No data flow, API, or engine changes. The only risk is orphaned references — the Comparativa page has `.lh-glow` elements that may share styles.
