# COMPASS Dashboard Improvement Plan
## Project Manager Assessment -- February 28, 2026

---

## 0. CURRENT STATE INVENTORY

| Dimension | Current State |
|-----------|--------------|
| Backend | `compass_dashboard_cloud.py` -- 1,403 lines, Flask, 14 API routes |
| Frontend | `templates/dashboard.html` -- 4,705 lines, monolithic (CSS + HTML + JS in one file) |
| Deploy | Render.com free tier, gunicorn 2 workers, auto-deploy on push |
| Data | Static CSV backtests + live yfinance prices (30s cache) + 6-source social feed |
| Tabs | Dashboard, Social Feed, Launch Roadmap (Research Paper tab hidden via `display:none`) |
| Auth | None. Public read-only showcase |
| Tests | None for the dashboard |
| Mobile | Partial. CSS media queries exist but limited (positions grid, roadmap) |

### Backend Route Map

| Route | Purpose | Cached? |
|-------|---------|---------|
| `/` | Render `dashboard.html` | -- |
| `/api/state` | Portfolio + positions + live prices | 30s (prices) |
| `/api/cycle-log` | 5-day cycle performance | No |
| `/api/live-chart` | COMPASS vs SPY indexed since live start | No |
| `/api/equity` | Full 26-year equity curve + milestones | No |
| `/api/equity-comparison` | COMPASS vs SPY vs Net (full period) | No |
| `/api/social-feed` | 6-source news aggregation | 5min |
| `/api/montecarlo` | Monte Carlo simulations | Forever (lazy) |
| `/api/trade-analytics` | Trade segmentation by exit/regime/sector | Forever (lazy) |
| `/api/backtest/status` | Stub (always returns not running) | -- |
| `/api/engine/*` | Stubs (showcase mode disabled) | -- |
| `/api/preflight` | Stub (showcase mode) | -- |

---

## 1. WHAT SHOULD NOT BE CHANGED

These elements work well and should be preserved:

### 1a. KEEP: Landing Hero
- The 3-metric hero (CAGR 11.57%, Sharpe 0.80, MaxDD -29.6%) is the single most important "above the fold" element. Clean, scannable, credible.
- "Bias-Corrected" label is a massive credibility signal for quant professionals.
- Disclaimer placement is appropriate and institutional-grade.

### 1b. KEEP: Fund Scatter Plot
- COMPASS vs 15 real algorithmic funds (leverage-adjusted) is the strongest differentiator on the entire dashboard. It answers the visitor's core question: "How does this compare to real funds?" within 3 seconds.
- Tooltip detail (AUM, leverage, MaxDD) is excellent.
- Category filters work well.

### 1c. KEEP: Design System Foundation
- CSS custom properties (light/dark mode), card system, typography (Inter + JetBrains Mono), color palette -- all professional and consistent.
- Animation system (skeleton loaders, fadeSlideUp) feels polished without being excessive.
- The glassmorphism header bar is on-trend for fintech.

### 1d. KEEP: Honest Disclosures
- Survivorship bias acknowledgment, DSR p-value ~0.30, declining alpha trend, failed experiments. This transparency is the dashboard's biggest competitive advantage vs. every "100% win rate" algo pitch page.

### 1e. KEEP: Live Data Architecture
- Live prices via yfinance with ThreadPoolExecutor, 30s cache, S&P 500 + ES Futures in header -- gives the dashboard a "live trading floor" feel.
- Pre-close timeline visualization (15:30-15:50 ET execution window) is unique and teaches the visitor how MOC orders work.

---

## 2. PRIORITIZATION FRAMEWORK

### Framework: Impact-on-Visitor vs. Implementation Effort

The target audience is a **finance professional** (quant, allocator, PM, or sophisticated retail) visiting for 2-5 minutes. Every improvement is scored on:

- **VISITOR IMPACT**: Does this change what the visitor *thinks* about COMPASS within their first 2 minutes? (High / Medium / Low)
- **IMPLEMENTATION EFFORT**: How long for a solo developer? (S = <4h, M = 4-16h, L = 16-40h, XL = 40+h)
- **RISK**: Could this break the current deployment or introduce regressions? (Low / Medium / High)

### Priority Tiers

| Priority | Criteria |
|----------|----------|
| P0 | High visitor impact + Small/Medium effort. Do these first. |
| P1 | High visitor impact + Large effort, OR Medium impact + Small effort. |
| P2 | Medium impact + Medium/Large effort. Schedule for later. |
| P3 | Low impact or XL effort. Backlog/never. |

---

## 3. PHASE 1: QUICK WINS (1-2 days)

### P0-1. Fix the Cold Start / "Wake Up" Experience
- **Problem**: Render free tier sleeps after 15 min inactivity. First visitor sees "CONNECTING TO SERVER..." with "--" placeholders for 10-30 seconds. For a finance professional, this looks broken.
- **Solution**: (a) Add a real loading state with the COMPASS logo + "Dashboard loading..." message with a subtle animation. (b) Show the static hero metrics and scatter chart IMMEDIATELY (they require no API call -- fund data is hardcoded in JS, hero metrics are hardcoded in HTML). (c) Only skeleton-load the dynamic sections (positions, cycle log, prices).
- **Effort**: S (2-4 hours)
- **Files**: `templates/dashboard.html` (JS init section + skeleton states)
- **Acceptance criteria**: A visitor sees the hero, scatter chart, and research paper content within 1 second of page load, even before the API responds.

### P0-2. Remove Dead / Internal-Only UI Elements
- **Problem**: Engine bar (`display:none`), production config bar (`display:none`), hidden Research Paper tab, engine start/stop buttons, backtest status endpoint -- all are dead code that bloats the file and confuses any developer reading it.
- **Solution**: Delete the HTML and JS for: engine bar, engine controls, engine endpoints, production config hidden bar, `page-paper` div (research paper is 1,100+ lines of HTML hidden via display:none). Keep the backend routes as stubs (they return harmless JSON).
- **Effort**: S (2-3 hours)
- **Files**: `templates/dashboard.html` (remove ~1,200 lines of hidden HTML + ~80 lines of JS)
- **Risk**: Low -- these elements are already hidden. Removing them cannot break visible behavior.
- **Acceptance criteria**: dashboard.html drops from 4,705 to ~3,400 lines. No visible change for visitors.

### P0-3. Mobile Header Responsiveness
- **Problem**: The header bar crams brand + regime pill + leverage + day + S&P 500 price + ES Futures + market timer + update timer + dark mode toggle into a single horizontal flex row. On mobile, this overflows and looks broken.
- **Solution**: Add responsive breakpoints: (a) Hide ES Futures, market timer, and regime pills on screens < 768px. (b) Stack S&P price below brand on mobile. (c) Keep dark mode toggle always visible.
- **Effort**: S (2-3 hours)
- **Files**: `templates/dashboard.html` (CSS media queries section)
- **Acceptance criteria**: Header is usable and doesn't overflow on a 375px screen (iPhone SE).

### P0-4. OG Meta Tags: Use Correct Metrics
- **Problem**: `<meta og:description>` shows "11.57% CAGR | 0.80 Sharpe | -29.62% MaxDD" which is correct, but there's a stale "No Leverage" claim and the OG image is missing.
- **Solution**: (a) Add an OG image (a screenshot or generated card). (b) Verify all meta descriptions use consistent numbers (some say -29.6%, some say -29.62%).
- **Effort**: S (1-2 hours)
- **Files**: `templates/dashboard.html` (head section)
- **Acceptance criteria**: Sharing the URL on LinkedIn/Twitter shows a branded preview card with accurate metrics.

### P1-1. Equity Curve Chart: Show on Dashboard
- **Problem**: The `/api/equity` and `/api/equity-comparison` endpoints exist and return full 26-year COMPASS vs SPY vs Net data, but the dashboard page does NOT render them. The only chart is the fund scatter plot. A finance visitor EXPECTS to see an equity curve.
- **Solution**: Add a Chart.js line chart below the performance banner showing COMPASS vs SPY (indexed to $100K) from 2000-2026. Include milestones (COVID crash, GFC, ATH) as annotations. Add time-range buttons (1Y, 5Y, 10Y, ALL).
- **Effort**: M (4-8 hours)
- **Files**: `templates/dashboard.html` (new chart section + JS fetch + Chart.js config)
- **Dependencies**: None -- API endpoints already exist.
- **Acceptance criteria**: 26-year equity curve renders within 2 seconds, with drawdown annotations and zoom capability. Milestones (GFC, COVID, ATH) are labeled.

### P1-2. Performance Banner: Add "Since Inception" Context
- **Problem**: The COMPASS vs SPY performance banner only shows the *live paper trading* period (a few weeks). A new visitor needs to know the backtest period performance prominently, not just the live period.
- **Solution**: Add a second row to the performance banner: "Backtest (2000-2026): COMPASS $100K -> $1.8M vs SPY $100K -> $720K". Or render this as a comparison bar below the existing live banner.
- **Effort**: S (2-3 hours)
- **Files**: `templates/dashboard.html` (perf-banner section)
- **Acceptance criteria**: Both live and backtest performance are visible without scrolling.

---

## 4. PHASE 2: MEDIUM EFFORT (1 week)

### P1-3. Split the Monolith: CSS -> External File
- **Problem**: 1,700+ lines of CSS inside `dashboard.html` makes the file impossible to maintain and increases page load (no caching of static CSS).
- **Solution**: Extract all CSS into `static/css/dashboard.css`. Link it from `<head>`. This enables browser caching and halves the HTML file size.
- **Effort**: M (4-6 hours)
- **Files**: Create `static/css/dashboard.css`, edit `templates/dashboard.html`
- **Risk**: Medium -- must verify all CSS specificity still works. Run through all pages/tabs.
- **Acceptance criteria**: dashboard.html is <2,500 lines. CSS is in its own cached file. Visual appearance is identical.

### P1-4. Split the Monolith: JS -> External File
- **Problem**: Same as CSS -- ~1,400 lines of JS inline, no caching, no minification possible.
- **Solution**: Extract all JS into `static/js/dashboard.js`. Add a content hash to the filename for cache busting (or use Flask's `url_for('static', ...)` with a version query param).
- **Effort**: M (4-6 hours)
- **Files**: Create `static/js/dashboard.js`, edit `templates/dashboard.html`
- **Dependencies**: Phase 2 P1-3 (extract CSS first)
- **Acceptance criteria**: dashboard.html is <1,200 lines (just HTML structure). All JS functionality works.

### P1-5. Drawdown Visualization
- **Problem**: Max Drawdown is shown as a single number (-29.6%) but there is no visual representation of drawdown periods, depth, or recovery time. Finance professionals care deeply about drawdown behavior.
- **Solution**: Add an "underwater chart" (drawdown from peak over time) below the equity curve. Use the same `/api/equity` data -- compute drawdown client-side. Color code by severity: green (0 to -10%), yellow (-10% to -20%), red (>-20%).
- **Effort**: M (6-10 hours)
- **Files**: `templates/dashboard.html` (or new `static/js/dashboard.js` if extracted)
- **Dependencies**: P1-1 (equity curve chart) -- can share the same data fetch.
- **Acceptance criteria**: Underwater chart renders aligned below equity curve. Recovery periods are visible. GFC and COVID drawdowns are labeled.

### P1-6. Annual Returns Bar Chart
- **Problem**: The research paper mentions "23/26 positive years" but there is no visual. Annual returns are the first thing an allocator looks at.
- **Solution**: Add a horizontal bar chart showing COMPASS annual returns vs SPY, year by year (2000-2025). Green bars for positive years, red for negative. SPY as transparent overlay bars.
- **Effort**: M (4-8 hours)
- **Files**: Backend: add `/api/annual-returns` endpoint. Frontend: new Chart.js bar chart.
- **Dependencies**: Requires backtest data (already loaded as `_equity_df`).
- **Acceptance criteria**: 26 bars (one per year) render. Excess return vs SPY is visible at a glance.

### P2-1. Static File Hosting / CDN Headers
- **Problem**: No `static/` directory exists yet. CSS/JS are inline. When extracted, they need proper cache headers.
- **Solution**: Create `static/css/`, `static/js/`, `static/img/`. Configure Flask's static route with appropriate cache headers. For Render free tier, the 1-year cache header for versioned assets is the standard approach.
- **Effort**: S (2-3 hours)
- **Dependencies**: P1-3 and P1-4 (monolith split).
- **Files**: `compass_dashboard_cloud.py` (add static config), directory creation.

### P2-2. SEO / Structured Data
- **Problem**: No JSON-LD structured data, no sitemap, no robots.txt. Google discovery is limited.
- **Solution**: Add JSON-LD `FinancialProduct` or `SoftwareApplication` schema. Add `/robots.txt` and `/sitemap.xml` routes. Ensure all page tabs are discoverable.
- **Effort**: S (3-4 hours)
- **Files**: `compass_dashboard_cloud.py` (new routes), `templates/dashboard.html` (JSON-LD in head).

---

## 5. PHASE 3: MAJOR FEATURES (2+ weeks)

### P2-3. Interactive Backtest Explorer
- **Problem**: The 53 experiments and their results are either hardcoded in the paper HTML or in the Experiment Analysis JS function. A visitor can't explore them interactively.
- **Solution**: Build an "Experiment Lab" tab where visitors can see each experiment's CAGR, MaxDD, Sharpe plotted on a scatter (like the fund comparison, but for experiments). Click an experiment to see its description, why it failed, and the parameter diff from baseline.
- **Effort**: L (16-24 hours)
- **Dependencies**: Needs experiment data either hardcoded as JSON or served from a new API endpoint.
- **Files**: New tab, new JS module, possibly new API route.
- **Acceptance criteria**: All 53 experiments are plotted. Baseline (v8.2) is marked. Approved/failed/partial color coding. Click-through to details.

### P2-4. PDF Export / Fact Sheet Generator
- **Problem**: A finance professional visiting may want a 1-page fact sheet to share with their team or save for reference. Currently, the only option is a screenshot.
- **Solution**: Add a "Download Fact Sheet" button that generates a 1-page PDF with: strategy name, key metrics, equity curve thumbnail, annual returns, risk disclosure, contact info. Use a server-side rendering approach (WeasyPrint or similar) or client-side (jsPDF).
- **Effort**: L (16-24 hours)
- **Dependencies**: Equity curve and annual returns must be implemented first (Phase 2).
- **Files**: New Python module for PDF generation, new API route.
- **Risk**: Medium -- PDF generation on Render free tier may be slow or memory-constrained.

### P3-1. Full Componentization (Jinja2 Templates / HTMX)
- **Problem**: The HTML is one enormous file. Even after CSS/JS extraction, the HTML body is ~1,200 lines of structural markup.
- **Solution**: Split into Jinja2 includes: `base.html`, `partials/hero.html`, `partials/positions.html`, `partials/scatter.html`, `partials/roadmap.html`, etc.
- **Effort**: XL (24-40 hours)
- **Risk**: High -- requires careful testing of all dynamic JS references.
- **Recommendation**: Defer. The monolith is ugly but functional. Componentization doesn't improve visitor experience, only developer experience.

### P3-2. Real-time WebSocket Updates
- **Problem**: Dashboard polls `/api/state` every 30 seconds. During market hours, a live trading system would benefit from sub-second updates.
- **Solution**: Flask-SocketIO or SSE (Server-Sent Events) for position updates and price ticks.
- **Effort**: XL (40+ hours)
- **Risk**: Render free tier may not support WebSocket connections reliably.
- **Recommendation**: Defer until the strategy is actually live-trading with real capital. Paper trading every 30s polling is fine.

---

## 6. DEPENDENCY GRAPH

```
P0-1 (Cold Start Fix)          -- no dependencies, do first
P0-2 (Remove Dead Code)        -- no dependencies, do in parallel
P0-3 (Mobile Header)           -- no dependencies, do in parallel
P0-4 (OG Meta Tags)            -- no dependencies, do in parallel
    |
P1-1 (Equity Curve Chart)      -- depends on nothing
P1-2 (Performance Banner)      -- depends on nothing
    |
P1-3 (Extract CSS)             -- depends on P0-2 (less code to extract)
    |
P1-4 (Extract JS)              -- depends on P1-3
    |
P1-5 (Drawdown Chart)          -- depends on P1-1 (shares data/layout)
P1-6 (Annual Returns)          -- depends on nothing
    |
P2-1 (Static File Hosting)     -- depends on P1-3 + P1-4
P2-2 (SEO)                     -- depends on P0-4
    |
P2-3 (Experiment Explorer)     -- depends on P1-4 (needs modular JS)
P2-4 (PDF Fact Sheet)          -- depends on P1-1, P1-6 (needs charts)
    |
P3-1 (Jinja2 Templates)        -- depends on P1-3 + P1-4
P3-2 (WebSocket)                -- depends on nothing, but deprioritized
```

---

## 7. MVP FOR "TRULY IMPRESSIVE TO A FINANCE PROFESSIONAL"

The absolute minimum set of improvements to make a finance professional say "this is serious" during a 2-minute visit:

### Must-Have (Phase 1 items):
1. **Equity curve chart** (P1-1) -- the #1 missing visual. No quant dashboard is taken seriously without one.
2. **Cold start fix** (P0-1) -- the dashboard must load instantly. Waiting 30s kills credibility.
3. **Backtest context in banner** (P1-2) -- the visitor needs to see 26-year track record immediately, not just the last 2 weeks of paper trading.

### Should-Have (Phase 2 items):
4. **Annual returns bar chart** (P1-6) -- allocators evaluate year-by-year consistency.
5. **Drawdown visualization** (P1-5) -- risk managers evaluate drawdown behavior.

### Already Working (preserve these):
6. Fund scatter plot (already present -- strongest element)
7. Landing hero with bias-corrected metrics (already present)
8. Live prices + market timer (already present)
9. Pre-close execution timeline (already present)
10. Trade analytics segmentation (already present)

### What This MVP Does NOT Need:
- PDF export (nice-to-have, not MVP)
- WebSocket real-time (polling is fine for showcase)
- Full componentization (developer comfort, not visitor impact)
- Interactive experiment explorer (the experiment analysis panel is already good enough)
- Mobile perfection (most finance professionals will view on desktop)

---

## 8. TIMELINE FOR A SOLO DEVELOPER

| Day | Tasks | Output |
|-----|-------|--------|
| Day 1 AM | P0-1 (cold start), P0-2 (remove dead code) | Cleaner codebase, instant hero load |
| Day 1 PM | P0-3 (mobile header), P0-4 (OG meta) | Mobile-usable header, shareable links |
| Day 2 | P1-1 (equity curve chart) | The single highest-impact addition |
| Day 3 AM | P1-2 (performance banner context) | Backtest numbers visible above the fold |
| Day 3 PM | P1-6 (annual returns bar chart) | Year-by-year performance visible |
| Day 4 | P1-3 (extract CSS) | dashboard.html shrinks to ~3,000 lines |
| Day 5 | P1-4 (extract JS) | dashboard.html shrinks to ~1,200 lines |
| Day 6 | P1-5 (drawdown chart) | Complete risk visualization |
| Day 7 | P2-1 (static hosting), P2-2 (SEO) | Performance + discoverability |

**Total: 7 working days to go from "impressive demo" to "institutional-grade showcase".**

The MVP subset (Days 1-3, items P0-1 through P1-2 + P1-1) can be deployed in 3 days.

---

## 9. RISKS & MITIGATIONS

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Render free tier cold start is unfixable | High | High | P0-1 mitigates by showing static content instantly; paid tier ($7/mo) eliminates the problem entirely |
| Chart.js performance with 26 years of daily data (~6,500 points) | Medium | Medium | Backend already downsamples to every 10th row (~650 points). This is fine for Chart.js. |
| CSS extraction breaks dark mode | Medium | Medium | Test both modes after extraction. Use `grep` to verify all CSS variable references. |
| yfinance rate limiting on Render | Low | Low | Already handled with 30s cache. Two workers share cache via `--preload`. |
| JS extraction breaks COMPANY_INFO or FUND_DATA constants | Low | High | These are defined in the `<script>` block -- must be extracted together. Verify with browser console after deployment. |
| Removing hidden Research Paper breaks SEO | Low | Medium | The paper is `display:none` so Google may not index it. But if it does, removing it loses SEO. Mitigation: move paper to its own URL route (`/research`) before deleting from dashboard.html. |

---

## 10. EXPLICIT SCOPE EXCLUSIONS

The following are OUT OF SCOPE for this plan:

- **Authentication / user accounts** -- not needed for a public showcase
- **Backend framework migration** (Flask -> FastAPI) -- no justification for a showcase dashboard
- **Database integration** -- CSV + JSON files are fine for this scale
- **CI/CD pipeline** -- git push auto-deploy on Render is sufficient
- **Automated testing** -- important in general, but the dashboard is read-only and the risk of a bug causing data loss is zero
- **Internationalization** -- English-only audience
- **Algorithm changes** -- algorithm is locked (v8.3)
- **Live trading integration** -- this is a showcase, not a trading terminal
