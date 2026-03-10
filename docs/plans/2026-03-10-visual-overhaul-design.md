# OmniCapital Visual Overhaul — Design Document

**Date:** 2026-03-10
**Status:** Approved
**Audience:** Daily monitoring (self) + investor/partner showcase
**Theme:** Dark mode only
**Direction:** "Precision Quantitative" — Two Sigma meets Stripe. Calm authority.

---

## Current State

Dashboard at B+/A- level. Good foundations (Plus Jakarta Sans + JetBrains Mono, dark palette #08081a, glassmorphism, mesh gradients). Seven problems prevent A+ fintech product:

1. No information hierarchy — everything same visual weight
2. Hero carousel stats too small (28px, should be 40-56px)
3. Typography scale compressed — largest number ~28px
4. Metric cards identical — Portfolio Value should dominate
5. Charts are Chart.js defaults
6. Position cards flat — P&L same weight as entry price
7. Inconsistent spacing (6px, 18px, 24px — no system)

---

## 1. Typography Scale Overhaul

```css
--type-xs:      10px;
--type-sm:      11px;
--type-base:    13px;
--type-md:      14px;
--type-lg:      16px;
--type-xl:      20px;
--type-2xl:     24px;
--type-3xl:     clamp(28px, 3.5vw, 36px);
--type-hero:    clamp(40px, 5vw, 56px);
--type-display: clamp(48px, 6vw, 72px);
```

- Portfolio Value: 48px JetBrains Mono 700
- Hero carousel stats (CAGR, Sharpe, MaxDD): 40-56px JetBrains Mono 800
- Secondary metrics (Cash, Drawdown, Positions): 24-28px
- Section labels: 11px uppercase, letter-spacing 2px
- Body: 13-14px Plus Jakarta Sans

## 2. Spacing — 8px Baseline Grid

```css
--space-1:   4px;
--space-2:   8px;
--space-3:   12px;
--space-4:   16px;
--space-5:   20px;
--space-6:   24px;
--space-8:   32px;
--space-10:  40px;
--space-12:  48px;
--space-16:  64px;
```

- Within cards: 16px
- Between cards: 24px
- Between sections: 32px
- Hero padding: 48px
- No arbitrary values

## 3. Hero Carousel Upgrade

- Keep 3-slide structure
- Stats at 40-56px JetBrains Mono (up from ~28px)
- Smooth cross-fade transitions (400ms)
- Dot indicators min 44px touch target
- All text legible without waiting for rotation

## 4. Annual Returns Chart — Bloomberg Style

- Taller container (more vertical breathing room)
- Positive bars: solid #10b981 (emerald)
- Negative bars: solid #f43f5e (rose)
- SPY bars: rgba(100, 116, 139, 0.3) (quiet slate)
- Year labels: 12px JetBrains Mono
- Zero-baseline: 0.5px rgba(255,255,255,0.2)
- Percentage values on HYDRA bars only
- Reduce grid lines to 4 references (0%, +/-10%, +/-20%)

## 5. Portfolio Value Card — Full Width Hero

- Spans full width (or 2x other cards)
- Dollar amount: 48px Mono 700
- Today's P&L: 20px, colored green/red
- Cash allocation: thin 4px progress bar
- Other 4 metric cards in 4-column grid below

## 6. Position Cards — Typography + Spacing Polish

- Keep current layout and info density
- Internal spacing to 8px grid
- P&L numbers slightly larger weight/size
- Add P&L icons (up/down arrows) alongside colors
- Remove scale() hover transforms, use border-glow hover
- Hold day progress as thin 3px bar at card bottom

## 7. Color Refinements (Dark Mode)

```css
--bg-root:       #07071a;    /* 1 step deeper */
--positive:      #10b981;    /* emerald */
--negative:      #f43f5e;    /* rose */
--accent-2:      #0ea5e9;    /* sky blue for SPY/market data */
--neutral:       #64748b;    /* slate for reference data */
```

Keep accent indigo (#4f46e5) for brand/regime.

## 8. Motion & Animation

- Number countups: 0 to final over 800ms ease-out
- Value flash: green/red 600ms pulse on P&L change
- Entrance translateY: 20px to 12px
- Remove card scale transforms on hover (border-glow only)
- Tab cross-fade: 200ms opacity on page switch
- All wrapped in prefers-reduced-motion check

## 9. Remove Light Mode

- Delete dark mode toggle from header
- Remove all light mode CSS overrides
- Remove initDarkMode() / toggleDarkMode() JS
- Set dark class permanently on body
- Reclaim header space

## 10. Accessibility

- Fix contrast on muted text (min #8888a0)
- Add :focus-visible outlines
- P&L arrows alongside color coding
- Touch targets min 44px on mobile
- aria-label on interactive elements

## What We're NOT Changing

- No sidebar navigation (keep top tabs)
- No decorative illustrations
- No gradient-filled chart bars
- No additional colors beyond refined palette
- No new border-radius (keep 8-16px)
- No scroll-triggered animations on data
- No API or data flow changes
