# Kill Hero Section — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the 934px landing hero so the dashboard opens directly on financial data.

**Architecture:** Pure deletion — remove the hero HTML block, its dedicated CSS rules, and the carousel JS. Keep `.lh-glow` / `@keyframes glowFloat` styles that are shared by the Fondos page `fc-hero`.

**Tech Stack:** HTML, CSS, JS (no Python changes)

**Spec:** `docs/superpowers/specs/2026-03-22-kill-hero-section-design.md`

---

### Task 1: Delete hero HTML block

**Files:**
- Modify: `templates/dashboard.html:233-360`

- [ ] **Step 1: Delete the landing hero div**

Delete the entire block from `<!-- LANDING HERO — Context for first-time visitors -->` through the closing `</div>` that precedes `<!-- ═══════════ SECTION 1: ESTADO ACTUAL ═══════════ -->`. This is lines 233-360 (128 lines).

The block starts with:
```html
<!-- LANDING HERO — Context for first-time visitors -->
<div class="landing-hero">
```
And ends with:
```html
</div>

<!-- ═══════════ SECTION 1: ESTADO ACTUAL ═══════════ -->
```

Delete everything from the comment through the closing `</div>`, leaving the SECTION 1 comment intact.

- [ ] **Step 2: Verify HTML is valid**

Run: `python -c "from html.parser import HTMLParser; HTMLParser().feed(open('templates/dashboard.html').read()); print('HTML parse OK')"`

Expected: `HTML parse OK`

- [ ] **Step 3: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat: remove landing hero HTML block (934px → 0px)"
```

---

### Task 2: Delete hero carousel JS

**Files:**
- Modify: `static/js/dashboard.js:3260-3329`

- [ ] **Step 1: Delete the hero carousel IIFE**

Delete the entire block from the comment `/* ============ HERO STATS CAROUSEL (Two Sigma-inspired) ============ */` through the closing `})();` that precedes `/* ============ FUND COMPARISON PAGE ============ */`. This is lines 3260-3329 (70 lines).

The block starts with:
```js
/* ============ HERO STATS CAROUSEL (Two Sigma-inspired) ============ */
(function() {
```
And ends with:
```js
})();

/* ============ FUND COMPARISON PAGE ============ */
```

Delete everything from the comment through `})();`, leaving the FUND COMPARISON comment intact.

- [ ] **Step 2: Check for other heroCarousel references**

Search for any remaining references to `heroCarousel`, `heroCarouselPause`, `lh-dot`, or `lh-stats-slide` in `dashboard.js`. There should be none outside the deleted block.

Run: `grep -n "heroCarousel\|heroCarouselPause\|lh-dot\|lh-stats-slide" static/js/dashboard.js`

Expected: No output (no remaining references)

- [ ] **Step 3: Verify JS syntax**

Run: `node -c static/js/dashboard.js`

Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add static/js/dashboard.js
git commit -m "feat: remove hero carousel JS (70 lines)"
```

---

### Task 3: Delete hero CSS — dark/light mode overrides

**Files:**
- Modify: `static/css/dashboard.css:139-165`

- [ ] **Step 1: Delete dark mode and light mode hero overrides**

Delete lines 139-165. This block starts with `body.dark .landing-hero {` and ends with `body:not(.dark) .landing-hero::before { opacity: 0.5; }`.

**KEEP line 164** (`body:not(.dark) .lh-glow { opacity: 0.15; }`) — this is shared by `fc-hero` on the Fondos page.

So delete:
- Lines 139-163 (dark `.landing-hero`, all light `.lh-title`, `.lh-version`, `.lh-icon`, `.lh-tagline`, `.lh-stat-*`, `.lh-chalk-*`, `.lh-feature-*`, `.lh-disclaimer`)
- Line 165 (`body:not(.dark) .landing-hero::before`)

Keep:
- Line 164 (`body:not(.dark) .lh-glow { opacity: 0.15; }`)

- [ ] **Step 2: Commit**

```bash
git add static/css/dashboard.css
git commit -m "feat: remove hero dark/light mode CSS overrides"
```

---

### Task 4: Delete hero CSS — main block

**Files:**
- Modify: `static/css/dashboard.css:2316-2661`

- [ ] **Step 1: Delete the main hero CSS block**

Delete from `.landing-hero {` (line 2316) through the closing `}` of the `@media (max-width: 600px)` block (line 2661).

**KEEP these rules (shared by fc-hero / algo-hero):**
- `.lh-glow` (lines 2338-2343)
- `.lh-glow-1` (lines 2345-2350)
- `.lh-glow-2` (lines 2351-2356)
- `.lh-glow-3` (lines 2357-2362)
- `@keyframes glowFloat` (lines 2363-2367)

**DELETE everything else in this range:**
- `.landing-hero` base styles (2316-2326)
- `.landing-hero::before` (2328-2336)
- `.lh-accent-line` + `@keyframes shimmerLine` (2369-2379)
- `.landing-hero > *:not(.lh-glow)` (2380)
- `.lh-chalkboard` through `.lh-chalk-divider` (2382-2479)
- `@media (max-width: 600px)` chalkboard overrides (2480-2486)
- `.lh-brand` through `.lh-icon:hover` (2488-2506)
- `.lh-title-group` through `.lh-tagline` (2507-2532)
- `.lh-stats-carousel` through `.lh-carousel-pause.paused` (2535-2569)
- `@keyframes statsFadeIn` (2547-2550)
- `.lh-stats` through `.lh-disclaimer` (2571-2649)
- `@media (max-width: 600px)` hero overrides (2650-2661)

- [ ] **Step 2: Verify CSS brace balance**

Run: `python -c "css=open('static/css/dashboard.css').read(); print(f'Braces: {css.count(chr(123))} open, {css.count(chr(125))} close — {\"OK\" if css.count(chr(123))==css.count(chr(125)) else \"MISMATCH\"}")"`

Expected: `Braces: N open, N close — OK`

- [ ] **Step 3: Commit**

```bash
git add static/css/dashboard.css
git commit -m "feat: remove hero CSS block (~300 lines, keep .lh-glow shared styles)"
```

---

### Task 5: Update CSS cache-buster version

**Files:**
- Modify: `templates/dashboard.html`

- [ ] **Step 1: Update the CSS version query string**

Find `dashboard.css?v=20260318b` and change to `dashboard.css?v=20260322b`.

- [ ] **Step 2: Commit**

```bash
git add templates/dashboard.html
git commit -m "chore: bump CSS cache-buster to 20260322b"
```

---

### Task 6: Visual verification — local

**Files:** None (read-only verification)

- [ ] **Step 1: Start local server**

Run: `python compass_dashboard.py &`

Wait for Flask to start on port 5000.

- [ ] **Step 2: Screenshot dashboard page**

Navigate to `http://localhost:5000/`. Take screenshot.

Verify:
- "Estado Actual — Rendimiento en Tiempo Real" is the first content below the tab bar
- No blank space or broken layout where the hero was
- Header bar intact (logo, RISK ON, NORMAL, S&P 500, market status)

- [ ] **Step 3: Screenshot dark mode**

Verify dark mode renders correctly (no missing styles).

- [ ] **Step 4: Screenshot mobile layout**

Set viewport to 375px width. Navigate to `http://localhost:5000/`.

Verify:
- "Estado Actual" section renders correctly at narrow width
- No overflow or broken layout where the hero was removed

- [ ] **Step 5: Screenshot Fondos/Comparativa page**

Navigate to Comparativa tab. Take screenshot.

Verify:
- `fc-hero` section still has its glow orbs
- No visual regression

- [ ] **Step 6: Check console for JS errors**

Open browser console. Verify no errors related to missing carousel elements.

- [ ] **Step 7: Stop local server**

Kill the Flask process.

---

### Task 7: Run tests

- [ ] **Step 1: Run pytest**

Run: `cd "C:/Users/caslu/Desktop/NuevoProyecto" && pytest tests/ -v`

Expected: All tests pass (no tests reference the hero)

- [ ] **Step 2: Syntax check modified files**

Run:
```bash
python -c "import py_compile; py_compile.compile('compass_dashboard.py'); py_compile.compile('compass_dashboard_cloud.py'); print('OK')"
```

Expected: `OK`

---

### Task 8: Push and verify cloud deploy

- [ ] **Step 1: Push to remote**

```bash
git push
```

- [ ] **Step 2: Wait for Render deploy**

Wait ~60 seconds for Render auto-deploy via webhook.

- [ ] **Step 3: Screenshot live dashboard**

Navigate to `https://omnicapital.onrender.com/`. Take screenshot.

Verify same criteria as Task 6 Step 2 — "Estado Actual" is first content visible.

- [ ] **Step 4: Screenshot live Comparativa page**

Verify `fc-hero` glow orbs still work on production.
