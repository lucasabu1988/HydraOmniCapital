/* ============ DARK MODE ============ */
function initDarkMode() {
    // v2 key — forces dark default for users who had old 'compass-dark-mode' saved
    var saved = localStorage.getItem('compass-theme-v2');
    var isDark = saved !== null ? saved === 'dark' : true;
    if (isDark) document.body.classList.add('dark');
    updateDarkToggleIcon(isDark);
}
function toggleDarkMode() {
    var isDark = document.body.classList.toggle('dark');
    localStorage.setItem('compass-theme-v2', isDark ? 'dark' : 'light');
    updateDarkToggleIcon(isDark);
    // Update chart colors if charts exist
    if (typeof updateChartColors === 'function') updateChartColors();
}
function updateDarkToggleIcon(isDark) {
    var btn = document.getElementById('dark-toggle');
    if (btn) btn.innerHTML = isDark ? '&#9788;' : '&#9790;';
}
initDarkMode();

/* ============ COMPANY INFO MAP (for ticker tooltips) ============ */
const COMPANY_INFO = {
    'TSLA': {name:'Tesla',sector:'Electric Vehicles',cap:'$1.1T',desc:'Electric vehicles, energy storage, and solar products manufacturer'},
    'MSFT': {name:'Microsoft',sector:'Software',cap:'$3.1T',desc:'Cloud computing (Azure), Windows OS, Office 365, and AI platforms'},
    'META': {name:'Meta Platforms',sector:'Social Media',cap:'$1.6T',desc:'Facebook, Instagram, WhatsApp, and metaverse/VR technologies'},
    'AMZN': {name:'Amazon',sector:'E-Commerce / Cloud',cap:'$2.3T',desc:'E-commerce marketplace, AWS cloud computing, and digital streaming'},
    'GOOGL': {name:'Alphabet',sector:'Internet / AI',cap:'$2.2T',desc:'Google Search, YouTube, Google Cloud, and Waymo autonomous vehicles'},
    'AVGO': {name:'Broadcom',sector:'Semiconductors',cap:'$1.0T',desc:'Semiconductor and infrastructure software for data centers and networking'},
    'UNH': {name:'UnitedHealth Group',sector:'Healthcare',cap:'$450B',desc:'Largest US health insurer with Optum health services division'},
    'ORCL': {name:'Oracle',sector:'Software / Cloud',cap:'$400B',desc:'Enterprise database software, cloud infrastructure, and business applications'},
    'MU':   {name:'Micron Technology',sector:'Semiconductors',cap:'$100B',desc:'Memory and storage semiconductors (DRAM, NAND flash) for data centers'},
    'LLY':  {name:'Eli Lilly',sector:'Pharmaceuticals',cap:'$700B',desc:'Pharmaceuticals specializing in diabetes (Mounjaro), obesity, and oncology'},
    'INTC': {name:'Intel',sector:'Semiconductors',cap:'$100B',desc:'Semiconductor design and manufacturing for PCs, data centers, and AI'},
    'JPM':  {name:'JPMorgan Chase',sector:'Banking',cap:'$680B',desc:'Largest US bank by assets with investment banking, trading, and wealth management'},
    'BRK-B':{name:'Berkshire Hathaway',sector:'Conglomerate',cap:'$1.0T',desc:'Diversified holding company led by Warren Buffett with insurance and investments'},
    'COST': {name:'Costco',sector:'Retail',cap:'$400B',desc:'Membership-only warehouse retail chain with bulk consumer goods'},
    'V':    {name:'Visa',sector:'Financial Services',cap:'$600B',desc:'Global digital payments network processing billions of transactions annually'},
    'CRM':  {name:'Salesforce',sector:'Software / CRM',cap:'$280B',desc:'Cloud-based CRM platform for sales, marketing, and customer service'},
    'WMT':  {name:'Walmart',sector:'Retail',cap:'$680B',desc:'Largest retailer globally with discount stores, grocery, and e-commerce'},
    'BAC':  {name:'Bank of America',sector:'Banking',cap:'$340B',desc:'Major US bank with consumer banking, wealth management, and trading'},
    'XOM':  {name:'Exxon Mobil',sector:'Energy',cap:'$480B',desc:'Largest US oil and gas company with upstream, downstream, and chemicals'},
    'BA':   {name:'Boeing',sector:'Aerospace',cap:'$140B',desc:'Commercial airplanes, defense systems, and space launch vehicles'},
    'GS':   {name:'Goldman Sachs',sector:'Investment Banking',cap:'$180B',desc:'Global investment banking, trading, asset management, and securities'},
    'MA':   {name:'Mastercard',sector:'Financial Services',cap:'$470B',desc:'Global payment processing network for credit, debit, and prepaid cards'},
    'NOW':  {name:'ServiceNow',sector:'Software / IT',cap:'$200B',desc:'Cloud platform for IT service management, workflows, and digital operations'},
    'MRVL': {name:'Marvell Technology',sector:'Semiconductors',cap:'$75B',desc:'Data infrastructure semiconductors for cloud, 5G, and enterprise networking'},
    'ADBE': {name:'Adobe',sector:'Software / Creative',cap:'$200B',desc:'Creative Cloud (Photoshop, Premiere), Document Cloud, and digital marketing'},
    'JNJ':  {name:'Johnson & Johnson',sector:'Healthcare',cap:'$370B',desc:'Pharmaceuticals and medical devices for immunology, oncology, and surgery'},
    'AMAT': {name:'Applied Materials',sector:'Semiconductors',cap:'$150B',desc:'Semiconductor manufacturing equipment for chip fabrication and display'},
    'QCOM': {name:'Qualcomm',sector:'Semiconductors',cap:'$190B',desc:'Mobile chipsets (Snapdragon), wireless technology patents, and 5G modems'},
    'HD':   {name:'Home Depot',sector:'Retail',cap:'$380B',desc:'Largest home improvement retailer in the US with DIY and pro segments'},
    'TXN':  {name:'Texas Instruments',sector:'Semiconductors',cap:'$185B',desc:'Analog and embedded processing semiconductors for industrial and auto'},
    'CVX':  {name:'Chevron',sector:'Energy',cap:'$280B',desc:'Integrated oil and gas company with global upstream and downstream operations'},
    'GE':   {name:'GE Aerospace',sector:'Aerospace',cap:'$220B',desc:'Aviation jet engines, power generation, and renewable energy systems'},
    'PG':   {name:'Procter & Gamble',sector:'Consumer Staples',cap:'$380B',desc:'Consumer goods giant with brands like Tide, Pampers, and Gillette'},
    'MRK':  {name:'Merck',sector:'Pharmaceuticals',cap:'$250B',desc:'Pharmaceuticals and vaccines including Keytruda (cancer) and Gardasil (HPV)'},
    'C':    {name:'Citigroup',sector:'Banking',cap:'$140B',desc:'Global banking institution with consumer banking, trading, and treasury services'},
    'IBM':  {name:'IBM',sector:'Technology / AI',cap:'$210B',desc:'Enterprise cloud, AI (Watson), consulting, and mainframe computing'},
    'WFC':  {name:'Wells Fargo',sector:'Banking',cap:'$240B',desc:'Major US bank focused on consumer and commercial banking with mortgage lending'},
    'ABBV': {name:'AbbVie',sector:'Pharmaceuticals',cap:'$310B',desc:'Biopharmaceuticals with Humira/Skyrizi (immunology) and Botox (aesthetics)'},
    'PFE':  {name:'Pfizer',sector:'Pharmaceuticals',cap:'$140B',desc:'Global pharmaceutical company with vaccines, oncology, and rare disease drugs'},
    'LRCX': {name:'Lam Research',sector:'Semiconductors',cap:'$100B',desc:'Semiconductor wafer fabrication equipment for etch, deposition, and clean'},
};

/* ============ GLOBALS ============ */
const REFRESH_MS = 30000;
let countdownSec = 30;
let currentPositions = {};
let lastSuccessTime = null;
/* Social feed state */
let sfMessages = [];
let sfActiveSource = 'all';
let sfActiveTicker = 'all';
let sfActiveView = 'timeline';
let sfSymbols = [];
/* ============ PAGE SWITCHING ============ */
function switchPage(page) {
    document.querySelectorAll('.page-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.page-tab').forEach(el => el.classList.remove('active'));
    const pageEl = document.getElementById('page-' + page);
    const tabEl = document.querySelector('.page-tab[data-page="' + page + '"]');
    if (pageEl) pageEl.classList.add('active');
    if (tabEl) tabEl.classList.add('active');
}

/* ============ HELPERS ============ */
function fmt$(v) {
    if (v == null || isNaN(v)) return '$--';
    const neg = v < 0;
    const abs = Math.abs(v);
    let s;
    if (abs >= 1e6) s = (abs/1e6).toFixed(2) + 'M';
    else s = abs.toLocaleString('en-US', {minimumFractionDigits:0, maximumFractionDigits:0});
    return (neg ? '-$' : '$') + s;
}

function fmtPct(v) {
    if (v == null || isNaN(v)) return '--';
    return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
}

function colorCls(v) {
    if (v > 0) return 'c-green';
    if (v < 0) return 'c-red';
    return 'c-dim';
}

function timeAgo(isoStr) {
    if (!isoStr) return '--';
    const d = new Date(isoStr);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return Math.floor(diff) + 's ago';
    if (diff < 3600) return Math.floor(diff/60) + 'm ago';
    if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
    return Math.floor(diff/86400) + 'd ago';
}

function escHtml(s) {
    if (!s) return '';
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* ============ UPDATE FUNCTIONS ============ */
function updateStatusBar(p) {
    const rt = document.getElementById('regime-tag');
    if (p.regime === 'RISK_ON') {
        rt.innerHTML = '<span class="hdr-pill-dot"></span> Risk On';
        rt.className = 'hdr-pill hdr-pill-on';
    } else {
        rt.innerHTML = '<span class="hdr-pill-dot"></span> Risk Off';
        rt.className = 'hdr-pill hdr-pill-off';
    }

    const lev = p.leverage != null ? p.leverage.toFixed(2) + 'x' : '1.00x';
    document.getElementById('leverage-display').textContent = lev;

    const pt = document.getElementById('protection-tag');
    if (p.in_protection) {
        const ddLev = p.dd_leverage != null ? ' (' + (p.dd_leverage * 100).toFixed(0) + '%)' : '';
        pt.textContent = '';
        const dot = document.createElement('span');
        dot.className = 'hdr-pill-dot';
        pt.appendChild(dot);
        pt.appendChild(document.createTextNode(' DD SCALING' + ddLev));
        pt.className = 'hdr-pill hdr-pill-prot';
    } else {
        pt.textContent = '';
        const dot = document.createElement('span');
        dot.className = 'hdr-pill-dot';
        pt.appendChild(dot);
        pt.appendChild(document.createTextNode(' NORMAL'));
        pt.className = 'hdr-pill hdr-pill-norm';
    }

    document.getElementById('day-display').textContent = p.trading_day;

    const ago = timeAgo(p.timestamp);
    document.getElementById('last-update').textContent = ago;

    const ts = p.timestamp ? new Date(p.timestamp).toLocaleString() : '--';
    document.getElementById('upd-tooltip').innerHTML =
        '\u00daltima actualizaci\u00f3n: ' + ts + '<br>Pr\u00f3xima en: ' + countdownSec + 's';
}

function updatePreclose(preclose) {
    if (!preclose) return;
    const dot = document.getElementById('preclose-dot');
    const label = document.getElementById('preclose-label');
    const timeEl = document.getElementById('preclose-time');
    const seg = document.getElementById('preclose-seg-window');

    timeEl.textContent = preclose.current_time_et + ' ET';

    switch (preclose.phase) {
        case 'waiting':
            dot.className = 'preclose-dot preclose-dot-waiting';
            label.textContent = 'ESPERANDO SE\u00d1AL 15:30';
            label.style.color = 'var(--text-tertiary)';
            seg.classList.remove('active');
            break;
        case 'window_open':
            dot.className = 'preclose-dot preclose-dot-window';
            label.textContent = 'VENTANA PRE-CIERRE ABIERTA';
            label.style.color = 'var(--yellow)';
            seg.classList.add('active');
            break;
        case 'entries_done':
            dot.className = 'preclose-dot preclose-dot-done';
            label.textContent = '\u00d3RDENES MOC ENVIADAS';
            label.style.color = 'var(--green)';
            seg.classList.add('active');
            break;
        default: /* market_closed */
            dot.className = 'preclose-dot preclose-dot-closed';
            label.textContent = 'MERCADO CERRADO';
            label.style.color = 'var(--text-muted)';
            seg.classList.remove('active');
    }
}

function updateCards(p) {
    const adjPortfolio = p.portfolio_value;
    const adjReturn = ((adjPortfolio - p.initial_capital) / p.initial_capital * 100);
    const total = document.getElementById('card-total');
    total.textContent = fmt$(adjPortfolio);
    total.className = 'metric-value ' + colorCls(adjReturn);
    document.getElementById('card-return').innerHTML =
        '<span class="' + colorCls(adjReturn) + '">' + fmtPct(adjReturn) + '</span> from $' + p.initial_capital.toLocaleString();

    /* Expected CAGR card — static production reference */
    /* Leverage info shown in sub when in protection */
    const cagrSub = document.getElementById('card-cagr-sub');
    if (p.in_protection) {
        const levNow = p.leverage != null ? p.leverage.toFixed(1) + 'x' : '1.0x';
        const ddLevPct = p.dd_leverage != null ? (p.dd_leverage * 100).toFixed(0) + '%' : '?';
        cagrSub.textContent = 'Lev: ' + levNow + ' (DD Scale ' + ddLevPct + ')';
    } else {
        cagrSub.textContent = 'Pre-close MOC + costs, no lev';
    }

    document.getElementById('card-cash').textContent = fmt$(p.cash);
    document.getElementById('card-invested').textContent = 'Invertido: ' + fmt$(p.invested);

    const dd = document.getElementById('card-drawdown');
    dd.textContent = fmtPct(p.drawdown);
    dd.className = 'metric-value ' + (p.drawdown > -5 ? 'c-green' : p.drawdown > -10 ? 'c-yellow' : 'c-red');
    document.getElementById('card-peak').textContent = 'M\u00e1ximo: ' + fmt$(p.peak_value);

    document.getElementById('card-positions').textContent = p.num_positions + ' / ' + p.max_positions;
    var regimeLabel = p.regime === 'RISK_ON' ? 'Risk On' : 'Risk Off';
    document.getElementById('card-maxpos').textContent = regimeLabel + (p.in_protection ? ' | DD Scaling' : '');
}

function updateRegimeBand(p) {
    var score = p.regime_score;
    var cons = p.regime_consecutive;

    var scoreEl = document.getElementById('rb-score');
    scoreEl.textContent = score != null ? score.toFixed(2) : '--';

    var consEl = document.getElementById('rb-consecutive');
    consEl.textContent = cons != null ? cons + ' d' : '--';

    var pct = score != null ? Math.min(Math.max(score * 100, 0), 100) : 0;

    var needle = document.getElementById('rb-needle');
    needle.style.left = pct + '%';

    var needleLabel = document.getElementById('rb-needle-label');
    needleLabel.textContent = score != null ? score.toFixed(2) : '--';

    var fill = document.getElementById('rb-fill');
    fill.style.width = pct + '%';
    if (score >= 0.65) {
        fill.style.background = 'linear-gradient(90deg, var(--red), var(--yellow), var(--green))';
        scoreEl.style.color = 'var(--green)';
        needleLabel.style.color = 'var(--green)';
    } else if (score >= 0.50) {
        fill.style.background = 'linear-gradient(90deg, var(--red), var(--yellow))';
        scoreEl.style.color = 'var(--yellow)';
        needleLabel.style.color = 'var(--yellow)';
    } else if (score >= 0.35) {
        fill.style.background = 'linear-gradient(90deg, var(--red), var(--yellow))';
        scoreEl.style.color = 'var(--yellow)';
        needleLabel.style.color = 'var(--yellow)';
    } else {
        fill.style.background = 'var(--red)';
        scoreEl.style.color = 'var(--red)';
        needleLabel.style.color = 'var(--red)';
    }

    var tag = document.getElementById('rb-tag');
    if (score >= 0.65) {
        tag.textContent = 'RISK ON (' + p.max_positions + ' pos)';
        tag.style.cssText = 'background:var(--green-dim);color:var(--green);border:1px solid rgba(34,197,94,0.3)';
    } else if (score >= 0.50) {
        tag.textContent = 'TRANSICI\u00d3N (' + p.max_positions + ' pos)';
        tag.style.cssText = 'background:var(--yellow-dim);color:var(--yellow);border:1px solid rgba(234,179,8,0.3)';
    } else if (score >= 0.35) {
        tag.textContent = 'CAUTELA (' + p.max_positions + ' pos)';
        tag.style.cssText = 'background:var(--yellow-dim);color:var(--yellow);border:1px solid rgba(234,179,8,0.3)';
    } else {
        tag.textContent = 'RISK OFF (' + p.max_positions + ' pos)';
        tag.style.cssText = 'background:var(--red-dim);color:var(--red);border:1px solid rgba(239,68,68,0.3)';
    }
}


function updatePerfBanner(p) {
    const adjPortfolio = p.portfolio_value;
    const adjReturn = ((adjPortfolio - p.initial_capital) / p.initial_capital * 100);
    const compassVal = document.getElementById('perf-compass-val');
    compassVal.textContent = fmtPct(adjReturn);
    compassVal.className = 'perf-side-value ' + colorCls(adjReturn);
    document.getElementById('perf-compass-sub').innerHTML =
        '$' + p.initial_capital.toLocaleString() + ' &rarr; ' + fmt$(adjPortfolio);

    /* SPY side */
    const spyVal = document.getElementById('perf-spy-val');
    if (p.spy_return != null) {
        spyVal.textContent = fmtPct(p.spy_return);
        spyVal.className = 'perf-side-value ' + colorCls(p.spy_return);
        const spyStart = p.initial_capital;
        const spyNow = spyStart * (1 + p.spy_return / 100);
        document.getElementById('perf-spy-sub').innerHTML =
            '$' + spyStart.toLocaleString() + ' &rarr; ' + fmt$(spyNow);
    } else {
        spyVal.textContent = '--';
        spyVal.className = 'perf-side-value';
    }

    /* VS center — difference expressed as outperformance */
    const alphaEl = document.getElementById('perf-alpha');
    const alphaLabel = document.getElementById('perf-alpha-label');
    if (p.spy_return != null) {
        const diff = adjReturn - p.spy_return;
        const absDiff = Math.abs(diff).toFixed(2);
        if (diff >= 0) {
            alphaEl.textContent = '+' + absDiff + ' pp';
            alphaEl.className = 'perf-vs-alpha c-green';
            alphaLabel.textContent = 'Superando SPY';
            alphaLabel.style.color = 'var(--green)';
        } else {
            alphaEl.textContent = '-' + absDiff + ' pp';
            alphaEl.className = 'perf-vs-alpha c-red';
            alphaLabel.textContent = 'Detr\u00e1s de SPY';
            alphaLabel.style.color = 'var(--red)';
        }
    } else {
        alphaEl.textContent = '--';
        alphaEl.className = 'perf-vs-alpha';
        alphaLabel.textContent = 'vs SPY';
        alphaLabel.style.color = '';
    }

    /* Period label */
    if (p.last_trading_date) {
        const days = p.trading_day || '?';
        document.getElementById('perf-period').textContent =
            'Test en vivo \u00B7 D\u00eda ' + days + ' \u00B7 Inicio Feb 19, 2026';
    }
}


function updatePositions(details) {
    const grid = document.getElementById('positions-grid');
    const totalBar = document.getElementById('positions-total-bar');
    currentPositions = {};

    if (!details || details.length === 0) {
        grid.innerHTML = '<div class="positions-empty"><div class="positions-empty-icon">&#9671;</div>SIN POSICIONES</div>';
        totalBar.style.display = 'none';
        document.getElementById('ph-invested').textContent = '$0';
        document.getElementById('ph-total-pnl').textContent = '$0';
        document.getElementById('ph-total-pnl').className = 'ph-stat-value c-dim';
        document.getElementById('ph-total-pct').textContent = '0.00%';
        document.getElementById('ph-total-pct').className = 'ph-stat-value c-dim';
        return;
    }

    let html = '';
    let totalValue = 0;
    let totalPnl = 0;
    let totalCost = 0;
    const holdDays = 5; /* COMPASS hold period */

    for (const p of details) {
        currentPositions[p.symbol] = true;

        totalValue += p.market_value || 0;
        totalPnl += p.pnl_dollar || 0;
        totalCost += (p.entry_price * p.shares) || 0;

        const isProfit = p.pnl_pct >= 0;
        const cardCls = p.near_stop ? 'pos-near-stop' : (isProfit ? 'pos-profit' : 'pos-loss');

        /* Return badge (total return since entry) */
        const retUp = (p.pnl_pct || 0) >= 0;
        const pnlBadgeCls = retUp ? 'pnl-up' : 'pnl-dn';

        /* Hold progress */
        const holdPct = Math.min(100, (p.days_held / holdDays) * 100);
        const holdFillCls = p.days_remaining === 0 ? 'hold-expired' : 'hold-active';
        const holdText = p.days_remaining === 0 ? 'EXP' : p.days_remaining + 'd left';

        /* Trailing stop */
        let trailHtml = '';
        if (p.trailing_active && p.trailing_stop_level) {
            trailHtml = '<div class="pos-stop-item">' +
                '<span class="pos-stop-dot" style="background:var(--cyan);"></span>' +
                '<span class="pos-stop-label">Trail</span>' +
                '<span class="pos-stop-val">$' + p.trailing_stop_level.toFixed(2) + '</span></div>';
        }

        /* Today's price change (vs previous regular close, not post-market) */
        const priceChange = p.prev_close ? (p.current_price - p.prev_close) : 0;
        const priceChangeSign = priceChange >= 0 ? '+' : '-';

        html += '<div class="pos-card ' + cardCls + '">' +
            /* Top: Symbol + Live Price + P&L badge */
            '<div class="pos-top">' +
                (function(){
                    const ci = COMPANY_INFO[p.symbol];
                    const safeSym = escHtml(p.symbol);
                    if (!ci) return '<span class="pos-symbol">' + safeSym + '</span>';
                    return '<span class="ticker-tip-wrap"><span class="pos-symbol">' + safeSym + '</span>' +
                        '<div class="ticker-tip">' +
                            '<div class="ticker-tip-name">' + ci.name + '</div>' +
                            '<span class="ticker-tip-sector">' + ci.sector + '</span>' +
                            '<div class="ticker-tip-cap">Market Cap: <b>' + ci.cap + '</b></div>' +
                            '<div class="ticker-tip-desc">' + ci.desc + '</div>' +
                        '</div></span>';
                })() +
                '<span style="font-size:15px; font-weight:700; color:var(--text-primary); font-family:var(--font-mono,monospace); margin-left:auto; margin-right:6px;">$' + p.current_price.toFixed(2) + '</span>' +
                '<span class="pos-pnl-badge ' + pnlBadgeCls + '">' + fmtPct(p.pnl_pct || 0) + '</span>' +
            '</div>' +
            /* Row 1: Value, P&L$, Shares */
            '<div class="pos-data-row">' +
                '<div class="pos-datum"><span class="pos-datum-label">Value</span><span class="pos-datum-value" style="color:var(--text-primary);">' + fmt$(p.market_value) + '</span></div>' +
                '<div class="pos-datum"><span class="pos-datum-label">P&amp;L</span><span class="pos-datum-value ' + colorCls(p.pnl_dollar) + '">' + fmt$(p.pnl_dollar) + '</span></div>' +
                '<div class="pos-datum"><span class="pos-datum-label">Shares</span><span class="pos-datum-value">' + p.shares.toFixed(1) + '</span></div>' +
            '</div>' +
            /* Row 2: Entry, Chg$, High */
            '<div class="pos-data-row">' +
                '<div class="pos-datum"><span class="pos-datum-label">Entry</span><span class="pos-datum-value">$' + p.entry_price.toFixed(2) + '</span></div>' +
                '<div class="pos-datum"><span class="pos-datum-label">Hoy</span><span class="pos-datum-value ' + colorCls(priceChange) + '">' + priceChangeSign + '$' + Math.abs(priceChange).toFixed(2) + '</span></div>' +
                '<div class="pos-datum"><span class="pos-datum-label">High</span><span class="pos-datum-value">$' + p.high_price.toFixed(2) + '</span></div>' +
            '</div>' +
            /* Hold progress bar */
            '<div class="pos-hold-bar-wrap">' +
                '<div class="pos-hold-bar"><div class="pos-hold-fill ' + holdFillCls + '" style="width:' + holdPct + '%"></div></div>' +
                '<span class="pos-hold-text">' + holdText + '</span>' +
            '</div>' +
            /* Stop levels */
            '<div class="pos-stops">' +
                '<div class="pos-stop-item">' +
                    '<span class="pos-stop-dot" style="background:var(--red);"></span>' +
                    '<span class="pos-stop-label">Stop' + (p.adaptive_stop_pct != null ? ' (' + p.adaptive_stop_pct.toFixed(0) + '%)' : '') + '</span>' +
                    '<span class="pos-stop-val">$' + p.position_stop_level.toFixed(2) + '</span>' +
                '</div>' +
                trailHtml +
                (p.sector ? '<div class="pos-stop-item"><span class="pos-stop-dot" style="background:var(--purple);"></span><span class="pos-stop-label">' + p.sector + '</span></div>' : '') +
                (p.near_stop ? '<span style="margin-left:auto; font-size:11px; font-weight:700; color:var(--yellow); letter-spacing:0.5px;">&#9888; CERCA DEL STOP</span>' : '') +
            '</div>' +
        '</div>';
    }

    /* Experiment history table — hidden (internal reference only) */

    /* Adaptive column count — eliminates empty grid cells */
    var n = details.length;
    var cols;
    if (n <= 0) cols = 4;
    else if (n <= 3) cols = n;
    else if (n === 4) cols = 4;
    else if (n === 5) cols = 5;
    else if (n === 6) cols = 3;
    else if (n === 7) cols = 4;
    else if (n === 8) cols = 4;
    else if (n === 9) cols = 3;
    else if (n === 10) cols = 5;
    else cols = 4;
    /* Cap columns for narrow viewports */
    var vw = window.innerWidth;
    if (vw <= 480) cols = Math.min(cols, 1);
    else if (vw <= 800) cols = Math.min(cols, 2);
    else if (vw <= 1100) cols = Math.min(cols, 3);
    grid.style.setProperty('--pos-cols', cols);

    grid.innerHTML = html;

    /* Staggered fade-in for position cards */
    grid.querySelectorAll('.pos-card').forEach(function(card, i) {
        card.style.opacity = '0';
        card.style.transform = 'translateY(4px)';
        setTimeout(function() {
            card.style.transition = 'opacity 0.2s ease, transform 0.2s ease';
            card.style.opacity = '1';
            card.style.transform = 'translateY(0)';
        }, i * 30);
    });

    /* --- Tooltip positioning (appended to body to escape overflow:hidden) --- */
    grid.querySelectorAll('.ticker-tip-wrap').forEach(function(wrap) {
        var tip = wrap.querySelector('.ticker-tip');
        if (!tip) return;
        document.body.appendChild(tip);
        wrap.addEventListener('mouseenter', function(e) {
            var rect = wrap.getBoundingClientRect();
            tip.style.display = 'block';
            tip.style.visibility = 'hidden';
            var tipW = 240;
            var tipH = tip.offsetHeight;
            tip.style.visibility = '';
            var left = rect.left;
            if (left + tipW > window.innerWidth - 12) left = window.innerWidth - tipW - 12;
            if (left < 12) left = 12;
            var top = rect.top - tipH - 8;
            if (top < 4) { top = rect.bottom + 8; tip.classList.add('tip-below'); }
            else { tip.classList.remove('tip-below'); }
            tip.style.left = left + 'px';
            tip.style.top = top + 'px';
            var arrowLeft = (rect.left + rect.width / 2) - left;
            arrowLeft = Math.max(14, Math.min(arrowLeft, tipW - 14));
            tip.style.setProperty('--arrow-left', arrowLeft + 'px');
        });
        wrap.addEventListener('mouseleave', function() { tip.style.display = 'none'; });
    });

    fetchExpAnalysis();

    /* Totals */
    const totalPnlPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0;
    const totCls = colorCls(totalPnlPct);

    /* Hero summary */
    document.getElementById('ph-invested').textContent = fmt$(totalValue);
    const pnlEl = document.getElementById('ph-total-pnl');
    pnlEl.textContent = fmt$(totalPnl);
    pnlEl.className = 'ph-stat-value ' + totCls;
    const pctEl = document.getElementById('ph-total-pct');
    pctEl.textContent = fmtPct(totalPnlPct);
    pctEl.className = 'ph-stat-value ' + totCls;

    /* Bottom bar */
    totalBar.style.display = 'flex';
    document.getElementById('pt-count').textContent = details.length + (details.length !== 1 ? ' Posiciones' : ' Posici\u00f3n');
    document.getElementById('pt-value').textContent = fmt$(totalValue);
    const ptPnl = document.getElementById('pt-pnl');
    ptPnl.textContent = fmt$(totalPnl);
    ptPnl.className = 'pt-stat-value ' + totCls;
    const ptPct = document.getElementById('pt-pct');
    ptPct.textContent = fmtPct(totalPnlPct);
    ptPct.className = 'pt-stat-value ' + totCls;
}


/* ============ HYDRA (Rattlesnake + Cash Recycling) ============ */
function updateHydra(hydra) {
    if (!hydra || !hydra.available) {
        var rHero = document.getElementById('rattle-positions-hero');
        if (rHero) rHero.style.display = 'none';
        var allocBand = document.getElementById('hydra-alloc-band');
        if (allocBand) allocBand.style.display = 'none';
        return;
    }

    /* Rattlesnake positions */
    var rHero = document.getElementById('rattle-positions-hero');
    var rGrid = document.getElementById('rattle-grid');
    if (rHero) rHero.style.display = 'block';

    var rPositions = hydra.rattle_positions || [];
    document.getElementById('rh-count').textContent = rPositions.length;

    var regimeEl = document.getElementById('rh-regime');
    regimeEl.textContent = hydra.rattle_regime || '--';
    regimeEl.style.color = hydra.rattle_regime === 'RISK_ON' ? 'var(--green)' : 'var(--red)';

    var vixEl = document.getElementById('rh-vix');
    if (hydra.vix_current != null) {
        vixEl.textContent = hydra.vix_current.toFixed(1);
        vixEl.style.color = hydra.vix_current > 35 ? 'var(--red)' : hydra.vix_current > 25 ? 'var(--yellow)' : 'var(--green)';
    } else {
        vixEl.textContent = '--';
    }

    if (rGrid) {
        if (rPositions.length === 0) {
            rGrid.textContent = '';
            var emptyDiv = document.createElement('div');
            emptyDiv.className = 'positions-empty';
            emptyDiv.style.gridColumn = '1 / -1';
            var iconDiv = document.createElement('div');
            iconDiv.className = 'positions-empty-icon';
            iconDiv.style.color = 'var(--yellow)';
            iconDiv.textContent = '\u25C6';
            emptyDiv.appendChild(iconDiv);
            var textNode = document.createTextNode('SIN POSICIONES RATTLESNAKE');
            emptyDiv.appendChild(textNode);
            var subDiv = document.createElement('div');
            subDiv.style.cssText = 'font-size:11px;color:var(--text-tertiary);margin-top:4px;';
            subDiv.textContent = 'Esperando ca\u00edda \u22658% + RSI<25 en S&P 100';
            emptyDiv.appendChild(subDiv);
            rGrid.appendChild(emptyDiv);
        } else {
            rGrid.textContent = '';
            for (var i = 0; i < rPositions.length; i++) {
                var rp = rPositions[i];
                var pnlPct = rp.pnl_pct || 0;
                var isUp = pnlPct >= 0;

                var card = document.createElement('div');
                card.className = 'pos-card ' + (isUp ? 'pos-profit' : 'pos-loss');
                card.style.borderTop = '2px solid var(--yellow)';

                /* Top row */
                var top = document.createElement('div');
                top.className = 'pos-top';
                var symSpan = document.createElement('span');
                symSpan.className = 'pos-symbol';
                symSpan.textContent = rp.symbol;
                top.appendChild(symSpan);
                var rTag = document.createElement('span');
                rTag.style.cssText = 'font-size:11px;color:var(--yellow);font-weight:600;margin-left:4px;';
                rTag.textContent = 'R';
                top.appendChild(rTag);
                var priceSpan = document.createElement('span');
                priceSpan.style.cssText = 'font-size:15px;font-weight:700;color:var(--text-primary);font-family:var(--font-mono,monospace);margin-left:auto;margin-right:6px;';
                priceSpan.textContent = '$' + (rp.current_price || 0).toFixed(2);
                top.appendChild(priceSpan);
                var badge = document.createElement('span');
                badge.className = 'pos-pnl-badge ' + (isUp ? 'pnl-up' : 'pnl-dn');
                badge.textContent = fmtPct(pnlPct);
                top.appendChild(badge);
                card.appendChild(top);

                /* Data row */
                var dataRow = document.createElement('div');
                dataRow.className = 'pos-data-row';
                var items = [
                    ['Entry', '$' + (rp.entry_price || 0).toFixed(2)],
                    ['Shares', String(rp.shares || 0)],
                    ['Days', (rp.days_held || 0) + '/8']
                ];
                for (var j = 0; j < items.length; j++) {
                    var datum = document.createElement('div');
                    datum.className = 'pos-datum';
                    var lbl = document.createElement('span');
                    lbl.className = 'pos-datum-label';
                    lbl.textContent = items[j][0];
                    datum.appendChild(lbl);
                    var val = document.createElement('span');
                    val.className = 'pos-datum-value';
                    val.textContent = items[j][1];
                    datum.appendChild(val);
                    dataRow.appendChild(datum);
                }
                card.appendChild(dataRow);

                /* Stops row */
                var stops = document.createElement('div');
                stops.className = 'pos-stops';
                var targetItem = document.createElement('div');
                targetItem.className = 'pos-stop-item';
                var tDot = document.createElement('span');
                tDot.className = 'pos-stop-dot';
                tDot.style.background = 'var(--green)';
                targetItem.appendChild(tDot);
                var tLbl = document.createElement('span');
                tLbl.className = 'pos-stop-label';
                tLbl.textContent = 'Target';
                targetItem.appendChild(tLbl);
                var tVal = document.createElement('span');
                tVal.className = 'pos-stop-val';
                tVal.textContent = '$' + ((rp.entry_price || 0) * 1.04).toFixed(2);
                targetItem.appendChild(tVal);
                stops.appendChild(targetItem);

                var stopItem = document.createElement('div');
                stopItem.className = 'pos-stop-item';
                var sDot = document.createElement('span');
                sDot.className = 'pos-stop-dot';
                sDot.style.background = 'var(--red)';
                stopItem.appendChild(sDot);
                var sLbl = document.createElement('span');
                sLbl.className = 'pos-stop-label';
                sLbl.textContent = 'Stop';
                stopItem.appendChild(sLbl);
                var sVal = document.createElement('span');
                sVal.className = 'pos-stop-val';
                sVal.textContent = '$' + ((rp.entry_price || 0) * 0.95).toFixed(2);
                stopItem.appendChild(sVal);
                stops.appendChild(stopItem);
                card.appendChild(stops);

                rGrid.appendChild(card);
            }
            rGrid.style.setProperty('--pos-cols', Math.min(rPositions.length, 5));
        }
    }

    /* Capital allocation bar */
    var cap = hydra.capital;
    var allocBand = document.getElementById('hydra-alloc-band');
    if (cap && allocBand) {
        allocBand.style.display = 'flex';
        var cPct = (cap.compass_pct || 0.5) * 100;
        var rPct = (cap.rattle_pct || 0.5) * 100;
        document.getElementById('hydra-bar-compass').style.width = cPct + '%';
        document.getElementById('hydra-bar-rattle').style.width = rPct + '%';
        document.getElementById('hydra-c-pct').textContent = cPct.toFixed(0) + '%';
        document.getElementById('hydra-r-pct').textContent = rPct.toFixed(0) + '%';
        document.getElementById('hydra-c-val').textContent = fmt$(cap.compass_account || 0);
        document.getElementById('hydra-r-val').textContent = fmt$(cap.rattle_account || 0);
        var recycled = cap.recycled_pct || 0;
        document.getElementById('hydra-recycled').textContent = (recycled * 100).toFixed(0) + '% recycled';
        var tag = document.getElementById('hydra-tag');
        if (recycled > 0) {
            tag.textContent = 'Recycling Active';
            tag.style.cssText = 'color:var(--cyan); background:var(--cyan-dim);';
        } else {
            tag.textContent = 'No Recycling';
            tag.style.cssText = 'color:var(--text-muted); background:var(--bg-tertiary);';
        }
    }
}


/* ============ UNIVERSE ============ */
function toggleUniverse() {
    const grid = document.getElementById('universe-grid');
    const arrow = document.getElementById('universe-arrow');
    if (grid.style.display === 'none') {
        grid.style.display = 'flex';
        arrow.innerHTML = '&#9660;';
    } else {
        grid.style.display = 'none';
        arrow.innerHTML = '&#9654;';
    }
}

function updateUniverse(universe, positions) {
    const grid = document.getElementById('universe-grid');
    const count = document.getElementById('universe-count');
    if (!universe || universe.length === 0) {
        count.textContent = '0';
        grid.innerHTML = '<span class="c-dim" style="font-size:12px;">No universe loaded</span>';
        return;
    }
    count.textContent = universe.length;
    let html = '';
    const held = positions || {};
    for (const sym of universe) {
        const isHeld = sym in held;
        const ci = COMPANY_INFO[sym];
        if (ci) {
            html += '<span class="ticker-tip-wrap"><span class="uni-badge' + (isHeld ? ' held' : '') + '">' + escHtml(sym) + '</span>' +
                '<div class="ticker-tip">' +
                    '<div class="ticker-tip-name">' + ci.name + '</div>' +
                    '<span class="ticker-tip-sector">' + ci.sector + '</span>' +
                    '<div class="ticker-tip-cap">Market Cap: <b>' + ci.cap + '</b></div>' +
                    '<div class="ticker-tip-desc">' + ci.desc + '</div>' +
                '</div></span>';
        } else {
            html += '<span class="uni-badge' + (isHeld ? ' held' : '') + '">' + escHtml(sym) + '</span>';
        }
    }
    grid.innerHTML = html;

    grid.querySelectorAll('.ticker-tip-wrap').forEach(function(wrap) {
        var tip = wrap.querySelector('.ticker-tip');
        if (!tip) return;
        document.body.appendChild(tip);
        wrap.addEventListener('mouseenter', function() {
            var rect = wrap.getBoundingClientRect();
            tip.style.display = 'block';
            tip.style.visibility = 'hidden';
            var tipW = 240;
            var tipH = tip.offsetHeight;
            tip.style.visibility = '';
            var left = rect.left;
            if (left + tipW > window.innerWidth - 12) left = window.innerWidth - tipW - 12;
            if (left < 12) left = 12;
            var top = rect.top - tipH - 8;
            if (top < 4) { top = rect.bottom + 8; tip.classList.add('tip-below'); }
            else { tip.classList.remove('tip-below'); }
            tip.style.left = left + 'px';
            tip.style.top = top + 'px';
            var arrowLeft = (rect.left + rect.width / 2) - left;
            arrowLeft = Math.max(14, Math.min(arrowLeft, tipW - 14));
            tip.style.setProperty('--arrow-left', arrowLeft + 'px');
        });
        wrap.addEventListener('mouseleave', function() { tip.style.display = 'none'; });
    });
}

/* ============ SOCIAL FEED ============ */
function sfTimeAgo(isoStr) {
    if (!isoStr) return '';
    try {
        const d = new Date(isoStr);
        const diff = (Date.now() - d.getTime()) / 1000;
        if (diff < 60) return 'now';
        if (diff < 3600) return Math.floor(diff / 60) + 'm';
        if (diff < 86400) return Math.floor(diff / 3600) + 'h';
        return Math.floor(diff / 86400) + 'd';
    } catch(e) { return ''; }
}

function highlightCashtags(text) {
    if (!text) return '';
    return escHtml(text).replace(/(\$[A-Z]{1,5})/g, '<span class="sf-cashtag">$1</span>')
                        .replace(/(#[A-Z]{1,5})/g, '<span class="sf-cashtag">$1</span>');
}

function sfDisplaySymbol(symbol) {
    if (!symbol || symbol === 'MKT') return 'Mercado';
    return '$' + escHtml(symbol);
}

function sfGetTierClass(source) {
    if (source === 'sec' || source === 'seekingalpha') return 'sf-msg-tier1';
    if (source === 'reddit') return 'sf-msg-tier3';
    return 'sf-msg-tier2';
}

function sfGetTierOrder(source) {
    var order = { sec: 1, seekingalpha: 2, news: 3, google: 4, marketwatch: 5, reddit: 6 };
    return order[source] || 7;
}

/* Note: innerHTML usage follows existing codebase pattern — all text is sanitized via escHtml() */
function sfRenderMessage(m) {
    var tierCls = sfGetTierClass(m.source);
    var timeStr = sfTimeAgo(m.time);
    var safeUrl = '';
    if (m.url) { try { var u = new URL(m.url); if (u.protocol === 'https:' || u.protocol === 'http:') safeUrl = m.url; } catch(e) {} }
    var bodyHtml = safeUrl ?
        '<a href="' + escHtml(safeUrl) + '" target="_blank" rel="noopener noreferrer">' + highlightCashtags(m.body) + '</a>' :
        highlightCashtags(m.body);
    var srcMap = {
        'reddit': ['sf-src-reddit', 'Reddit'],
        'news': ['sf-src-news', 'Yahoo Finance'],
        'seekingalpha': ['sf-src-seekingalpha', 'SeekingAlpha'],
        'sec': ['sf-src-sec', 'SEC'],
        'google': ['sf-src-google', 'Google News'],
        'marketwatch': ['sf-src-marketwatch', 'MarketWatch'],
    };
    var arr = srcMap[m.source] || ['sf-src-news', m.source || 'News'];
    var srcCls = arr[0], srcLabel = arr[1];
    var sentimentHtml = m.sentiment === 'bullish' ?
        '<span class="sf-sentiment sf-sentiment-bull">Alcista</span>' :
        m.sentiment === 'bearish' ?
        '<span class="sf-sentiment sf-sentiment-bear">Bajista</span>' : '';

    return '<div class="' + tierCls + '">' +
        '<div class="sf-msg-badge">' +
            '<span class="sf-ticker">' + sfDisplaySymbol(m.symbol) + '</span>' +
            sentimentHtml +
        '</div>' +
        '<div class="sf-msg-content">' +
            '<div class="sf-msg-text">' + bodyHtml + '</div>' +
            '<div class="sf-msg-meta">' +
                '<span class="sf-source ' + srcCls + '">' + srcLabel + '</span>' +
                '<span class="sf-msg-user">' + escHtml(m.user) + '</span>' +
                (timeStr ? '<span class="sf-msg-time">' + timeStr + '</span>' : '') +
            '</div>' +
        '</div>' +
    '</div>';
}

function sfApplyFilters() {
    return sfMessages.filter(function(m) {
        if (sfActiveSource !== 'all' && m.source !== sfActiveSource) return false;
        if (sfActiveTicker !== 'all' && m.symbol !== sfActiveTicker) return false;
        return true;
    });
}

function sfUpdateStats(filtered) {
    var bull = 0, bear = 0, neutral = 0;
    var tickerCounts = {};
    var newestTime = null;
    for (var i = 0; i < filtered.length; i++) {
        var m = filtered[i];
        if (m.sentiment === 'bullish') bull++;
        else if (m.sentiment === 'bearish') bear++;
        else neutral++;
        var sym = m.symbol || 'MKT';
        tickerCounts[sym] = (tickerCounts[sym] || 0) + 1;
        if (m.time) { try { var t = new Date(m.time); if (!newestTime || t > newestTime) newestTime = t; } catch(e) {} }
    }
    var el;
    el = document.getElementById('sf-stat-total'); if (el) el.textContent = filtered.length;
    el = document.getElementById('sf-stat-bull'); if (el) el.textContent = bull;
    el = document.getElementById('sf-stat-bear'); if (el) el.textContent = bear;
    el = document.getElementById('sf-stat-neutral'); if (el) el.textContent = neutral;
    var topTicker = '--', topCount = 0;
    for (var sym in tickerCounts) { if (tickerCounts[sym] > topCount) { topCount = tickerCounts[sym]; topTicker = sym; } }
    el = document.getElementById('sf-stat-top-ticker');
    if (el) el.textContent = (topTicker === 'MKT' ? 'Mercado' : '$' + topTicker) + ' (' + topCount + ')';
    el = document.getElementById('sf-stat-freshness');
    if (el) el.textContent = newestTime ? (sfTimeAgo(newestTime.toISOString()) || 'ahora') : '--';
}

function sfRenderTimeline(filtered) {
    var tier1 = [], tier2 = [], tier3 = [];
    for (var i = 0; i < filtered.length; i++) {
        var m = filtered[i];
        if (m.source === 'sec' || m.source === 'seekingalpha') tier1.push(m);
        else if (m.source === 'reddit') tier3.push(m);
        else tier2.push(m);
    }
    var html = '';
    if (tier1.length > 0) {
        html += '<div class="sf-tier-section"><div class="sf-tier-header"><span class="sf-tier-label">An\u00e1lisis &amp; Regulatorio</span><span class="sf-tier-line"></span><span class="sf-tier-count">' + tier1.length + '</span></div>';
        for (var i = 0; i < tier1.length; i++) html += sfRenderMessage(tier1[i]);
        html += '</div>';
    }
    if (tier2.length > 0) {
        html += '<div class="sf-tier-section"><div class="sf-tier-header"><span class="sf-tier-label">Noticias</span><span class="sf-tier-line"></span><span class="sf-tier-count">' + tier2.length + '</span></div>';
        for (var i = 0; i < tier2.length; i++) html += sfRenderMessage(tier2[i]);
        html += '</div>';
    }
    if (tier3.length > 0) {
        html += '<div class="sf-tier-section"><div class="sf-tier-header"><span class="sf-tier-label">Comunidad</span><span class="sf-tier-line"></span><span class="sf-tier-count">' + tier3.length + '</span></div>';
        for (var i = 0; i < tier3.length; i++) html += sfRenderMessage(tier3[i]);
        html += '</div>';
    }
    return html;
}

function sfRenderGrouped(filtered) {
    var groups = {}, order = [];
    for (var i = 0; i < filtered.length; i++) {
        var m = filtered[i], sym = m.symbol || 'MKT';
        if (!groups[sym]) { groups[sym] = []; order.push(sym); }
        groups[sym].push(m);
    }
    order.sort(function(a, b) { if (a === 'MKT') return 1; if (b === 'MKT') return -1; return a.localeCompare(b); });
    var html = '<div class="sf-grouped-container">';
    for (var g = 0; g < order.length; g++) {
        var sym = order[g], msgs = groups[sym];
        var bull = 0, bear = 0;
        for (var i = 0; i < msgs.length; i++) { if (msgs[i].sentiment === 'bullish') bull++; else if (msgs[i].sentiment === 'bearish') bear++; }
        msgs.sort(function(a, b) { var d = sfGetTierOrder(a.source) - sfGetTierOrder(b.source); return d !== 0 ? d : (b.time || '').localeCompare(a.time || ''); });
        var displaySym = sym === 'MKT' ? 'Mercado' : '$' + escHtml(sym);
        html += '<div class="sf-ticker-group"><div class="sf-ticker-group-header">' +
            '<span class="sf-ticker-group-symbol">' + displaySym + '</span>' +
            '<span class="sf-ticker-group-count">' + msgs.length + ' publicaciones</span>' +
            '<div class="sf-ticker-group-sentiment">' +
            (bull > 0 ? '<span class="sf-sentiment sf-sentiment-bull">' + bull + ' alcista</span>' : '') +
            (bear > 0 ? '<span class="sf-sentiment sf-sentiment-bear">' + bear + ' bajista</span>' : '') +
            '</div></div><div class="sf-ticker-group-body">';
        for (var i = 0; i < msgs.length; i++) html += sfRenderMessage(msgs[i]);
        html += '</div></div>';
    }
    html += '</div>';
    return html;
}

function sfRender() {
    var panel = document.getElementById('sf-body');
    var skeleton = document.getElementById('sf-skeleton');
    if (!panel) return;
    if (skeleton) skeleton.style.display = 'none';
    var filtered = sfApplyFilters();
    sfUpdateStats(filtered);
    if (filtered.length === 0) {
        panel.textContent = '';
        var noRes = document.createElement('div');
        noRes.className = 'sf-no-results';
        noRes.textContent = '';
        var icon = document.createElement('div');
        icon.className = 'sf-no-results-icon';
        icon.textContent = '\uD83D\uDD0D';
        var txt = document.createElement('div');
        txt.className = 'sf-no-results-text';
        txt.textContent = 'No hay publicaciones para estos filtros';
        noRes.appendChild(icon);
        noRes.appendChild(txt);
        panel.appendChild(noRes);
        return;
    }
    /* Using innerHTML for performance with large feed lists - all text sanitized via escHtml() */
    panel.innerHTML = sfActiveView === 'grouped' ? sfRenderGrouped(filtered) : sfRenderTimeline(filtered);
}

function sfBuildTickerPills() {
    var container = document.getElementById('sf-ticker-filters');
    if (!container) return;
    var existing = container.querySelectorAll('.sf-pill[data-ticker]:not([data-ticker="all"])');
    for (var i = 0; i < existing.length; i++) existing[i].remove();
    var seen = {}, syms = [];
    for (var i = 0; i < sfMessages.length; i++) {
        var s = sfMessages[i].symbol || 'MKT';
        if (!seen[s]) { seen[s] = true; syms.push(s); }
    }
    syms.sort(function(a, b) { if (a === 'MKT') return 1; if (b === 'MKT') return -1; return a.localeCompare(b); });
    for (var i = 0; i < syms.length; i++) {
        var btn = document.createElement('button');
        btn.className = 'sf-pill';
        btn.setAttribute('data-ticker', syms[i]);
        btn.textContent = syms[i] === 'MKT' ? 'Mercado' : '$' + syms[i];
        container.appendChild(btn);
    }
}

function sfInitFilters() {
    var srcC = document.getElementById('sf-source-filters');
    if (srcC) srcC.addEventListener('click', function(e) {
        var pill = e.target.closest('.sf-pill'); if (!pill) return;
        srcC.querySelectorAll('.sf-pill').forEach(function(p) { p.classList.remove('sf-pill-active'); });
        pill.classList.add('sf-pill-active');
        sfActiveSource = pill.getAttribute('data-source');
        sfRender();
    });
    var tickC = document.getElementById('sf-ticker-filters');
    if (tickC) tickC.addEventListener('click', function(e) {
        var pill = e.target.closest('.sf-pill'); if (!pill) return;
        tickC.querySelectorAll('.sf-pill').forEach(function(p) { p.classList.remove('sf-pill-active'); });
        pill.classList.add('sf-pill-active');
        sfActiveTicker = pill.getAttribute('data-ticker');
        sfRender();
    });
    var viewC = document.getElementById('sf-view-toggle');
    if (viewC) viewC.addEventListener('click', function(e) {
        var pill = e.target.closest('.sf-pill'); if (!pill) return;
        viewC.querySelectorAll('.sf-pill').forEach(function(p) { p.classList.remove('sf-pill-active'); });
        pill.classList.add('sf-pill-active');
        sfActiveView = pill.getAttribute('data-view');
        sfRender();
    });
}

function updateSocialFeed(data) {
    var messages = data.messages || data;
    if (!messages || messages.length === 0) {
        var skeleton = document.getElementById('sf-skeleton');
        if (skeleton) skeleton.style.display = 'block';
        var countEl = document.getElementById('sf-count');
        if (countEl) countEl.textContent = '';
        return;
    }
    sfMessages = messages;
    sfSymbols = data.symbols || sfSymbols;
    var countEl = document.getElementById('sf-count');
    if (countEl) countEl.textContent = messages.length + ' publicaciones';
    sfBuildTickerPills();
    sfRender();
}

async function fetchSocialFeed() {
    try {
        var res = await fetch('/api/social-feed');
        var data = await res.json();
        updateSocialFeed(data);
    } catch(e) { console.error('Social feed error:', e); }
}





/* ============ CYCLE LOG ============ */
async function fetchCycleLog() {
    try {
        const res = await fetch('/api/cycle-log');
        const cycles = await res.json();
        const tbody = document.getElementById('cycle-log-body');
        if (!tbody || !cycles.length) {
            if (tbody) tbody.innerHTML = '<tr><td colspan="7" style="color:var(--text-muted);text-align:center;">No hay ciclos completados a\u00fan</td></tr>';
            return;
        }
        let html = '';
        for (const c of cycles) {
            const isActive = c.status === 'active';
            const compass = c.compass_return != null ? (c.compass_return >= 0 ? '+' : '') + c.compass_return.toFixed(2) + '%' : '--';
            const spy = c.spy_return != null ? (c.spy_return >= 0 ? '+' : '') + c.spy_return.toFixed(2) + '%' : '--';
            const alpha = c.alpha != null ? (c.alpha >= 0 ? '+' : '') + c.alpha.toFixed(2) + ' pp' : '--';
            const compassCls = c.compass_return > 0 ? 'cl-pos' : c.compass_return < 0 ? 'cl-neg' : '';
            const spyCls = c.spy_return > 0 ? 'cl-pos' : c.spy_return < 0 ? 'cl-neg' : '';
            const alphaCls = c.alpha > 0 ? 'cl-pos' : c.alpha < 0 ? 'cl-neg' : '';
            const period = c.end_date ? c.start_date + ' → ' + c.end_date : c.start_date + ' → ...';
            // Build tickers display — use positions_current for active cycles
            var tickers = '--';
            var displayPositions = (isActive && c.positions_current) ? c.positions_current : c.positions;
            if (displayPositions) {
                var stops = c.stop_events || [];
                var stoppedTickers = [];
                for (var si = 0; si < stops.length; si++) {
                    stoppedTickers.push(stops[si].stopped);
                    if (stops[si].replacement) stoppedTickers.push(stops[si].replacement + '(repl)');
                }
                var parts = [];
                for (var ti = 0; ti < displayPositions.length; ti++) {
                    parts.push(displayPositions[ti]);
                }
                // Show stopped tickers as strikethrough prefix
                var stoppedParts = [];
                for (var si = 0; si < stops.length; si++) {
                    var s = stops[si];
                    var label = '<s style="opacity:.5">' + s.stopped + '</s>';
                    if (s.replacement) label += '→<s style="opacity:.5">' + s.replacement + '</s>';
                    stoppedParts.push(label);
                }
                if (stoppedParts.length > 0) {
                    tickers = stoppedParts.join(', ') + ' · ' + parts.join(', ');
                } else {
                    tickers = parts.join(', ');
                }
            }
            const status = isActive
                ? '<span class="cl-active">● ACTIVE</span>'
                : (c.alpha != null && c.alpha >= 0 ? '<span class="cl-pos">✓ WIN</span>' : '<span class="cl-neg">✗ LOSS</span>');
            html += '<tr>' +
                '<td>#' + c.cycle + '</td>' +
                '<td>' + period + '</td>' +
                '<td class="cl-tickers">' + tickers + '</td>' +
                '<td class="cl-num ' + compassCls + '">' + compass + '</td>' +
                '<td class="cl-num ' + spyCls + '">' + spy + '</td>' +
                '<td class="cl-num ' + alphaCls + '">' + alpha + '</td>' +
                '<td>' + status + '</td>' +
                '</tr>';
        }
        tbody.innerHTML = html;
    } catch (e) {
        console.error('Cycle log error:', e);
    }
}

/* ============ FETCH & REFRESH ============ */
let _fetchRetries = 0;
const MAX_RETRIES = 5;
const RETRY_DELAYS = [3000, 5000, 8000, 12000, 20000];

/* SPY & Futures live price tracker */
function _applyPriceChg(priceEl, chgEl, currentPrice, prevClose) {
    priceEl.textContent = '$' + currentPrice.toFixed(2);
    if (!prevClose || prevClose <= 0) {
        chgEl.textContent = '--';
        chgEl.style.color = 'var(--text-secondary)';
        return;
    }
    var chg = ((currentPrice - prevClose) / prevClose) * 100;
    if (Math.abs(chg) < 0.001) {
        chgEl.textContent = '0.00%';
        chgEl.style.color = 'var(--text-secondary)';
    } else if (chg > 0) {
        chgEl.textContent = '+' + chg.toFixed(2) + '%';
        chgEl.style.color = 'var(--green)';
    } else {
        chgEl.textContent = chg.toFixed(2) + '%';
        chgEl.style.color = 'var(--red)';
    }
}
function updateSpyTracker(prices, prevCloses) {
    var pc = prevCloses || {};
    /* --- S&P 500 Index --- */
    var priceEl = document.getElementById('hdr-spy-price');
    var chgEl = document.getElementById('hdr-spy-chg');
    var idxPrice = prices['^GSPC'] || prices['GSPC'];
    if (priceEl && chgEl && idxPrice) {
        _applyPriceChg(priceEl, chgEl, idxPrice, pc['^GSPC'] || pc['GSPC']);
    }
    /* --- ES Futures --- */
    var fPriceEl = document.getElementById('hdr-futures-price');
    var fChgEl = document.getElementById('hdr-futures-chg');
    var esPrice = prices['ES=F'];
    if (fPriceEl && fChgEl && esPrice) {
        _applyPriceChg(fPriceEl, fChgEl, esPrice, pc['ES=F']);
    }
    /* --- NQ Futures --- */
    var nqPriceEl = document.getElementById('hdr-nq-price');
    var nqChgEl = document.getElementById('hdr-nq-chg');
    var nqPrice = prices['NQ=F'];
    if (nqPriceEl && nqChgEl && nqPrice) {
        _applyPriceChg(nqPriceEl, nqChgEl, nqPrice, pc['NQ=F']);
    }
    /* --- 10Y Treasury Yield (^TNX returns value * 10, e.g. 42.5 = 4.25%) --- */
    var tnxPriceEl = document.getElementById('hdr-tnx-price');
    var tnxChgEl = document.getElementById('hdr-tnx-chg');
    var tnxRaw = prices['^TNX'] || prices['TNX'];
    if (tnxPriceEl && tnxChgEl && tnxRaw) {
        tnxPriceEl.textContent = (tnxRaw / 10).toFixed(2) + '%';
        var tnxPrev = pc['^TNX'] || pc['TNX'];
        if (tnxPrev && tnxPrev > 0) {
            var tnxChg = ((tnxRaw - tnxPrev) / tnxPrev) * 100;
            if (Math.abs(tnxChg) < 0.001) {
                tnxChgEl.textContent = '0.00%';
                tnxChgEl.style.color = 'var(--text-secondary)';
            } else if (tnxChg > 0) {
                tnxChgEl.textContent = '+' + tnxChg.toFixed(2) + '%';
                tnxChgEl.style.color = 'var(--red)';
            } else {
                tnxChgEl.textContent = tnxChg.toFixed(2) + '%';
                tnxChgEl.style.color = 'var(--green)';
            }
        } else {
            tnxChgEl.textContent = '--';
            tnxChgEl.style.color = 'var(--text-secondary)';
        }
    }
    /* --- DXY Dollar Index --- */
    var dxyPriceEl = document.getElementById('hdr-dxy-price');
    var dxyChgEl = document.getElementById('hdr-dxy-chg');
    var dxyPrice = prices['DX-Y.NYB'] || prices['DX=F'];
    if (dxyPriceEl && dxyChgEl && dxyPrice) {
        dxyPriceEl.textContent = dxyPrice.toFixed(2);
        var dxyPrev = pc['DX-Y.NYB'] || pc['DX=F'];
        if (dxyPrev && dxyPrev > 0) {
            var dxyChg = ((dxyPrice - dxyPrev) / dxyPrev) * 100;
            if (Math.abs(dxyChg) < 0.001) {
                dxyChgEl.textContent = '0.00%';
                dxyChgEl.style.color = 'var(--text-secondary)';
            } else if (dxyChg > 0) {
                dxyChgEl.textContent = '+' + dxyChg.toFixed(2) + '%';
                dxyChgEl.style.color = 'var(--green)';
            } else {
                dxyChgEl.textContent = dxyChg.toFixed(2) + '%';
                dxyChgEl.style.color = 'var(--red)';
            }
        } else {
            dxyChgEl.textContent = '--';
            dxyChgEl.style.color = 'var(--text-secondary)';
        }
    }
}

async function fetchAll() {
    try {
        const stateRes = await fetch('/api/state');
        const stateData = await stateRes.json();

        if (stateData.status === 'offline') {
            const banner = document.getElementById('offline-banner');
            banner.style.display = 'block';
            banner.textContent = _fetchRetries > 0
                ? 'DESPERTANDO SERVIDOR... INTENTO ' + _fetchRetries + '/' + MAX_RETRIES
                : 'CONECTANDO AL SERVIDOR...';
            if (_fetchRetries < MAX_RETRIES) {
                setTimeout(fetchAll, RETRY_DELAYS[_fetchRetries]);
                _fetchRetries++;
            }
        } else {
            _fetchRetries = 0;
            document.getElementById('offline-banner').style.display = 'none';
            lastSuccessTime = new Date().toISOString();
            const p = stateData.portfolio;
            updateStatusBar(p);
            updateCards(p);
            updateRegimeBand(p);
            updatePerfBanner(p);
            updatePreclose(stateData.preclose);
            updatePositions(stateData.position_details);
            if (stateData.hydra) updateHydra(stateData.hydra);
            if (stateData.prices) updateSpyTracker(stateData.prices, stateData.prev_closes);
            const posDict = {};
            if (stateData.position_details) {
                for (const pd of stateData.position_details) posDict[pd.symbol] = true;
            }
            updateUniverse(stateData.universe, posDict);

            // Overlay status
            fetch('/api/overlay-status')
                .then(r => r.json())
                .then(d => {
                    if (!d.available) {
                        document.getElementById('ov-scalar').textContent = 'OFF';
                        document.getElementById('ov-tag').textContent = 'Unavailable';
                        document.getElementById('ov-tag').className = 'regime-band-tag';
                        return;
                    }
                    const scalar = d.capital_scalar;
                    document.getElementById('ov-scalar').textContent = scalar.toFixed(2);

                    const tag = document.getElementById('ov-tag');
                    tag.textContent = d.scalar_label;
                    tag.className = 'regime-band-tag';
                    if (d.scalar_color === 'green') tag.style.cssText = 'color:var(--green); background:var(--green-dim);';
                    else if (d.scalar_color === 'yellow') tag.style.cssText = 'color:var(--yellow); background:var(--yellow-dim);';
                    else tag.style.cssText = 'color:var(--red); background:var(--red-dim);';

                    const colorVal = v => v >= 0.90 ? 'var(--green)' : v >= 0.60 ? 'var(--yellow)' : 'var(--red)';
                    const bso = d.per_overlay.bso;
                    const m2 = d.per_overlay.m2;
                    const fomc = d.per_overlay.fomc;

                    const bsoEl = document.getElementById('ov-bso');
                    bsoEl.textContent = bso.toFixed(2);
                    bsoEl.style.color = colorVal(bso);

                    const m2El = document.getElementById('ov-m2');
                    m2El.textContent = m2.toFixed(2);
                    m2El.style.color = colorVal(m2);

                    const fomcEl = document.getElementById('ov-fomc');
                    fomcEl.textContent = fomc.toFixed(2);
                    fomcEl.style.color = colorVal(fomc);

                    const fedEl = document.getElementById('ov-fed');
                    fedEl.textContent = d.fed_emergency_active ? 'ACTIVE' : 'Inactive';
                    fedEl.style.color = d.fed_emergency_active ? 'var(--red)' : 'var(--text-muted)';

                    const creditEl = document.getElementById('ov-credit');
                    const excluded = d.credit_filter.excluded_sectors;
                    if (excluded && excluded.length > 0) {
                        creditEl.textContent = excluded.join(', ');
                        creditEl.style.color = 'var(--red)';
                    } else {
                        creditEl.textContent = 'Clear';
                        creditEl.style.color = 'var(--green)';
                    }
                })
                .catch(() => {});
        }
    } catch (err) {
        console.error('Fetch error:', err);
        const banner = document.getElementById('offline-banner');
        banner.style.display = 'block';
        banner.innerHTML = _fetchRetries > 0
            ? 'DESPERTANDO SERVIDOR... INTENTO ' + _fetchRetries + '/' + MAX_RETRIES
            : 'CONECTANDO AL SERVIDOR...';
        if (_fetchRetries < MAX_RETRIES) {
            setTimeout(fetchAll, RETRY_DELAYS[_fetchRetries]);
            _fetchRetries++;
        }
    }
}

/* (Monte Carlo removed — replaced by Fund Scatter Plot on dashboard) */


/* ============ TRADE ANALYTICS ============ */
let taData = null;
let taActiveSeg = 'exit_reason';

const TA_SEGMENTS = [
    { key: 'exit_reason', label: 'Exit Reason' },
    { key: 'regime', label: 'Regime' },
    { key: 'sector', label: 'Sector' },
    { key: 'year', label: 'Year' },
    { key: 'dow', label: 'Day of Week' },
    { key: 'vol_environment', label: 'Volatility' },
];

async function fetchTradeAnalytics() {
    try {
        const res = await fetch('/api/trade-analytics');
        const data = await res.json();
        if (data.error) {
            document.getElementById('ta-table-container').innerHTML =
                '<div style="color:var(--red);font-size:12px;">Error: ' + data.error + '</div>';
            return;
        }
        taData = data;
        document.getElementById('ta-badge').textContent =
            (data.overall ? data.overall.total_trades.toLocaleString() + ' trades' : '--');
        renderTAButtons();
        renderTATable(taActiveSeg);
    } catch(e) {
        console.error('TA error:', e);
        document.getElementById('ta-table-container').innerHTML =
            '<div style="color:var(--red);font-size:12px;">Failed to load: ' + e.message + '</div>';
    }
}

function renderTAButtons() {
    const box = document.getElementById('ta-segments');
    box.innerHTML = TA_SEGMENTS.map(s =>
        `<button class="ta-seg-btn ${s.key===taActiveSeg?'active':''}" data-seg="${s.key}">${s.label}</button>`
    ).join('');
    box.querySelectorAll('.ta-seg-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            taActiveSeg = this.dataset.seg;
            box.querySelectorAll('.ta-seg-btn').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            renderTATable(taActiveSeg);
        });
    });
}

function renderTATable(segKey) {
    const box = document.getElementById('ta-table-container');
    if (!taData || !taData.segments || !taData.segments[segKey]) {
        box.innerHTML = '<div style="color:var(--text-tertiary);font-size:12px;">No data</div>';
        return;
    }
    const seg = taData.segments[segKey];
    const entries = Object.entries(seg).sort((a,b) => b[1].alpha_contribution_pct - a[1].alpha_contribution_pct);

    let html = '<table class="analytics-table"><thead><tr>';
    html += '<th>Category</th><th class="num">Trades</th><th class="num">Win%</th>';
    html += '<th class="num">Avg Return</th><th class="num">Avg PnL</th>';
    html += '<th class="num">Alpha %</th><th class="num">Sharpe</th>';
    html += '</tr></thead><tbody>';

    for (const [cat, s] of entries) {
        const retColor = s.avg_return_pct >= 0 ? 'var(--green)' : 'var(--red)';
        const pnlColor = s.avg_pnl >= 0 ? 'var(--green)' : 'var(--red)';
        const alphaColor = s.alpha_contribution_pct >= 0 ? 'var(--green)' : 'var(--red)';
        html += `<tr>`;
        html += `<td style="color:var(--text-primary);font-weight:500;">${cat}</td>`;
        html += `<td class="num">${s.count.toLocaleString()}</td>`;
        html += `<td class="num">${s.win_rate_pct.toFixed(1)}%</td>`;
        html += `<td class="num" style="color:${retColor};">${s.avg_return_pct >= 0 ? '+' : ''}${s.avg_return_pct.toFixed(2)}%</td>`;
        html += `<td class="num" style="color:${pnlColor};">$${s.avg_pnl.toLocaleString(undefined,{maximumFractionDigits:0})}</td>`;
        html += `<td class="num" style="color:${alphaColor};">${s.alpha_contribution_pct >= 0 ? '+' : ''}${s.alpha_contribution_pct.toFixed(1)}%</td>`;
        html += `<td class="num">${s.sharpe.toFixed(2)}</td>`;
        html += `</tr>`;
    }
    html += '</tbody></table>';
    box.innerHTML = html;
}





/* ============ EQUITY CURVE + UNDERWATER DRAWDOWN ============ */
let _equityChart = null;
let _underwaterChart = null;

/* Known crisis events for annotation labels */
const DRAWDOWN_EVENTS = [
    { start: '2000-09', end: '2003-05', label: 'Dot-Com Bust' },
    { start: '2007-10', end: '2009-09', label: 'GFC' },
    { start: '2020-02', end: '2020-08', label: 'COVID' },
    { start: '2022-01', end: '2023-10', label: 'Bear Market' },
];

function matchCrisisLabel(dateStr) {
    for (var ev of DRAWDOWN_EVENTS) {
        if (dateStr >= ev.start && dateStr <= ev.end) return ev.label;
    }
    return null;
}

function getDrawdownColor(dd) {
    if (dd >= -10) return 'rgba(22, 163, 74, 0.6)';   /* green */
    if (dd >= -20) return 'rgba(234, 179, 8, 0.6)';    /* yellow */
    return 'rgba(220, 38, 38, 0.6)';                    /* red */
}

function getDarkDrawdownColor(dd) {
    if (dd >= -10) return 'rgba(34, 197, 94, 0.5)';
    if (dd >= -20) return 'rgba(250, 204, 21, 0.5)';
    return 'rgba(239, 68, 68, 0.5)';
}

function updateChartColors() {
    /* Called when dark mode toggles — rebuild charts with correct colors */
    if (_equityChart || _underwaterChart) fetchEquityData();
    if (_annualData) renderAnnualReturns(_annualData.data, _annualData.positive, _annualData.total);
}

async function fetchEquityData() {
    try {
        var res = await fetch('/api/equity');
        var data = await res.json();
        if (!data.equity || data.equity.length === 0) return;
        renderEquityAndDrawdown(data.equity, data.milestones || []);
    } catch (e) {
        console.error('Equity fetch error:', e);
    }
}

function renderEquityAndDrawdown(equity, milestones) {
    var isDark = document.body.classList.contains('dark');
    var dates = [];
    var values = [];
    var ddPcts = [];
    var ddColors = [];

    /* Compute drawdown from peak */
    var peak = 0;
    for (var i = 0; i < equity.length; i++) {
        var pt = equity[i];
        dates.push(pt.date);
        values.push(pt.value);
        if (pt.value > peak) peak = pt.value;
        var dd = ((pt.value - peak) / peak) * 100;
        ddPcts.push(dd);
        ddColors.push(isDark ? getDarkDrawdownColor(dd) : getDrawdownColor(dd));
    }

    /* Badge with date range */
    var badge = document.getElementById('eq-badge');
    if (badge) {
        badge.textContent = dates[0].slice(0, 4) + '–' + dates[dates.length - 1].slice(0, 4) + ' · ' + equity.length + ' points';
    }

    /* Annotations for crisis events on underwater chart */
    var annotations = {};
    var labeledCrises = {};
    var worstByEvent = {};
    for (var j = 0; j < ddPcts.length; j++) {
        var crisis = matchCrisisLabel(dates[j].slice(0, 7));
        if (crisis && ddPcts[j] < (worstByEvent[crisis] || 0)) {
            worstByEvent[crisis] = ddPcts[j];
            labeledCrises[crisis] = j;
        }
    }
    Object.keys(labeledCrises).forEach(function(name) {
        var idx = labeledCrises[name];
        var worstDD = worstByEvent[name];
        annotations['crisis_' + name] = {
            type: 'label',
            xValue: dates[idx],
            yValue: worstDD,
            content: name + ' ' + worstDD.toFixed(1) + '%',
            color: isDark ? '#f87171' : '#dc2626',
            font: { size: 10, weight: '600', family: "'Inter', sans-serif" },
            position: { x: 'center', y: 'start' },
            yAdjust: -14,
        };
    });

    /* Grid colors */
    var gridColor = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)';
    var tickColor = isDark ? '#8888a0' : '#5e5e78';

    /* ---- EQUITY CURVE ---- */
    var eqCtx = document.getElementById('equityCurveChart');
    if (!eqCtx) return;

    /* Milestone annotations for equity chart */
    var eqAnnotations = {};
    if (milestones) {
        milestones.forEach(function(m, mi) {
            if (m.type === 'milestone') {
                eqAnnotations['ms_' + mi] = {
                    type: 'point',
                    xValue: m.date,
                    yValue: m.value,
                    radius: 4,
                    backgroundColor: isDark ? '#22c55e' : '#16a34a',
                    borderColor: isDark ? '#22c55e' : '#16a34a',
                    borderWidth: 2,
                };
                eqAnnotations['ms_label_' + mi] = {
                    type: 'label',
                    xValue: m.date,
                    yValue: m.value,
                    content: m.label,
                    color: isDark ? '#4ade80' : '#16a34a',
                    font: { size: 10, weight: '600' },
                    yAdjust: -16,
                };
            }
        });
    }

    if (_equityChart) _equityChart.destroy();
    _equityChart = new Chart(eqCtx, {
        type: 'line',
        data: {
            labels: dates,
            datasets: [{
                data: values,
                borderColor: isDark ? '#4ade80' : '#16a34a',
                borderWidth: 1.5,
                fill: true,
                backgroundColor: isDark ? 'rgba(34,197,94,0.08)' : 'rgba(22,163,74,0.06)',
                pointRadius: 0,
                tension: 0.1,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(20, 20, 40, 0.95)',
                    borderColor: 'rgba(255,255,255,0.15)',
                    borderWidth: 1,
                    titleFont: { family: "'Inter', sans-serif", size: 12, weight: '600' },
                    bodyFont: { family: "'JetBrains Mono', monospace", size: 11 },
                    displayColors: false,
                    callbacks: {
                        label: function(ctx) {
                            return '$' + ctx.parsed.y.toLocaleString();
                        }
                    }
                },
                annotation: { annotations: eqAnnotations },
                zoom: {
                    zoom: {
                        wheel: { enabled: true },
                        pinch: { enabled: true },
                        mode: 'x',
                    },
                    pan: { enabled: true, mode: 'x' },
                },
            },
            scales: {
                x: {
                    type: 'category',
                    ticks: {
                        color: tickColor,
                        font: { family: "'JetBrains Mono', monospace", size: 10 },
                        maxTicksLimit: 12,
                        callback: function(val, idx) {
                            var d = this.getLabelForValue(val);
                            return d ? d.slice(0, 4) : '';
                        }
                    },
                    grid: { color: gridColor },
                    border: { color: gridColor },
                },
                y: {
                    ticks: {
                        color: tickColor,
                        font: { family: "'JetBrains Mono', monospace", size: 10 },
                        callback: function(v) {
                            if (v >= 1e6) return '$' + (v / 1e6).toFixed(1) + 'M';
                            if (v >= 1e3) return '$' + (v / 1e3).toFixed(0) + 'K';
                            return '$' + v;
                        }
                    },
                    grid: { color: gridColor },
                    border: { color: gridColor },
                }
            }
        }
    });

    /* ---- UNDERWATER CHART ---- */
    var uwCtx = document.getElementById('underwaterChart');
    if (!uwCtx) return;

    if (_underwaterChart) _underwaterChart.destroy();
    _underwaterChart = new Chart(uwCtx, {
        type: 'bar',
        data: {
            labels: dates,
            datasets: [{
                data: ddPcts,
                backgroundColor: ddColors,
                borderWidth: 0,
                barPercentage: 1.0,
                categoryPercentage: 1.0,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(20, 20, 40, 0.95)',
                    borderColor: 'rgba(255,255,255,0.15)',
                    borderWidth: 1,
                    titleFont: { family: "'Inter', sans-serif", size: 12, weight: '600' },
                    bodyFont: { family: "'JetBrains Mono', monospace", size: 11 },
                    displayColors: false,
                    callbacks: {
                        label: function(ctx) {
                            return 'Drawdown: ' + ctx.parsed.y.toFixed(1) + '%';
                        }
                    }
                },
                annotation: { annotations: annotations },
                zoom: {
                    zoom: {
                        wheel: { enabled: true },
                        pinch: { enabled: true },
                        mode: 'x',
                    },
                    pan: { enabled: true, mode: 'x' },
                },
            },
            scales: {
                x: {
                    type: 'category',
                    ticks: {
                        color: tickColor,
                        font: { family: "'JetBrains Mono', monospace", size: 10 },
                        maxTicksLimit: 12,
                        callback: function(val, idx) {
                            var d = this.getLabelForValue(val);
                            return d ? d.slice(0, 4) : '';
                        }
                    },
                    grid: { color: gridColor },
                    border: { color: gridColor },
                },
                y: {
                    max: 0,
                    ticks: {
                        color: tickColor,
                        font: { family: "'JetBrains Mono', monospace", size: 10 },
                        callback: function(v) { return v + '%'; },
                    },
                    grid: { color: gridColor },
                    border: { color: gridColor },
                }
            }
        }
    });
}

/* ============ ANNUAL RETURNS BAR CHART ============ */
let _annualChart = null;
let _annualData = null;

async function fetchAnnualReturns() {
    try {
        var res = await fetch('/api/annual-returns');
        var data = await res.json();
        if (!data.data || data.data.length === 0) return;
        _annualData = { data: data.data, positive: data.positive_years, total: data.total_years };
        renderAnnualReturns(data.data, data.positive_years, data.total_years);
    } catch (e) {
        console.error('Annual returns fetch error:', e);
    }
}

function renderAnnualReturns(data, positiveYears, totalYears) {
    var ctx = document.getElementById('annualReturnsChart');
    if (!ctx) return;

    var isDark = document.body.classList.contains('dark');
    var years = data.map(function(d) { return d.year; });
    var compassRets = data.map(function(d) { return d.compass; });
    var spyRets = data.map(function(d) { return d.spy; });

    /* ── Badge ─────────────────────────────────────────────────────────── */
    var badge = document.getElementById('ar-badge');
    if (badge) badge.textContent = positiveYears + '/' + totalYears + ' positivos';

    /* ── Per-year derived flags ─────────────────────────────────────────── */
    var underperforms = data.map(function(d) {
        return d.spy != null && d.compass < d.spy;
    });

    /* ── Stat block ─────────────────────────────────────────────────────── */
    var compassWins = 0;
    var totalAlpha  = 0;
    var validPairs  = 0;
    data.forEach(function(d) {
        if (d.spy != null) {
            if (d.compass > d.spy) compassWins++;
            totalAlpha += (d.compass - d.spy);
            validPairs++;
        }
    });
    var compassLosses = validPairs - compassWins;
    var avgAlpha      = validPairs > 0 ? totalAlpha / validPairs : 0;
    var alphaSign     = avgAlpha >= 0 ? '+' : '';

    /* Write to new stat-bar elements */
    var elPositive = document.getElementById('ar-stat-positive');
    var elTotal    = document.getElementById('ar-stat-total');
    var elBeats    = document.getElementById('ar-stat-beats');
    var elLoses    = document.getElementById('ar-stat-loses');
    var elAlpha    = document.getElementById('ar-stat-alpha');
    if (elPositive) elPositive.textContent = positiveYears;
    if (elTotal)    elTotal.textContent    = totalYears;
    if (elBeats)    elBeats.textContent    = compassWins + '/' + validPairs;
    if (elLoses) {
        elLoses.textContent = compassLosses + '/' + validPairs;
        /* Colour the "loses" count red only when meaningful */
        elLoses.className = 'ar-stat-value' + (compassLosses > 0 ? ' negative' : ' positive');
    }
    if (elAlpha) {
        elAlpha.textContent = alphaSign + avgAlpha.toFixed(1) + ' pp';
        elAlpha.className   = 'ar-stat-value' + (avgAlpha >= 0 ? ' positive' : ' negative');
    }

    /* ── Design tokens ──────────────────────────────────────────────────── */
    /*
     * COMPASS bars:  solid green (positive) / solid red (negative).
     *                No opacity tricks — colour alone carries the sign.
     * SPY bars:      low-opacity indigo ghost — pure reference, not competitor.
     * Underperform:  communicated through a small yellow diamond drawn on the
     *                Y-axis tick by the custom plugin, not through bar colour.
     */
    var compassColors = compassRets.map(function(v) {
        if (v >= 0) return isDark ? '#22c55e' : '#16a34a';
        return isDark ? '#ef4444' : '#dc2626';
    });
    var spyColors = spyRets.map(function(v) {
        if (v == null) return 'transparent';
        return isDark ? 'rgba(99, 102, 241, 0.28)' : 'rgba(99, 102, 241, 0.22)';
    });
    var spyBorderColors = spyRets.map(function(v) {
        if (v == null) return 'transparent';
        return isDark ? 'rgba(99, 102, 241, 0.55)' : 'rgba(99, 102, 241, 0.50)';
    });

    var gridColor     = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.04)';
    var zeroLineColor = isDark ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.20)';

    /* ── Container height ───────────────────────────────────────────────── */
    /*
     * 30px per year + 80px top/bottom padding.
     * Larger rows give better hover targets and clearer bar separation.
     * Minimum 440px to avoid a squashed look on small data sets.
     */
    var PX_PER_YEAR = 30;
    var chartH = Math.max(440, data.length * PX_PER_YEAR + 80);
    var container = document.getElementById('annual-returns-container');
    if (container) container.style.height = chartH + 'px';

    /* ── Chart ──────────────────────────────────────────────────────────── */
    if (_annualChart) _annualChart.destroy();
    _annualChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: years,
            datasets: [
                {
                    label: 'HYDRA',
                    data: compassRets,
                    backgroundColor: compassColors,
                    borderColor: 'transparent',
                    borderWidth: 0,
                    borderRadius: { topRight: 2, bottomRight: 2, topLeft: 0, bottomLeft: 0 },
                    borderSkipped: false,
                    barPercentage: 0.55,
                    categoryPercentage: 0.72,
                    order: 1,
                },
                {
                    label: 'S&P 500',
                    data: spyRets,
                    backgroundColor: spyColors,
                    borderColor: spyBorderColors,
                    borderWidth: 1,
                    borderRadius: { topRight: 2, bottomRight: 2, topLeft: 0, bottomLeft: 0 },
                    borderSkipped: false,
                    barPercentage: 0.55,
                    categoryPercentage: 0.72,
                    order: 2,
                }
            ]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false, axis: 'y' },
            /* Right padding: enough room for the COMPASS value labels */
            layout: { padding: { top: 4, bottom: 4, left: 0, right: 72 } },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: isDark ? 'rgba(14,14,30,0.97)' : 'rgba(255,255,255,0.97)',
                    borderColor: isDark ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.10)',
                    borderWidth: 1,
                    padding: { x: 14, y: 10 },
                    titleColor: isDark ? '#e4e4f0' : '#1a1a2e',
                    bodyColor:  isDark ? '#a0a0b8' : '#555570',
                    titleFont: { family: "'Inter', sans-serif", size: 13, weight: '700' },
                    bodyFont:  { family: "'JetBrains Mono', monospace", size: 12 },
                    displayColors: true,
                    boxWidth: 10,
                    boxHeight: 10,
                    boxPadding: 4,
                    callbacks: {
                        title: function(items) {
                            return String(items[0].label);
                        },
                        label: function(item) {
                            var val = item.parsed.x;
                            if (val == null) return '';
                            var sign = val >= 0 ? '+' : '';
                            return '  ' + item.dataset.label + ':  ' + sign + val.toFixed(2) + '%';
                        },
                        afterBody: function(items) {
                            var compass = null, spy = null;
                            items.forEach(function(it) {
                                if (it.dataset.label === 'HYDRA') compass = it.parsed.x;
                                if (it.dataset.label === 'S&P 500') spy = it.parsed.x;
                            });
                            if (compass != null && spy != null) {
                                var diff = compass - spy;
                                var sign = diff >= 0 ? '+' : '';
                                var line = '  Alpha:  ' + sign + diff.toFixed(2) + ' pp';
                                return ['', line];
                            }
                            return [];
                        }
                    }
                },
                annotation: {
                    annotations: {
                        zeroLine: {
                            type: 'line',
                            xMin: 0, xMax: 0,
                            borderColor: zeroLineColor,
                            borderWidth: 1,
                            borderDash: [3, 4],
                        }
                    }
                }
            },
            scales: {
                x: {
                    position: 'bottom',
                    title: {
                        display: false
                    },
                    ticks: {
                        color: isDark ? '#404060' : '#a0a0b8',
                        font: { family: "'JetBrains Mono', monospace", size: 10 },
                        maxTicksLimit: 9,
                        callback: function(v) {
                            return (v >= 0 ? '+' : '') + v + '%';
                        }
                    },
                    grid: {
                        color: gridColor,
                        drawTicks: false,
                    },
                    border: { color: 'transparent' },
                },
                y: {
                    ticks: {
                        color: isDark ? '#707090' : '#7070a0',
                        font: {
                            family: "'JetBrains Mono', monospace",
                            size: 11,
                            weight: '500',
                        },
                        /* remove default padding so year label sits tight */
                        padding: 8,
                    },
                    grid: { display: false },
                    border: { color: 'transparent' },
                }
            }
        },
        plugins: [
            /*
             * Plugin 1 — COMPASS value labels
             * Drawn only for dataset 0 (COMPASS).
             * Positive bars: label to the RIGHT of bar end.
             * Negative bars: label to the LEFT of bar end.
             * Font: 10px JetBrains Mono / colour tracks sign.
             */
            {
                id: 'arValueLabels',
                afterDatasetsDraw: function(chart, args, opts) {
                    if (args.index !== 0) return;   /* COMPASS only */
                    var c      = chart.ctx;
                    var dkNow  = document.body.classList.contains('dark');
                    var meta   = chart.getDatasetMeta(0);
                    var ds     = chart.data.datasets[0];

                    c.save();
                    c.font         = "600 10px 'JetBrains Mono', monospace";
                    c.textBaseline = 'middle';

                    meta.data.forEach(function(bar, i) {
                        var val = ds.data[i];
                        if (val == null) return;

                        var sign  = val >= 0 ? '+' : '';
                        var label = sign + val.toFixed(1) + '%';
                        var OFFSET = 5;

                        if (val >= 0) {
                            c.textAlign = 'left';
                            c.fillStyle = dkNow ? 'rgba(34,197,94,0.9)' : 'rgba(22,163,74,0.9)';
                            c.fillText(label, bar.x + OFFSET, bar.y);
                        } else {
                            c.textAlign = 'right';
                            c.fillStyle = dkNow ? 'rgba(239,68,68,0.9)' : 'rgba(220,38,38,0.9)';
                            c.fillText(label, bar.x - OFFSET, bar.y);
                        }
                    });
                    c.restore();
                }
            },
            /*
             * Plugin 2 — Underperformance marker
             * For years where COMPASS < SPY, paint a 3px wide yellow left-edge
             * accent on the Y axis tick area. This signals underperformance without
             * mutating bar colour, keeping the colour system clean.
             */
            {
                id: 'arUnderperformTick',
                afterDraw: function(chart) {
                    var c      = chart.ctx;
                    var yScale = chart.scales.y;
                    var dkNow  = document.body.classList.contains('dark');
                    var accentColor = dkNow ? 'rgba(234,179,8,0.75)' : 'rgba(202,138,4,0.75)';

                    c.save();
                    underperforms.forEach(function(isUnder, i) {
                        if (!isUnder) return;
                        var meta    = chart.getDatasetMeta(0);
                        var barEl   = meta.data[i];
                        if (!barEl) return;
                        /* Vertical centre of this category band */
                        var midY  = barEl.base !== undefined ? (yScale.getPixelForValue(i)) : barEl.y;
                        var halfH = (yScale.getPixelForValue(0) - yScale.getPixelForValue(1)) * 0.40;
                        var chartX = chart.chartArea.left;

                        /* 3px yellow accent bar on the far left of the chart area */
                        c.fillStyle = accentColor;
                        c.beginPath();
                        c.roundRect
                            ? c.roundRect(chartX - 3, midY - halfH, 3, halfH * 2, 1)
                            : c.rect(chartX - 3, midY - halfH, 3, halfH * 2);
                        c.fill();
                    });
                    c.restore();
                }
            }
        ]
    });
}

/* ============ INIT ============ */
document.addEventListener('DOMContentLoaded', function() {
    fetchEquityData();
    fetchAnnualReturns();
    fetchAll();
    fetchCycleLog();

    sfInitFilters();
    fetchSocialFeed();
    fetchTradeAnalytics();
    setInterval(fetchSocialFeed, 300000);
    setInterval(function() { fetchAll(); fetchCycleLog(); countdownSec = 30; }, REFRESH_MS);
    setInterval(function() {
        countdownSec = Math.max(0, countdownSec - 1);
        document.getElementById('countdown').textContent = countdownSec;
    }, 1000);

    /* Market open/close countdown timer */
    function updateMarketTimer() {
        const lbl = document.getElementById('hdr-market-label');
        const cd = document.getElementById('hdr-market-countdown');
        if (!lbl || !cd) return;
        const now = new Date();
        const fmt = new Intl.DateTimeFormat('en-US', {
            timeZone: 'America/New_York',
            hour: 'numeric', minute: 'numeric', second: 'numeric',
            hour12: false, weekday: 'short'
        });
        const parts = Object.fromEntries(fmt.formatToParts(now).map(p => [p.type, p.value]));
        const dayMap = {Sun:0,Mon:1,Tue:2,Wed:3,Thu:4,Fri:5,Sat:6};
        const day = dayMap[parts.weekday] ?? now.getDay();
        const h = parseInt(parts.hour), m = parseInt(parts.minute), s = parseInt(parts.second);
        const mins = h * 60 + m;
        const isWeekday = day >= 1 && day <= 5;
        const mktOpen = 9 * 60 + 30, mktClose = 16 * 60;
        const isOpen = isWeekday && mins >= mktOpen && mins < mktClose;
        if (isOpen) {
            lbl.textContent = 'PAPER TRADING EN VIVO';
            lbl.style.color = 'var(--green)';
            const left = (mktClose * 60) - (mins * 60 + s);
            const hh = Math.floor(left / 3600), mm = Math.floor((left % 3600) / 60), ss = left % 60;
            cd.textContent = 'cierra ' + hh + 'h ' + String(mm).padStart(2,'0') + 'm ' + String(ss).padStart(2,'0') + 's';
        } else {
            lbl.textContent = 'MERCADO CERRADO';
            lbl.style.color = 'var(--text-muted)';
            /* Calculate seconds until next market open using ET time components */
            let secsToOpen = 0;
            const secsNowInDay = h * 3600 + m * 60 + s;
            const mktOpenSecs = 9 * 3600 + 30 * 60;
            if (isWeekday && secsNowInDay < mktOpenSecs) {
                /* Before market open today */
                secsToOpen = mktOpenSecs - secsNowInDay;
            } else {
                /* After close or weekend — count to next weekday 9:30 */
                const secsLeftToday = 86400 - secsNowInDay;
                let daysAhead = 1;
                let nextDay = (day + 1) % 7;
                while (nextDay === 0 || nextDay === 6) { daysAhead++; nextDay = (nextDay + 1) % 7; }
                secsToOpen = secsLeftToday + (daysAhead - 1) * 86400 + mktOpenSecs;
            }
            const diff = Math.max(0, secsToOpen);
            const hh = Math.floor(diff / 3600), mm = Math.floor((diff % 3600) / 60), ss = diff % 60;
            cd.textContent = 'abre ' + hh + 'h ' + String(mm).padStart(2,'0') + 'm ' + String(ss).padStart(2,'0') + 's';
        }
    }
    updateMarketTimer();
    setInterval(updateMarketTimer, 1000);
});

/* ============ EXPERIMENT ANALYSIS PANEL ============ */
function fetchExpAnalysis() {
    const container = document.getElementById('exp-analysis-container');
    if (!container) return;

    const totalExp = 37;
    const failed = 33;
    const approved = 3;  /* v8 COMPASS + Exp #34 IG Cash Yield + EXP59 HYDRA */
    const partial = 2;   /* RATTLESNAKE standalone + QUANTUM */
    const failRate = ((failed / totalExp) * 100).toFixed(1);

    /* Category breakdown */
    const categories = [
        { name: 'Motor (signal/params)', tried: 18, failed: 16, examples: 'v8.1 shorts, rank-hysteresis, VORTEX, behavioral, ensemble, preemptive stop, profit target, MWF, Genius Layer' },
        { name: 'Alternative engines', tried: 7, failed: 5, examples: 'VIPER ETF, ECLIPSE pairs, QUANTUM RSI, RATTLESNAKE mean-rev' },
        { name: 'Geographic expansion', tried: 2, failed: 2, examples: 'COMPASS EU (STOXX), COMPASS Asia (N225)' },
        { name: 'Protection/hedging', tried: 5, failed: 5, examples: 'Inverse ETFs, momentum shorts, OTM puts, gold futures, TLT/IEF' },
        { name: 'Chassis improvements', tried: 5, failed: 2, examples: 'MOC execution, no leverage, IG cash yield, box spread, pre-close signal' },
    ];

    /* Key insights from 37 experiments */
    const insights = [
        { tag: 'PATTERN', tagCls: 'exp-tag-pattern', text: 'Algorithm is inelastic: ANY parameter change degrades performance. 90d lookback, 5d hold, 5 positions are genuinely optimal.' },
        { tag: 'PATTERN', tagCls: 'exp-tag-pattern', text: 'ML complexity destroys signal: v9 Genius Layer (5 ML layers) lost -8.03% CAGR. MLP blocked 62% of selections, HMM overrode regime 1981 times.' },
        { tag: 'PATTERN', tagCls: 'exp-tag-pattern', text: 'Concentrated alpha requires simplicity: ensemble momentum, behavioral overlays, and sector optimization all dilute the signal.' },
        { tag: 'WARNING', tagCls: 'exp-tag-warning', text: 'Geographic expansion is not viable: EU (-20.87%) and Asia (-19.71%) catastrophic. Algorithm relies on US market microstructure.' },
        { tag: 'WARNING', tagCls: 'exp-tag-warning', text: 'Protection mode is a closed question: gold, TLT/IEF, inverse ETFs, momentum shorts all tested and rejected. Cash + Aaa yield is optimal.' },
        { tag: 'IDEA', tagCls: 'exp-tag-idea', text: 'Chassis > Motor: the only approved changes (IG cash yield +1.15%, pre-close signal +0.79%) were infrastructure improvements, not signal changes.' },
    ];

    let html = '<div class="exp-analysis-title">EXPERIMENT ANALYSIS</div>';

    /* Stats grid */
    html += '<div class="exp-analysis-grid">';
    html += '<div class="exp-stat-box"><div class="exp-stat-label">EXPERIMENTS RUN</div><div class="exp-stat-val" style="color:var(--cyan);">' + totalExp + '</div><div class="exp-stat-note">' + failed + ' failed, ' + approved + ' approved, ' + partial + ' partial</div></div>';
    html += '<div class="exp-stat-box"><div class="exp-stat-label">FAILURE RATE</div><div class="exp-stat-val" style="color:var(--red);">' + failRate + '%</div><div class="exp-stat-note">Algorithm inelasticity confirmed</div></div>';
    html += '<div class="exp-stat-box"><div class="exp-stat-label">CAGR BASELINE</div><div class="exp-stat-val" style="color:var(--green);">18.56%</div><div class="exp-stat-note">Signal gross | 15.16% net (after 2.5% costs)</div></div>';
    html += '<div class="exp-stat-box"><div class="exp-stat-label">WORST EXPERIMENT</div><div class="exp-stat-val" style="color:var(--red);">-20.87%</div><div class="exp-stat-note">COMPASS EU v1 ($100K &rarr; $507)</div></div>';
    html += '</div>';

    /* Category breakdown */
    html += '<div class="exp-insights-title">CATEGORY BREAKDOWN</div>';
    html += '<table class="exp-table" style="margin-bottom:18px;">';
    html += '<thead><tr><th>Category</th><th>Tried</th><th>Failed</th><th>Rate</th></tr></thead><tbody>';
    for (const cat of categories) {
        const rate = ((cat.failed / cat.tried) * 100).toFixed(0);
        const cls = cat.failed === cat.tried ? 'exp-fail' : 'exp-partial';
        html += '<tr><td class="exp-name">' + cat.name + '</td><td>' + cat.tried + '</td><td class="' + cls + '">' + cat.failed + '</td><td class="' + cls + '">' + rate + '%</td></tr>';
    }
    html += '</tbody></table>';

    /* Key insights */
    html += '<div class="exp-insights"><div class="exp-insights-title">KEY INSIGHTS</div>';
    for (const ins of insights) {
        html += '<div class="exp-insight-item"><span class="exp-insight-tag ' + ins.tagCls + '">' + ins.tag + '</span>' + ins.text + '</div>';
    }
    html += '</div>';

    /* Conclusion */
    html += '<div class="exp-proposals"><div class="exp-proposals-title">CONCLUSION</div>';
    html += '<div class="exp-proposal-card">';
    html += '<div class="exp-proposal-name">Algorithm Motor: LOCKED <span class="exp-proposal-priority exp-priority-high">FINAL</span></div>';
    html += '<div class="exp-proposal-desc">59 experiments confirm HYDRA (COMPASS + Rattlesnake + Cash Recycling) as the optimal configuration. EXP59 validated segregated accounts with cash recycling: 13.28% CAGR, 1.04 Sharpe, -23.5% MaxDD.</div>';
    html += '<div class="exp-proposal-rationale">Focus on chassis (execution quality, broker integration, data sources) and operations (paper trading, tax optimization, scaling).</div>';
    html += '</div>';

    html += '<div class="exp-proposal-card">';
    html += '<div class="exp-proposal-name">Next Steps: Chassis &amp; Operations <span class="exp-proposal-priority exp-priority-med">ACTIVE</span></div>';
    html += '<div class="exp-proposal-desc">1. Norgate Data (survivorship bias cure) &bull; 2. IBKR paper trading (3-6 months) &bull; 3. Tax optimization (IRA/401k) &bull; 4. Scaling path ($500K+)</div>';
    html += '</div>';
    html += '</div>';

    html += '<div class="exp-updated">Last updated: Feb 25, 2026 &bull; Experiment #37 (v9 Genius Layer) added</div>';

    container.innerHTML = html;
}

/* Terminal removed — replaced with WhatsApp contact FAB */

/* ============ ML LEARNING TAB ============ */
var _mlLastCount = 0;

async function fetchMLLearning() {
    try {
        var res = await fetch('/api/ml-learning');
        var data = await res.json();
        renderMLTerminal(data.log_entries || [], data.insights || {});
        renderMLInterpretation(data.interpretation || '');
    } catch (e) {
        // silent
    }
}

function renderMLTerminal(entries, insights) {
    var logEl = document.getElementById('ml-log');
    var statusEl = document.getElementById('ml-status');
    if (!logEl) return;

    /* Stats row */
    var nDecisions = 0, nSnapshots = 0, nOutcomes = 0;
    entries.forEach(function(r) {
        if (r._type === 'decision') nDecisions++;
        else if (r._type === 'snapshot') nSnapshots++;
        else if (r._type === 'outcome') nOutcomes++;
    });

    var phase = (insights.learning_phase || 1);
    if (statusEl) statusEl.textContent = 'Phase ' + phase;

    var html = '<div class="ml-stats-row">';
    html += '<div class="ml-stat"><span class="ml-stat-label">Decisions</span><span class="ml-stat-value">' + nDecisions + '</span></div>';
    html += '<div class="ml-stat"><span class="ml-stat-label">Snapshots</span><span class="ml-stat-value">' + nSnapshots + '</span></div>';
    html += '<div class="ml-stat"><span class="ml-stat-label">Outcomes</span><span class="ml-stat-value">' + nOutcomes + '</span></div>';
    html += '<div class="ml-stat"><span class="ml-stat-label">Trading Days</span><span class="ml-stat-value">' + (insights.trading_days || '--') + '</span></div>';
    html += '<div class="ml-stat"><span class="ml-stat-label">Phase</span><span class="ml-stat-value">' + phase + '/3</span></div>';
    html += '</div>';

    /* Terminal lines */
    entries.forEach(function(r) {
        var ts = (r.timestamp || r.date || '').replace('T', ' ').substring(0, 19);
        var type = '';
        var badge = '';
        var detail = '';

        if (r._type === 'decision') {
            type = r.decision_type || 'unknown';
            if (type === 'entry') {
                badge = '<span class="ml-line-badge ml-badge-entry">ENTRY</span>';
                var mom = r.momentum_score != null ? r.momentum_score.toFixed(2) : '--';
                var rank = r.momentum_rank != null ? (r.momentum_rank * 100).toFixed(0) + '%' : '--';
                var vol = r.entry_vol_ann != null ? (r.entry_vol_ann * 100).toFixed(0) + '%' : '--';
                var stop = r.adaptive_stop_pct != null ? (r.adaptive_stop_pct * 100).toFixed(1) + '%' : '--';
                detail = '<span class="ml-sym">' + (r.symbol || '??') + '</span> '
                    + '<span class="ml-dim">mom=</span>' + mom
                    + ' <span class="ml-dim">rank=</span>' + rank
                    + ' <span class="ml-dim">vol=</span>' + vol
                    + ' <span class="ml-dim">stop=</span>' + stop
                    + ' <span class="ml-dim">regime=</span>' + (r.regime_bucket || '--');
            } else if (type === 'exit') {
                badge = '<span class="ml-line-badge ml-badge-exit">EXIT</span>';
                var ret = r.current_return != null ? (r.current_return * 100).toFixed(1) + '%' : '--';
                var retCls = (r.current_return || 0) >= 0 ? 'ml-val-pos' : 'ml-val-neg';
                detail = '<span class="ml-sym">' + (r.symbol || '??') + '</span> '
                    + '<span class="ml-dim">reason=</span>' + (r.exit_reason || '--')
                    + ' <span class="ml-dim">return=</span><span class="' + retCls + '">' + ret + '</span>'
                    + ' <span class="ml-dim">days=</span>' + (r.days_held || '--')
                    + ' <span class="ml-dim">regime=</span>' + (r.regime_bucket || '--');
            } else if (type === 'skip') {
                badge = '<span class="ml-line-badge ml-badge-skip">SKIP</span>';
                detail = '<span class="ml-sym">' + (r.symbol || '??') + '</span> '
                    + '<span class="ml-dim">reason=</span>' + (r.skip_reason || '--');
            } else {
                badge = '<span class="ml-line-badge ml-badge-entry">' + type.toUpperCase() + '</span>';
                detail = '<span class="ml-sym">' + (r.symbol || '??') + '</span>';
            }
        } else if (r._type === 'snapshot') {
            badge = '<span class="ml-line-badge ml-badge-snapshot">SNAP</span>';
            var pv = r.portfolio_value != null ? '$' + r.portfolio_value.toLocaleString('en-US', {maximumFractionDigits: 0}) : '--';
            var dd = r.drawdown != null ? (r.drawdown * 100).toFixed(2) + '%' : '--';
            var ddCls = (r.drawdown || 0) < -0.01 ? 'ml-val-neg' : 'ml-dim';
            var posStr = (r.positions || []).join(', ') || '--';
            detail = '<span class="ml-dim">portfolio=</span>' + pv
                + ' <span class="ml-dim">dd=</span><span class="' + ddCls + '">' + dd + '</span>'
                + ' <span class="ml-dim">pos=</span>' + (r.n_positions || 0)
                + ' <span class="ml-dim">regime=</span>' + (r.regime_bucket || '--')
                + ' <span class="ml-dim">[' + posStr + ']</span>';
        } else if (r._type === 'outcome') {
            badge = '<span class="ml-line-badge ml-badge-outcome">TRADE</span>';
            var gr = r.gross_return != null ? (r.gross_return * 100).toFixed(1) + '%' : '--';
            var grCls = (r.gross_return || 0) >= 0 ? 'ml-val-pos' : 'ml-val-neg';
            var pnl = r.pnl_usd != null ? '$' + r.pnl_usd.toFixed(0) : '--';
            detail = '<span class="ml-sym">' + (r.symbol || '??') + '</span> '
                + '<span class="ml-dim">result=</span><span class="' + grCls + '">' + gr + '</span>'
                + ' <span class="ml-dim">pnl=</span>' + pnl
                + ' <span class="ml-dim">exit=</span>' + (r.exit_reason || '--')
                + ' <span class="ml-dim">days=</span>' + (r.trading_days_held || '--')
                + ' <span class="ml-dim">label=</span>' + (r.outcome_label || '--');
        }

        html += '<div class="ml-line"><span class="ml-line-ts">' + ts + '</span>' + badge + '<span class="ml-line-detail">' + detail + '</span></div>';
    });

    logEl.innerHTML = html;

    /* Auto-scroll on new entries */
    if (entries.length > _mlLastCount) {
        logEl.scrollTop = logEl.scrollHeight;
        _mlLastCount = entries.length;
    }
}

function renderMLInterpretation(text) {
    var el = document.getElementById('ml-interpret');
    var timeEl = document.getElementById('ml-interpret-time');
    if (!el) return;
    if (!text) {
        el.innerHTML = '<p class="ml-interpret-loading">Waiting for analysis...</p>';
        return;
    }
    /* Simple markdown-to-HTML */
    var html = text
        .replace(/### (.+)/g, '<h3>$1</h3>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/^- (.+)$/gm, '<li>$1</li>')
        .replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>')
        .replace(/\n\n/g, '</p><p>')
        .replace(/\n/g, '<br>');
    if (!html.startsWith('<')) html = '<p>' + html + '</p>';
    el.innerHTML = html;
    if (timeEl) {
        var now = new Date();
        timeEl.textContent = 'Updated ' + now.toLocaleTimeString('en-US', {hour:'2-digit', minute:'2-digit'});
    }
}

/* Poll ML data every 60s */
setInterval(fetchMLLearning, 60000);
/* Initial load on page ready */
document.addEventListener('DOMContentLoaded', function() {
    fetchMLLearning();
});
