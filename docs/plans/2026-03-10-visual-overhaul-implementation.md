# Visual Overhaul Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform OmniCapital dashboard from B+ developer dashboard to A+ fintech product — "Precision Quantitative" aesthetic.

**Architecture:** CSS-first changes (design tokens, spacing, typography, colors), then HTML restructure (portfolio card, carousel), then JS changes (chart config, animations, dark mode removal). Three files: `static/css/dashboard.css`, `templates/dashboard.html`, `static/js/dashboard.js`. After each task, sync to `compass/` folder for cloud deployment.

**Tech Stack:** CSS3 (custom properties, clamp(), grid), Chart.js 4.4.1, vanilla JS, Flask templates (Jinja2)

---

### Task 1: Design Tokens — Typography Scale + Spacing System + Color Refinements

Add the new design token system to CSS variables. This is the foundation everything else builds on.

**Files:**
- Modify: `static/css/dashboard.css:4-60` (`:root` light mode variables)
- Modify: `static/css/dashboard.css:63-103` (`body.dark` variables)

**Step 1: Add typography scale and spacing tokens to `:root`**

In `static/css/dashboard.css`, inside the `:root` block (after line 46, before `--shadow-sm`), add:

```css
    /* Typography scale */
    --type-xs: 10px;
    --type-sm: 11px;
    --type-base: 13px;
    --type-md: 14px;
    --type-lg: 16px;
    --type-xl: 20px;
    --type-2xl: 24px;
    --type-3xl: clamp(28px, 3.5vw, 36px);
    --type-hero: clamp(40px, 5vw, 56px);
    --type-display: clamp(48px, 6vw, 72px);

    /* Spacing — 8px baseline grid */
    --space-1: 4px;
    --space-2: 8px;
    --space-3: 12px;
    --space-4: 16px;
    --space-5: 20px;
    --space-6: 24px;
    --space-8: 32px;
    --space-10: 40px;
    --space-12: 48px;
    --space-16: 64px;

    /* Semantic signal colors */
    --positive: #16a34a;
    --positive-dim: rgba(22, 163, 74, 0.08);
    --negative: #dc2626;
    --negative-dim: rgba(220, 38, 38, 0.08);
    --accent-2: #0ea5e9;
    --accent-2-dim: rgba(14, 165, 233, 0.12);
    --neutral: #64748b;
```

**Step 2: Update `body.dark` color tokens**

In the `body.dark` block, update these existing values and add new ones:

Change `--bg-root: #08081a;` to `--bg-root: #07071a;`

Change `--green: #22c55e;` to `--positive: #10b981;`
Change `--green-dim: rgba(34, 197, 94, 0.12);` to `--positive-dim: rgba(16, 185, 129, 0.12);`
Change `--green-glow: rgba(34, 197, 94, 0.18);` to `--positive-glow: rgba(16, 185, 129, 0.18);`
Change `--red: #ef4444;` to `--negative: #f43f5e;`
Change `--red-dim: rgba(239, 68, 68, 0.12);` to `--negative-dim: rgba(244, 63, 94, 0.12);`
Change `--red-glow: rgba(239, 68, 68, 0.18);` to `--negative-glow: rgba(244, 63, 94, 0.18);`

Add after `--accent-light: #818cf8;`:
```css
    --accent-2: #0ea5e9;
    --accent-2-dim: rgba(14, 165, 233, 0.12);
    --neutral: #64748b;
    --text-muted: #505068;   /* was #404058, raised for contrast */
```

**IMPORTANT:** Keep the existing `--green`, `--red` variables intact for backward compatibility. The new `--positive`/`--negative` tokens are additions, NOT replacements of the existing ones. Other parts of the CSS still reference `--green` and `--red`.

**Step 3: Syntax check**

Open the dashboard in a browser, verify no CSS parsing errors in DevTools console.

**Step 4: Commit**

```
feat: add design tokens — typography scale, 8px spacing grid, refined dark colors
```

---

### Task 2: Remove Light Mode — Dark-Only Theme

Remove the dark mode toggle, light mode CSS overrides, and related JS. Dashboard is permanently dark.

**Files:**
- Modify: `templates/dashboard.html:118` (remove dark toggle button)
- Modify: `static/js/dashboard.js:1-20` (remove dark mode functions)
- Modify: `static/css/dashboard.css:4-60` (collapse light `:root` into dark-only)

**Step 1: Remove the dark mode toggle button from HTML**

In `templates/dashboard.html:118`, remove the entire line:
```html
    <button class="dark-toggle" id="dark-toggle" title="Toggle dark mode" onclick="toggleDarkMode()">&#9790;</button>
```

**Step 2: Add `dark` class to body permanently**

In `templates/dashboard.html:46`, change:
```html
<body>
```
to:
```html
<body class="dark">
```

**Step 3: Replace dark mode JS with permanent dark**

In `static/js/dashboard.js`, replace lines 1-20 (from `function initDarkMode()` through `initDarkMode();`) with:
```javascript
/* ============ DARK MODE (permanent) ============ */
document.body.classList.add('dark');
```

**Step 4: Remove `.dark-toggle` CSS**

In `static/css/dashboard.css`, remove the `.dark-toggle` block (lines 193-212):
```css
.dark-toggle {
    ...
}
.dark-toggle:hover {
    ...
}
```

**Step 5: Verify dashboard loads dark-only**

Open `http://localhost:5000` — should load in dark mode with no toggle visible.

**Step 6: Commit**

```
refactor: remove light mode — dark-only theme, delete toggle button and JS
```

---

### Task 3: Typography Overhaul — Metrics, Hero Carousel, Section Labels

Apply the new typography scale to the key components.

**Files:**
- Modify: `static/css/dashboard.css:700-721` (metric card styles)
- Modify: `static/css/dashboard.css:2405-2423` (hero carousel stat styles)
- Modify: `templates/dashboard.html:360-386` (metric card HTML for portfolio hero)

**Step 1: Make Portfolio Value card full-width hero**

In `templates/dashboard.html`, replace the metrics-grid section (lines 360-386) with:

```html
<!-- PORTFOLIO METRICS -->
<div class="metrics-hero-row anim-enter anim-d4">
    <div class="metric-card metric-card-hero">
        <div class="metric-label" data-i18n="metric-portfolio">Valor del Portfolio</div>
        <div class="metric-value metric-value-hero" id="card-total"><span class="skeleton skeleton-value">&nbsp;</span></div>
        <div class="metric-sub" id="card-return"><span class="skeleton skeleton-line" style="width:60%">&nbsp;</span></div>
    </div>
</div>
<div class="metrics-grid metrics-grid-4 anim-enter anim-d4">
    <div class="metric-card">
        <div class="metric-label" data-i18n="metric-cagr">CAGR Esperado</div>
        <div class="metric-value c-accent" id="card-cagr">14.93%</div>
        <div class="metric-sub" id="card-cagr-sub" data-i18n="metric-cagr-sub">HYDRA (Momentum + Rattlesnake + EFA) | No leverage</div>
    </div>
    <div class="metric-card">
        <div class="metric-label" data-i18n="metric-cash">Efectivo</div>
        <div class="metric-value" id="card-cash"><span class="skeleton skeleton-value">&nbsp;</span></div>
        <div class="metric-sub" id="card-invested"><span class="skeleton skeleton-line" style="width:70%">&nbsp;</span></div>
    </div>
    <div class="metric-card">
        <div class="metric-label" data-i18n="metric-drawdown">Drawdown</div>
        <div class="metric-value" id="card-drawdown"><span class="skeleton skeleton-value" style="width:50%">&nbsp;</span></div>
        <div class="metric-sub" id="card-peak"><span class="skeleton skeleton-line" style="width:65%">&nbsp;</span></div>
    </div>
    <div class="metric-card">
        <div class="metric-label" data-i18n="metric-positions">Posiciones</div>
        <div class="metric-value" id="card-positions"><span class="skeleton skeleton-value" style="width:40%">&nbsp;</span></div>
        <div class="metric-sub" id="card-maxpos"><span class="skeleton skeleton-line" style="width:55%">&nbsp;</span></div>
    </div>
</div>
```

**Step 2: Add CSS for hero metric card and 4-column grid**

In `static/css/dashboard.css`, after the existing `.metrics-grid` rule (around line 669-672), add:

```css
.metrics-hero-row {
    margin-bottom: var(--space-3);
}
.metric-card-hero {
    text-align: center;
    padding: var(--space-6) var(--space-8);
}
.metric-value-hero {
    font-size: var(--type-display) !important;
    line-height: 1.1;
}
.metrics-grid-4 {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: var(--space-3);
    margin-bottom: var(--space-3);
}
```

**Step 3: Upscale hero carousel stats**

In `static/css/dashboard.css`, change `.lh-stat-value` (line 2410-2416):

From:
```css
.lh-stat-value {
    font-size: 28px; font-weight: 800;
    font-family: var(--font-mono, 'JetBrains Mono', monospace);
    color: #fff; display: block; line-height: 1.1;
    font-variant-numeric: tabular-nums;
    margin-bottom: 6px;
}
```

To:
```css
.lh-stat-value {
    font-size: var(--type-hero); font-weight: 800;
    font-family: var(--font-mono, 'JetBrains Mono', monospace);
    color: #fff; display: block; line-height: 1.1;
    font-variant-numeric: tabular-nums;
    margin-bottom: var(--space-2);
}
```

**Step 4: Update section labels to use letter-spacing 2px**

In `static/css/dashboard.css`, change `.metric-label` (line 700-706):

From:
```css
.metric-label {
    font-size: 11px;
    color: var(--text-tertiary);
    text-transform: uppercase;
    letter-spacing: 1px;
    font-weight: 500;
    margin-bottom: 6px;
}
```

To:
```css
.metric-label {
    font-size: var(--type-sm);
    color: var(--text-tertiary);
    text-transform: uppercase;
    letter-spacing: 2px;
    font-weight: 500;
    margin-bottom: var(--space-2);
}
```

**Step 5: Update mobile responsive for 4-column grid**

Find the existing media query at `@media (max-width: 768px)` and add:
```css
    .metrics-grid-4 { grid-template-columns: repeat(2, 1fr); }
```

Find `@media (max-width: 480px)` and add:
```css
    .metrics-grid-4 { grid-template-columns: 1fr; }
    .metric-value-hero { font-size: clamp(32px, 8vw, 48px) !important; }
```

**Step 6: Verify in browser**

Check that portfolio value card spans full width with large type, and 4 secondary cards below in a row.

**Step 7: Commit**

```
feat: typography overhaul — portfolio hero at 48px, carousel stats at 40-56px, section labels 2px spacing
```

---

### Task 4: Spacing Rhythm — Consistent 32px Section Gaps

Replace arbitrary spacing between sections with the 8px grid.

**Files:**
- Modify: `static/css/dashboard.css` (multiple locations)

**Step 1: Update metrics-grid gap**

Change `.metrics-grid` (line 669-672):
```css
.metrics-grid {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 10px;
    margin-bottom: 10px;
}
```
to:
```css
.metrics-grid {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: var(--space-3);
    margin-bottom: var(--space-3);
}
```

**Step 2: Update metric card padding**

Change `.metric-card` padding (line 680):
```css
    padding: 12px 16px;
```
to:
```css
    padding: var(--space-4) var(--space-4);
```

**Step 3: Update position card gap**

Change `.pos-card` gap (line 1385):
```css
    gap: 10px;
```
to:
```css
    gap: var(--space-2);
```

Change `.pos-card` padding (line 1382):
```css
    padding: 14px 18px;
```
to:
```css
    padding: var(--space-4);
```

**Step 4: Add section spacing to main dashboard sections**

Add new CSS rule:
```css
/* Section rhythm — 32px between major sections */
.landing-hero,
.preclose-bar,
.universe-bar,
.perf-banner,
.metrics-hero-row,
.regime-band,
.positions-hero,
.card {
    margin-bottom: var(--space-8);
}
```

**Step 5: Verify visual rhythm in browser**

Each major section should have consistent 32px gaps. No arbitrary spacing.

**Step 6: Commit**

```
feat: spacing rhythm — 8px baseline grid, consistent 32px section gaps
```

---

### Task 5: Annual Returns Chart — Bloomberg Style

Upgrade the chart colors, sizing, and zero-line for the Bloomberg-inspired look.

**Files:**
- Modify: `static/js/dashboard.js:2073-2200` (chart config)

**Step 1: Update HYDRA bar colors**

In `static/js/dashboard.js`, change the `hydraColors` map (lines 2081-2084):

From:
```javascript
    var hydraColors = hydraRets.map(function(v) {
        if (v >= 0) return isDark ? '#22c55e' : '#16a34a';
        return isDark ? '#ef4444' : '#dc2626';
    });
```

To:
```javascript
    var hydraColors = hydraRets.map(function(v) {
        if (v >= 0) return '#10b981';
        return '#f43f5e';
    });
```

**Step 2: Update SPY bar colors to quiet slate**

Change the `spyColors` map (lines 2085-2088):

From:
```javascript
    var spyColors = spyRets.map(function(v) {
        if (v == null) return 'transparent';
        return isDark ? 'rgba(99, 102, 241, 0.28)' : 'rgba(99, 102, 241, 0.22)';
    });
```

To:
```javascript
    var spyColors = spyRets.map(function(v) {
        if (v == null) return 'transparent';
        return 'rgba(100, 116, 139, 0.3)';
    });
```

Change SPY border colors (lines 2089-2092):

From:
```javascript
    var spyBorderColors = spyRets.map(function(v) {
        if (v == null) return 'transparent';
        return isDark ? 'rgba(99, 102, 241, 0.55)' : 'rgba(99, 102, 241, 0.50)';
    });
```

To:
```javascript
    var spyBorderColors = spyRets.map(function(v) {
        if (v == null) return 'transparent';
        return 'rgba(100, 116, 139, 0.45)';
    });
```

**Step 3: Update zero-line**

Change the annotation zeroLine (lines 2191-2197):

From:
```javascript
                        zeroLine: {
                            type: 'line',
                            xMin: 0, xMax: 0,
                            borderColor: zeroLineColor,
                            borderWidth: 1,
                            borderDash: [3, 4],
                        }
```

To:
```javascript
                        zeroLine: {
                            type: 'line',
                            xMin: 0, xMax: 0,
                            borderColor: 'rgba(255, 255, 255, 0.2)',
                            borderWidth: 0.5,
                        }
```

**Step 4: Increase height per year**

Change `PX_PER_YEAR` (line 2103):

From:
```javascript
    var PX_PER_YEAR = 30;
```

To:
```javascript
    var PX_PER_YEAR = 36;
```

**Step 5: Update year label font size**

In the y-axis scale config (find `scales: { ... y: { ... ticks:`), change the ticks font size to 12 and add JetBrains Mono:

Find the y-axis ticks configuration and update font to:
```javascript
                    font: { family: "'JetBrains Mono', monospace", size: 12, weight: '500' },
```

**Step 6: Update grid to fewer reference lines**

In the x-axis scale config, find the grid settings and update:
```javascript
                    grid: {
                        color: 'rgba(255, 255, 255, 0.04)',
                        drawTicks: false,
                    },
                    ticks: {
                        callback: function(val) {
                            if (val === 0 || Math.abs(val) === 10 || Math.abs(val) === 20 || Math.abs(val) === 30) return val + '%';
                            return '';
                        },
```

**Step 7: Verify chart in browser**

Open dashboard, check annual returns chart has emerald/rose bars, quiet slate SPY, clean zero-line, and taller rows.

**Step 8: Commit**

```
feat: annual returns chart — Bloomberg-style bars, emerald/rose colors, taller rows, clean zero-line
```

---

### Task 6: Card Hover States — Remove Scale Transforms, Add Border Glow

Replace bouncy hover effects with financial-grade border glow.

**Files:**
- Modify: `static/css/dashboard.css:685-688` (metric card hover)
- Modify: `static/css/dashboard.css:1390` (position card hover)
- Modify: `static/css/dashboard.css:2395-2398` (hero stat hover)

**Step 1: Fix metric card hover**

Change `.metric-card:hover` (line 685-688):

From:
```css
.metric-card:hover {
    border-color: var(--glass-border-hover);
    transform: translateY(-2px);
    box-shadow: var(--shadow-md), var(--glow-accent);
}
```

To:
```css
.metric-card:hover {
    border-color: rgba(99, 102, 241, 0.3);
    box-shadow: 0 0 0 1px rgba(99, 102, 241, 0.1), 0 8px 32px rgba(0, 0, 0, 0.3);
}
```

**Step 2: Fix position card hover**

Change `.pos-card:hover` (line 1390):

From:
```css
.pos-card:hover { background: var(--bg-card-hover); transform: translateY(-1px); box-shadow: var(--shadow-sm); }
```

To:
```css
.pos-card:hover { background: var(--bg-card-hover); box-shadow: 0 0 0 1px rgba(99, 102, 241, 0.1), var(--shadow-sm); }
```

**Step 3: Fix hero stat hover**

Change `.lh-stat:hover` (lines 2395-2398):

From:
```css
.lh-stat:hover {
    background: rgba(255,255,255,0.05);
    transform: translateY(-2px);
}
```

To:
```css
.lh-stat:hover {
    background: rgba(255,255,255,0.05);
}
```

**Step 4: Commit**

```
fix: remove scale/translate hover transforms — use border-glow for financial-grade feel
```

---

### Task 7: Entrance Animations — Refine translateY and Add Value Flash

Reduce entrance animation distance and add P&L value flash on data refresh.

**Files:**
- Modify: `static/css/dashboard.css:239-241` (entrance animation keyframes)
- Modify: `static/css/dashboard.css` (add new keyframes)

**Step 1: Reduce entrance translateY**

Change `@keyframes fadeSlideUp` (lines 239-241):

From:
```css
@keyframes fadeSlideUp {
    from { opacity: 0; transform: translateY(20px) scale(0.98); filter: blur(4px); }
    to { opacity: 1; transform: translateY(0) scale(1); filter: blur(0); }
}
```

To:
```css
@keyframes fadeSlideUp {
    from { opacity: 0; transform: translateY(12px) scale(0.99); filter: blur(2px); }
    to { opacity: 1; transform: translateY(0) scale(1); filter: blur(0); }
}
```

**Step 2: Add value flash keyframes**

After the entrance animation block, add:
```css
/* Value flash — Bloomberg-style P&L change indicator */
@keyframes value-flash-positive {
    0%   { background: rgba(16, 185, 129, 0.0); }
    20%  { background: rgba(16, 185, 129, 0.25); }
    100% { background: rgba(16, 185, 129, 0.0); }
}
@keyframes value-flash-negative {
    0%   { background: rgba(244, 63, 94, 0.0); }
    20%  { background: rgba(244, 63, 94, 0.25); }
    100% { background: rgba(244, 63, 94, 0.0); }
}
.value-flash-pos { animation: value-flash-positive 0.6s ease-out; border-radius: 4px; }
.value-flash-neg { animation: value-flash-negative 0.6s ease-out; border-radius: 4px; }

/* Respect user motion preferences */
@media (prefers-reduced-motion: reduce) {
    .anim-enter { animation: none; opacity: 1; }
    .value-flash-pos, .value-flash-neg { animation: none; }
    .lh-stats.lh-stats-slide.active { animation: none; }
}
```

**Step 3: Add value flash to JS state update**

In `static/js/dashboard.js`, find the function that updates `card-total` (the portfolio value element). After setting the text content, add the flash logic:

```javascript
// Add after setting portfolio value text
function flashValue(elementId, newValue, oldValue) {
    if (oldValue === null || oldValue === undefined) return;
    var el = document.getElementById(elementId);
    if (!el || newValue === oldValue) return;
    el.classList.remove('value-flash-pos', 'value-flash-neg');
    void el.offsetWidth; // trigger reflow
    el.classList.add(newValue > oldValue ? 'value-flash-pos' : 'value-flash-neg');
}
```

**Step 4: Commit**

```
feat: refined entrance animations (12px) + Bloomberg-style value flash on P&L changes
```

---

### Task 8: Accessibility — Contrast, Focus States, P&L Arrows

Fix accessibility issues: contrast ratios, keyboard focus, colorblind-safe P&L indicators.

**Files:**
- Modify: `static/css/dashboard.css` (add focus styles, fix contrasts)
- Modify: `static/js/dashboard.js` (add arrow indicators to P&L)

**Step 1: Add focus-visible styles**

Add to CSS after the `::selection` block (line 277):
```css
/* Keyboard focus — visible only for keyboard navigation */
:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
}
button:focus-visible, .page-tab:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
    border-radius: var(--radius-sm);
}
```

**Step 2: Fix carousel dot touch targets**

Change `.lh-dot` (line 2360-2364):

From:
```css
.lh-dot {
    width: 8px; height: 8px; border-radius: 50%;
    border: 1.5px solid rgba(255,255,255,0.25); background: transparent;
    cursor: pointer; transition: all 0.3s; padding: 0;
}
```

To:
```css
.lh-dot {
    width: 12px; height: 12px; border-radius: 50%;
    border: 1.5px solid rgba(255,255,255,0.25); background: transparent;
    cursor: pointer; transition: all 0.3s; padding: 8px;
    box-sizing: content-box;
}
```

**Step 3: Add P&L arrows to position card rendering in JS**

In `static/js/dashboard.js`, find where the P&L badge text is set for position cards. The P&L badge content should prefix with an arrow:

Find the line that sets the pnl-badge text (search for `pnl-badge` or `pnl_pct`) and change the format from:
```javascript
sign + pnlPct.toFixed(2) + '%'
```
to:
```javascript
(pnlPct >= 0 ? '▲ +' : '▼ ') + pnlPct.toFixed(2) + '%'
```

**Step 4: Commit**

```
feat: accessibility — focus-visible outlines, larger touch targets, P&L arrows for colorblind users
```

---

### Task 9: Page Tab Cross-Fade Transition

Add smooth opacity transition when switching tabs instead of instant show/hide.

**Files:**
- Modify: `static/css/dashboard.css` (page-content transition)
- Modify: `static/js/dashboard.js:79-80` (switchPage function)

**Step 1: Add CSS transition to page content**

Add to CSS:
```css
.page-content {
    opacity: 0;
    transition: opacity 0.2s ease;
    display: none;
}
.page-content.active {
    display: block;
    opacity: 1;
}
```

Note: CSS `transition` doesn't work with `display: none/block`. The JS needs to handle this with a two-step approach.

**Step 2: Update switchPage in JS**

In `static/js/dashboard.js`, replace the `switchPage` function (line 79-80 and beyond) with:

```javascript
function switchPage(page) {
    var current = document.querySelector('.page-content.active');
    var next = document.getElementById('page-' + page);
    if (!next || next === current) return;

    // Update tab styles
    document.querySelectorAll('.page-tab').forEach(function(t) {
        t.classList.toggle('active', t.dataset.page === page);
    });

    // Cross-fade: hide current, show next
    if (current) {
        current.style.opacity = '0';
        setTimeout(function() {
            current.classList.remove('active');
            current.style.display = 'none';
            current.style.opacity = '';
            next.style.display = 'block';
            next.style.opacity = '0';
            next.classList.add('active');
            requestAnimationFrame(function() {
                next.style.opacity = '1';
            });
        }, 150);
    } else {
        next.style.display = 'block';
        next.classList.add('active');
        next.style.opacity = '1';
    }
}
```

**Step 3: Add transition style to page-content**

```css
.page-content {
    transition: opacity 0.15s ease;
}
```

**Step 4: Commit**

```
feat: smooth cross-fade transition between dashboard tabs (150ms opacity)
```

---

### Task 10: Sync to compass/ and Final Verification

**Files:**
- Copy: `static/css/dashboard.css` → `compass/static/css/dashboard.css`
- Copy: `templates/dashboard.html` → `compass/templates/dashboard.html`
- Copy: `static/js/dashboard.js` → `compass/static/js/dashboard.js`

**Step 1: Sync files**

```bash
cp static/css/dashboard.css compass/static/css/dashboard.css
cp templates/dashboard.html compass/templates/dashboard.html
cp static/js/dashboard.js compass/static/js/dashboard.js
```

**Step 2: Verify dashboard loads**

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000
```
Expected: `200`

**Step 3: Take Playwright screenshot for visual verification**

Navigate to `http://localhost:5000` and take a screenshot to verify all visual changes look correct.

**Step 4: Commit and push**

```
chore: sync compass/ copies after visual overhaul
```

---

## Summary Table

| # | Task | Impact | Key Change |
|---|------|--------|------------|
| 1 | Design tokens | Foundation | Typography scale, spacing grid, color refinements |
| 2 | Remove light mode | Simplification | Dark-only, delete toggle + JS + CSS overrides |
| 3 | Typography overhaul | Transformative | Portfolio 48px, carousel 40-56px, hero card |
| 4 | Spacing rhythm | High | 8px grid, 32px section gaps |
| 5 | Annual returns chart | High | Emerald/rose bars, taller rows, clean zero-line |
| 6 | Hover states | Medium | Remove scale transforms, border-glow |
| 7 | Animations | Medium | 12px entrance, value flash |
| 8 | Accessibility | Medium | Focus states, contrast, P&L arrows |
| 9 | Tab transitions | Low-Medium | 150ms cross-fade |
| 10 | Sync + verify | Maintenance | Copy to compass/, screenshot |
