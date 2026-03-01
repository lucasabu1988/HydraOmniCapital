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
        rt.innerHTML = '<span class="hdr-pill-dot"></span> RISK ON';
        rt.className = 'hdr-pill hdr-pill-on';
    } else {
        rt.innerHTML = '<span class="hdr-pill-dot"></span> RISK OFF';
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
        'Last update: ' + ts + '<br>Next refresh in: ' + countdownSec + 's';
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
            label.textContent = 'WAITING FOR 15:30 SIGNAL';
            label.style.color = 'var(--text-tertiary)';
            seg.classList.remove('active');
            break;
        case 'window_open':
            dot.className = 'preclose-dot preclose-dot-window';
            label.textContent = 'PRE-CLOSE WINDOW OPEN';
            label.style.color = 'var(--yellow)';
            seg.classList.add('active');
            break;
        case 'entries_done':
            dot.className = 'preclose-dot preclose-dot-done';
            label.textContent = 'MOC ENTRIES SENT';
            label.style.color = 'var(--green)';
            seg.classList.add('active');
            break;
        default: /* market_closed */
            dot.className = 'preclose-dot preclose-dot-closed';
            label.textContent = 'MARKET CLOSED';
            label.style.color = 'var(--text-muted)';
            seg.classList.remove('active');
    }
}

function updateCards(p) {
    const yieldAdj = p.accumulated_yield || 0;
    const adjPortfolio = p.portfolio_value + yieldAdj;
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
    document.getElementById('card-invested').textContent = 'Invested: ' + fmt$(p.invested);

    const dd = document.getElementById('card-drawdown');
    dd.textContent = fmtPct(p.drawdown);
    dd.className = 'metric-value ' + (p.drawdown > -5 ? 'c-green' : p.drawdown > -10 ? 'c-yellow' : 'c-red');
    document.getElementById('card-peak').textContent = 'Peak: ' + fmt$(p.peak_value);

    document.getElementById('card-positions').textContent = p.num_positions + ' / ' + p.max_positions;
    document.getElementById('card-maxpos').textContent = p.regime + (p.in_protection ? ' | DD Scaling' : '');

    // Cash yield (Aaa IG Corporate)
    const yd = document.getElementById('yield-daily');
    if (p.daily_yield != null) {
        yd.textContent = '+$' + p.daily_yield.toFixed(2) + '/d';
        yd.className = 'metric-value c-green';
    }
    const ya = document.getElementById('yield-accum');
    if (ya && p.accumulated_yield != null) {
        ya.textContent = 'Acum: +$' + p.accumulated_yield.toFixed(2) + ' (' + (p.aaa_rate || 0).toFixed(1) + '%)';
    }
}


function updatePerfBanner(p) {
    /* COMPASS side — include accumulated cash yield in P&L */
    const yieldAdj = p.accumulated_yield || 0;
    const adjPortfolio = p.portfolio_value + yieldAdj;
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
            alphaLabel.textContent = 'Beating SPY';
            alphaLabel.style.color = 'var(--green)';
        } else {
            alphaEl.textContent = '-' + absDiff + ' pp';
            alphaEl.className = 'perf-vs-alpha c-red';
            alphaLabel.textContent = 'Trailing SPY';
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
            'Live test \u00B7 Day ' + days + ' \u00B7 Started Feb 19, 2026';
    }
}


function updatePositions(details) {
    const grid = document.getElementById('positions-grid');
    const totalBar = document.getElementById('positions-total-bar');
    currentPositions = {};

    if (!details || details.length === 0) {
        grid.innerHTML = '<div class="positions-empty"><div class="positions-empty-icon">&#9671;</div>NO POSITIONS</div>';
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
        const pnlBadgeCls = isProfit ? 'pnl-up' : 'pnl-dn';

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

        const priceChange = p.current_price - p.entry_price;
        const priceChangeSign = priceChange >= 0 ? '+' : '';

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
                '<span class="pos-pnl-badge ' + pnlBadgeCls + '">' + fmtPct(p.pnl_pct) + '</span>' +
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
                '<div class="pos-datum"><span class="pos-datum-label">Chg</span><span class="pos-datum-value ' + colorCls(priceChange) + '">' + priceChangeSign + '$' + Math.abs(priceChange).toFixed(2) + '</span></div>' +
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
                    '<span class="pos-stop-label">Stop</span>' +
                    '<span class="pos-stop-val">$' + p.position_stop_level.toFixed(2) + '</span>' +
                '</div>' +
                trailHtml +
                (p.near_stop ? '<span style="margin-left:auto; font-size:10px; font-weight:700; color:var(--yellow); letter-spacing:0.5px;">&#9888; NEAR STOP</span>' : '') +
            '</div>' +
        '</div>';
    }

    /* Experiment history table — hidden (internal reference only) */

    grid.innerHTML = html;

    /* --- Tooltip positioning (fixed, never clipped) --- */
    grid.querySelectorAll('.ticker-tip-wrap').forEach(function(wrap) {
        var tip = wrap.querySelector('.ticker-tip');
        if (!tip) return;
        wrap.addEventListener('mouseenter', function(e) {
            var rect = wrap.getBoundingClientRect();
            tip.style.display = 'block';
            /* Position above the ticker, left-aligned to it */
            var tipW = 260;
            var left = rect.left;
            /* Keep within viewport */
            if (left + tipW > window.innerWidth - 12) left = window.innerWidth - tipW - 12;
            if (left < 12) left = 12;
            var top = rect.top - tip.offsetHeight - 10;
            /* If above would go off screen, show below */
            if (top < 8) {
                top = rect.bottom + 10;
                tip.classList.add('tip-below');
            } else {
                tip.classList.remove('tip-below');
            }
            tip.style.left = left + 'px';
            tip.style.top = top + 'px';
            /* Adjust arrow to point at ticker center */
            var arrowLeft = (rect.left + rect.width / 2) - left;
            arrowLeft = Math.max(14, Math.min(arrowLeft, tipW - 14));
            tip.style.setProperty('--arrow-left', arrowLeft + 'px');
        });
        wrap.addEventListener('mouseleave', function() {
            tip.style.display = 'none';
        });
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
    document.getElementById('pt-count').textContent = details.length + ' Position' + (details.length !== 1 ? 's' : '');
    document.getElementById('pt-value').textContent = fmt$(totalValue);
    const ptPnl = document.getElementById('pt-pnl');
    ptPnl.textContent = fmt$(totalPnl);
    ptPnl.className = 'pt-stat-value ' + totCls;
    const ptPct = document.getElementById('pt-pct');
    ptPct.textContent = fmtPct(totalPnlPct);
    ptPct.className = 'pt-stat-value ' + totCls;
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
        html += '<span class="uni-badge' + (isHeld ? ' held' : '') + '">' + sym + '</span>';
    }
    grid.innerHTML = html;
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
    /* Highlight $TICKER and #TICKER patterns */
    return escHtml(text).replace(/(\$[A-Z]{1,5})/g, '<span class="sf-cashtag">$1</span>')
                        .replace(/(#[A-Z]{1,5})/g, '<span class="sf-cashtag">$1</span>');
}

function updateSocialFeed(messages) {
    const panel = document.getElementById('sf-body');
    const countEl = document.getElementById('sf-count');
    if (!panel) return;

    if (!messages || messages.length === 0) {
        panel.innerHTML = '<div class="sf-empty">Loading social feed...</div>';
        if (countEl) countEl.textContent = '';
        return;
    }

    if (countEl) countEl.textContent = messages.length + ' posts';

    let html = '';
    for (const m of messages) {
        const timeStr = sfTimeAgo(m.time);
        let safeUrl = '';
        if (m.url) {
            try { const u = new URL(m.url); if (u.protocol === 'https:' || u.protocol === 'http:') safeUrl = m.url; } catch(e) {}
        }
        const bodyHtml = safeUrl ?
            '<a href="' + escHtml(safeUrl) + '" target="_blank" rel="noopener noreferrer">' + highlightCashtags(m.body) + '</a>' :
            highlightCashtags(m.body);
        const srcMap = {
            'reddit': ['sf-src-reddit', 'Reddit'],
            'news': ['sf-src-news', 'News'],
            'seekingalpha': ['sf-src-seekingalpha', 'SeekingAlpha'],
            'sec': ['sf-src-sec', 'SEC'],
            'google': ['sf-src-google', 'Google'],
            'marketwatch': ['sf-src-marketwatch', 'MarketWatch'],
        };
        const [srcCls, srcLabel] = srcMap[m.source] || ['sf-src-news', m.source || 'News'];
        const sentimentHtml = m.sentiment === 'bullish' ?
            '<span class="sf-sentiment sf-sentiment-bull">Bull</span>' :
            m.sentiment === 'bearish' ?
            '<span class="sf-sentiment sf-sentiment-bear">Bear</span>' : '';

        html += '<div class="sf-msg">' +
            '<div class="sf-msg-badge">' +
                '<span class="sf-ticker">$' + escHtml(m.symbol) + '</span>' +
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
    panel.innerHTML = html;
}

async function fetchSocialFeed() {
    try {
        const res = await fetch('/api/social-feed');
        const data = await res.json();
        updateSocialFeed(data.messages);
    } catch(e) { console.error('Social feed error:', e); }
}





/* ============ CYCLE LOG ============ */
async function fetchCycleLog() {
    try {
        const res = await fetch('/api/cycle-log');
        const cycles = await res.json();
        const tbody = document.getElementById('cycle-log-body');
        if (!tbody || !cycles.length) {
            if (tbody) tbody.innerHTML = '<tr><td colspan="7" style="color:var(--text-muted);text-align:center;">No cycles completed yet</td></tr>';
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
            const tickers = c.positions ? c.positions.join(', ') : '--';
            const status = isActive
                ? '<span class="cl-active">● ACTIVE</span>'
                : (c.compass_return != null && c.compass_return >= 0 ? '<span class="cl-pos">✓ WIN</span>' : '<span class="cl-neg">✗ LOSS</span>');
            html += '<tr>' +
                '<td>#' + c.cycle + '</td>' +
                '<td>' + period + '</td>' +
                '<td class="cl-tickers">' + tickers + '</td>' +
                '<td class="' + compassCls + '">' + compass + '</td>' +
                '<td class="' + spyCls + '">' + spy + '</td>' +
                '<td class="' + alphaCls + '">' + alpha + '</td>' +
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
}

async function fetchAll() {
    try {
        const stateRes = await fetch('/api/state');
        const stateData = await stateRes.json();

        if (stateData.status === 'offline') {
            const banner = document.getElementById('offline-banner');
            banner.style.display = 'block';
            banner.textContent = _fetchRetries > 0
                ? 'WAKING UP SERVER... RETRY ' + _fetchRetries + '/' + MAX_RETRIES
                : 'CONNECTING TO SERVER...';
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
            updatePerfBanner(p);
            updatePreclose(stateData.preclose);
            updatePositions(stateData.position_details);
            if (stateData.prices) updateSpyTracker(stateData.prices, stateData.prev_closes);
            const posDict = {};
            if (stateData.position_details) {
                for (const pd of stateData.position_details) posDict[pd.symbol] = true;
            }
            updateUniverse(stateData.universe, posDict);
        }
    } catch (err) {
        console.error('Fetch error:', err);
        const banner = document.getElementById('offline-banner');
        banner.style.display = 'block';
        banner.innerHTML = _fetchRetries > 0
            ? 'WAKING UP SERVER... RETRY ' + _fetchRetries + '/' + MAX_RETRIES
            : 'CONNECTING TO SERVER...';
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




/* ============ FUND SCATTER CHART ============ */
/* Fund data with categories and Max Drawdown */
const FUND_DATA = [
    /* COMPASS v8.3 (1x leverage) — leverage-adjusted = nominal */
    { x: 0.80, y: 11.57, label: 'COMPASS v8.3', lev: 1, color: '#22c55e', cat: 'compass', maxDD: -29.6, aum: '0.1M', desc: 'v8.3 bias-corrected, no leverage, 0 stop events' },
    /* Elite Multi-Strategy (high leverage) — y = nominal CAGR / leverage */
    { x: 2.2, y: 2.74, label: 'Citadel Wellington', lev: 7, color: '#f97316', cat: 'elite', maxDD: -8.0, aum: '$66B', desc: 'Multi-strategy, 7x lev → 19.2% nominal / 7 = 2.7% per turn of leverage' },
    { x: 1.7, y: 2.58, label: 'D.E. Shaw', lev: 5, color: '#f97316', cat: 'elite', maxDD: -12.0, aum: '$60B', desc: 'Quant multi-strategy, 5x lev → 12.9% nominal / 5 = 2.6%' },
    { x: 1.8, y: 4.63, label: 'PDT Partners', lev: 4, color: '#f97316', cat: 'elite', maxDD: -10.0, aum: '$10B', desc: 'Statistical arbitrage, 4x lev → 18.5% nominal / 4 = 4.6%' },
    { x: 2.5, y: 1.17, label: 'Millennium', lev: 12, color: '#f97316', cat: 'elite', maxDD: -7.6, aum: '$64B', desc: 'Pod-based, 12x lev → 14.0% nominal / 12 = 1.2%' },
    { x: 1.2, y: 3.0, label: 'Two Sigma', lev: 4, color: '#f97316', cat: 'elite', maxDD: -15.0, aum: '$60B', desc: 'AI/ML-driven, 4x lev → 12.0% nominal / 4 = 3.0%' },
    /* Systematic / Trend-Following — y = nominal / leverage */
    { x: 0.85, y: 3.83, label: 'Bridgewater Pure Alpha', lev: 3, color: '#3b82f6', cat: 'systematic', maxDD: -23.0, aum: '$150B', desc: 'Macro trend-following, 3x lev → 11.5% / 3 = 3.8%' },
    { x: 0.80, y: 3.87, label: 'Man AHL', lev: 3, color: '#3b82f6', cat: 'systematic', maxDD: -20.0, aum: '$50B', desc: 'Systematic CTA, 3x lev → 11.6% / 3 = 3.9%' },
    { x: 0.78, y: 4.23, label: 'Winton', lev: 3, color: '#3b82f6', cat: 'systematic', maxDD: -22.0, aum: '$6B', desc: 'Statistical trend-following, 3x lev → 12.7% / 3 = 4.2%' },
    { x: 0.60, y: 2.93, label: 'Aspect Capital', lev: 3, color: '#3b82f6', cat: 'systematic', maxDD: -25.0, aum: '$9B', desc: 'Diversified CTA, 3x lev → 8.8% / 3 = 2.9%' },
    /* Momentum Funds (long-only, 1x) — leverage-adjusted = nominal */
    { x: 0.97, y: 15.10, label: 'iShares MTUM', lev: 1, color: '#06b6d4', cat: 'momentum', maxDD: -34.1, aum: '$21B', desc: 'MSCI USA Momentum SR Variant Index, 125 stocks, quarterly rebalance, 1x leverage' },
    { x: 0.91, y: 13.96, label: 'AQR Momentum (AMOMX)', lev: 1, color: '#06b6d4', cat: 'momentum', maxDD: -34.3, aum: '$656M', desc: 'Composite momentum signal (price+earnings+residual), 320 stocks, 1x leverage' },
    { x: 0.55, y: 4.0, label: 'Renaissance RIEF', lev: 2, color: '#06b6d4', cat: 'momentum', maxDD: -28.0, aum: '$55B', desc: 'Public markets quant, 2x lev → 8.0% / 2 = 4.0%' },
    /* Benchmarks (1x) — leverage-adjusted = nominal */
    { x: 0.50, y: 10.4, label: 'S&P 500', lev: 1, color: '#6366f1', cat: 'benchmark', maxDD: -56.8, aum: '-', desc: 'US large-cap index (buy & hold), 1x' },
    { x: 0.65, y: 8.2, label: '60/40 Portfolio', lev: 1, color: '#6366f1', cat: 'benchmark', maxDD: -35.0, aum: '-', desc: '60/40 classic allocation, 1x' },
];

let _fundChart = null;
let _fundFilter = 'all';

function toggleFundCategory(cat) {
    _fundFilter = cat;
    /* Update button states */
    document.querySelectorAll('#fund-comparison-card .chart-btn').forEach(b => b.classList.remove('active'));
    const btn = document.getElementById('fund-btn-' + cat);
    if (btn) btn.classList.add('active');
    initFundScatterChart();
}

function initFundScatterChart() {
    const ctx = document.getElementById('fundScatterChart');
    if (!ctx) return;

    const filtered = _fundFilter === 'all' ? FUND_DATA
        : FUND_DATA.filter(f => f.cat === _fundFilter || f.cat === 'compass');

    /* Update badge */
    const badge = document.getElementById('fund-count-badge');
    if (badge) badge.textContent = filtered.length + ' funds';

    /* Build datasets — one per category for proper legend control */
    const datasets = [{
        data: filtered.map(f => ({ x: f.x, y: f.y, r: f.cat === 'compass' ? 10 + f.lev * 2 : 5 + f.lev * 2.5,
                                    label: f.label, lev: f.lev, maxDD: f.maxDD, aum: f.aum, desc: f.desc, cat: f.cat })),
        backgroundColor: filtered.map(f => f.cat === 'compass' ? f.color : f.color + '88'),
        borderColor: filtered.map(f => f.color),
        borderWidth: filtered.map(f => f.cat === 'compass' ? 3 : 1.5),
        hoverBorderWidth: 3,
        hoverBorderColor: filtered.map(f => f.color),
    }];

    if (_fundChart) _fundChart.destroy();

    _fundChart = new Chart(ctx, {
        type: 'bubble',
        data: { datasets: datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'nearest', intersect: true },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(20, 20, 40, 0.95)',
                    borderColor: 'rgba(255,255,255,0.15)',
                    borderWidth: 1,
                    titleColor: '#fff',
                    bodyColor: '#d0d0e0',
                    titleFont: { family: "'Inter', sans-serif", size: 14, weight: '700' },
                    bodyFont: { family: "'JetBrains Mono', monospace", size: 11 },
                    footerFont: { family: "'Inter', sans-serif", size: 10, style: 'italic' },
                    footerColor: '#888',
                    padding: 14,
                    cornerRadius: 8,
                    displayColors: false,
                    callbacks: {
                        title: function(items) { return items[0].raw.label; },
                        label: function(item) {
                            const d = item.raw;
                            const nominalCAGR = d.y * d.lev;
                            return [
                                'Lev-Adj CAGR: ' + d.y.toFixed(1) + '%  (nominal ' + nominalCAGR.toFixed(1) + '%)',
                                'Sharpe:       ' + d.x.toFixed(2),
                                'Max DD:       ' + d.maxDD.toFixed(1) + '%',
                                'Leverage:     ' + d.lev + 'x',
                                'AUM:          ' + d.aum,
                            ];
                        },
                        footer: function(items) {
                            return items[0].raw.desc;
                        }
                    }
                },
                /* Quadrant lines: COMPASS as reference */
                annotation: {
                    annotations: {
                        compassCAGR: {
                            type: 'line', yMin: 11.57, yMax: 11.57,
                            borderColor: 'rgba(34,197,94,0.2)', borderWidth: 1, borderDash: [6, 4],
                            label: { content: 'COMPASS v8.3 — 11.57%', display: true, position: 'start',
                                     color: 'rgba(34,197,94,0.5)', font: {size: 9}, backgroundColor: 'transparent', padding: 2 }
                        },
                        compassSharpe: {
                            type: 'line', xMin: 0.80, xMax: 0.80,
                            borderColor: 'rgba(34,197,94,0.2)', borderWidth: 1, borderDash: [6, 4],
                        }
                    }
                }
            },
            scales: {
                x: {
                    title: { display: true, text: 'Sharpe Ratio', color: '#7a7a90',
                             font: { family: "'Inter', sans-serif", size: 12, weight: '600' } },
                    min: 0.2, max: 2.8,
                    grid: { color: 'rgba(0,0,0,0.04)' },
                    ticks: { color: '#5e5e78', font: { family: "'JetBrains Mono', monospace", size: 11 },
                             stepSize: 0.5 },
                    border: { color: 'rgba(0,0,0,0.06)' }
                },
                y: {
                    title: { display: true, text: 'Leverage-Adjusted CAGR (%)  [CAGR / Leverage]', color: '#7a7a90',
                             font: { family: "'Inter', sans-serif", size: 12, weight: '600' } },
                    min: 0, max: 17,
                    grid: { color: 'rgba(0,0,0,0.04)' },
                    ticks: { color: '#5e5e78', font: { family: "'JetBrains Mono', monospace", size: 11 },
                             callback: v => v + '%', stepSize: 2 },
                    border: { color: 'rgba(0,0,0,0.06)' }
                }
            },
            /* Draw fund labels */
            animation: {
                onComplete: function() {
                    const chart = this;
                    const ctx2 = chart.ctx;
                    ctx2.save();
                    ctx2.textAlign = 'left';
                    const meta = chart.getDatasetMeta(0);
                    if (!meta || !meta.data) { ctx2.restore(); return; }
                    meta.data.forEach(function(el, i) {
                        const f = filtered[i];
                        if (!f || !el) return;
                        const px = el.x, py = el.y;
                        const isCompass = f.cat === 'compass';
                        /* Font weight */
                        ctx2.font = isCompass ? "700 10px 'Inter', sans-serif" : "500 9px 'Inter', sans-serif";
                        /* Label offsets */
                        let ox = (f.cat === 'compass' ? 14 : 5 + f.lev * 2.5 + 4), oy = -6;
                        /* Manual adjustments for overlapping labels */
                        if (f.label === 'COMPASS v8.3') { oy = -14; }
                        if (f.label === 'iShares MTUM') { oy = -14; }
                        if (f.label === 'AQR Momentum (AMOMX)') { oy = 18; }
                        if (f.label === 'Man AHL') { oy = 16; }
                        if (f.label === 'Bridgewater Pure Alpha') { oy = 16; }
                        if (f.label === 'S&P 500') { oy = -12; }
                        if (f.label === '60/40 Portfolio') { oy = 16; }
                        if (f.label === 'Aspect Capital') { oy = -12; }
                        if (f.label === 'Renaissance RIEF') { oy = -12; }
                        if (f.label === 'Millennium') { oy = 16; }
                        if (f.label === 'Two Sigma') { oy = -12; }
                        if (f.label === 'Winton') { oy = -12; }
                        if (f.label === 'D.E. Shaw') { oy = 16; }
                        if (f.label === 'PDT Partners') { oy = -12; }
                        /* Draw background pill for COMPASS labels */
                        if (isCompass) {
                            const tw = ctx2.measureText(f.label).width;
                            ctx2.fillStyle = 'rgba(34,197,94,0.1)';
                            ctx2.beginPath();
                            ctx2.roundRect(px + ox - 4, py + oy - 10, tw + 8, 14, 3);
                            ctx2.fill();
                            ctx2.fillStyle = '#22c55e';
                        } else {
                            ctx2.fillStyle = f.color + 'bb';
                        }
                        ctx2.fillText(f.label, px + ox, py + oy);
                    });
                    ctx2.restore();
                }
            }
        }
    });
}

/* ============ INIT ============ */
document.addEventListener('DOMContentLoaded', function() {
    /* Init fund scatter chart (visible on dashboard load) */
    initFundScatterChart();
    fetchAll();
    fetchCycleLog();

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
            lbl.textContent = 'LIVE PAPER TRADING';
            lbl.style.color = 'var(--green)';
            const left = (mktClose * 60) - (mins * 60 + s);
            const hh = Math.floor(left / 3600), mm = Math.floor((left % 3600) / 60), ss = left % 60;
            cd.textContent = 'closes ' + hh + 'h ' + String(mm).padStart(2,'0') + 'm ' + String(ss).padStart(2,'0') + 's';
        } else {
            lbl.textContent = 'MARKET CLOSED';
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
            cd.textContent = 'opens ' + hh + 'h ' + String(mm).padStart(2,'0') + 'm ' + String(ss).padStart(2,'0') + 's';
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
    const approved = 2;  /* v8 COMPASS + Exp #34 IG Cash Yield */
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
    html += '<div class="exp-proposal-desc">53 experiments confirm COMPASS v8.3 has reached optimal risk/return balance. 6 structural improvements + 3 bug fixes over v8.2.</div>';
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
