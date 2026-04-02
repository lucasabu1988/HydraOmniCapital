/* ============ DARK MODE (always on) ============ */
document.body.classList.add('dark');

/* ============ COMPANY INFO MAP (for ticker tooltips) ============ */
const COMPANY_INFO = {
    'AAPL': {name:'Apple',sector:'Technology',cap:'$3.4T',desc:'Consumer electronics (iPhone, Mac), services (App Store, iCloud), and wearables'},
    'NVDA': {name:'NVIDIA',sector:'Semiconductors',cap:'$2.8T',desc:'GPU chips for AI training/inference, gaming, data centers, and autonomous vehicles'},
    'NFLX': {name:'Netflix',sector:'Entertainment',cap:'$400B',desc:'Global streaming platform for movies, TV series, and original content'},
    'AMD':  {name:'AMD',sector:'Semiconductors',cap:'$200B',desc:'CPUs and GPUs for gaming, data centers, and embedded systems'},
    'ABT':  {name:'Abbott Laboratories',sector:'Healthcare',cap:'$200B',desc:'Medical devices, diagnostics, nutrition products, and branded generics'},
    'ACN':  {name:'Accenture',sector:'IT Services',cap:'$210B',desc:'Global IT consulting, technology services, and outsourcing'},
    'AIG':  {name:'AIG',sector:'Insurance',cap:'$50B',desc:'Global insurance and financial services for commercial and personal lines'},
    'AMGN': {name:'Amgen',sector:'Biotechnology',cap:'$160B',desc:'Biotechnology company focused on oncology, cardiovascular, and bone health'},
    'AMT':  {name:'American Tower',sector:'REITs',cap:'$95B',desc:'Real estate investment trust owning cell towers and wireless infrastructure'},
    'AXP':  {name:'American Express',sector:'Financial Services',cap:'$190B',desc:'Credit cards, charge cards, and travel-related services'},
    'BK':   {name:'BNY Mellon',sector:'Banking',cap:'$55B',desc:'Global investment services and management, custody, and treasury services'},
    'BKNG': {name:'Booking Holdings',sector:'Travel',cap:'$160B',desc:'Online travel reservations (Booking.com, Priceline, Kayak)'},
    'BLK':  {name:'BlackRock',sector:'Asset Management',cap:'$145B',desc:'Largest asset manager globally with iShares ETFs and Aladdin platform'},
    'BMY':  {name:'Bristol-Myers Squibb',sector:'Pharmaceuticals',cap:'$110B',desc:'Pharmaceuticals in oncology, cardiovascular, and immunology'},
    'CAT':  {name:'Caterpillar',sector:'Industrials',cap:'$180B',desc:'Construction and mining equipment, diesel engines, and industrial turbines'},
    'CHTR': {name:'Charter Communications',sector:'Telecom',cap:'$55B',desc:'Cable TV, internet, and phone services under the Spectrum brand'},
    'CL':   {name:'Colgate-Palmolive',sector:'Consumer Staples',cap:'$80B',desc:'Oral care (Colgate), home care, and personal care products globally'},
    'CMCSA':{name:'Comcast',sector:'Media / Telecom',cap:'$160B',desc:'Cable TV (Xfinity), NBCUniversal media, and Peacock streaming'},
    'COF':  {name:'Capital One',sector:'Banking',cap:'$70B',desc:'Consumer and commercial banking focused on credit cards and auto loans'},
    'COP':  {name:'ConocoPhillips',sector:'Energy',cap:'$130B',desc:'Independent oil and gas exploration and production company'},
    'CSCO': {name:'Cisco Systems',sector:'Networking',cap:'$230B',desc:'Networking hardware, software, and cybersecurity for enterprises'},
    'CVS':  {name:'CVS Health',sector:'Healthcare',cap:'$80B',desc:'Pharmacy retail chain, health insurance (Aetna), and pharmacy benefits'},
    'DE':   {name:'Deere & Company',sector:'Industrials',cap:'$120B',desc:'Agricultural, construction, and forestry machinery manufacturer'},
    'DHR':  {name:'Danaher',sector:'Healthcare',cap:'$170B',desc:'Life sciences, diagnostics, and environmental solutions instruments'},
    'DIS':  {name:'Walt Disney',sector:'Entertainment',cap:'$200B',desc:'Theme parks, Disney+, ESPN, Marvel, Pixar, and Star Wars franchises'},
    'DOW':  {name:'Dow Inc',sector:'Chemicals',cap:'$30B',desc:'Commodity chemicals, plastics, and agricultural products'},
    'DUK':  {name:'Duke Energy',sector:'Utilities',cap:'$85B',desc:'Electric and gas utility serving the southeastern and midwestern US'},
    'EMR':  {name:'Emerson Electric',sector:'Industrials',cap:'$70B',desc:'Automation solutions, climate technologies, and industrial tools'},
    'EXC':  {name:'Exelon',sector:'Utilities',cap:'$45B',desc:'Largest US regulated electric utility serving 10M customers'},
    'F':    {name:'Ford Motor',sector:'Automotive',cap:'$40B',desc:'Automobiles and trucks including F-150, Mustang, and electric vehicles'},
    'FDX':  {name:'FedEx',sector:'Logistics',cap:'$60B',desc:'Global courier delivery, package shipping, and freight services'},
    'GD':   {name:'General Dynamics',sector:'Defense',cap:'$80B',desc:'Aerospace, combat vehicles, weapons systems, and IT services for defense'},
    'GILD': {name:'Gilead Sciences',sector:'Biotechnology',cap:'$120B',desc:'Antiviral therapies for HIV, hepatitis, and oncology treatments'},
    'GM':   {name:'General Motors',sector:'Automotive',cap:'$45B',desc:'Automobiles including Chevrolet, GMC, Cadillac, and electric vehicles'},
    'GOOG': {name:'Alphabet (C)',sector:'Internet / AI',cap:'$2.2T',desc:'Google Search, YouTube, Google Cloud, and Waymo (Class C shares)'},
    'HON':  {name:'Honeywell',sector:'Industrials',cap:'$145B',desc:'Aerospace, building technologies, performance materials, and safety solutions'},
    'INTU': {name:'Intuit',sector:'Software',cap:'$180B',desc:'TurboTax, QuickBooks, Credit Karma, and Mailchimp financial software'},
    'KHC':  {name:'Kraft Heinz',sector:'Consumer Staples',cap:'$40B',desc:'Packaged foods and beverages (Heinz ketchup, Kraft cheese, Oscar Mayer)'},
    'KO':   {name:'Coca-Cola',sector:'Beverages',cap:'$270B',desc:'Global beverage company with Coke, Sprite, Fanta, and Minute Maid'},
    'LIN':  {name:'Linde',sector:'Chemicals',cap:'$220B',desc:'Industrial gases and engineering for healthcare, manufacturing, and energy'},
    'LMT':  {name:'Lockheed Martin',sector:'Defense',cap:'$120B',desc:'F-35 fighter jets, missiles, space systems, and defense technology'},
    'LOW':  {name:'Lowes',sector:'Retail',cap:'$140B',desc:'Home improvement retail chain competing with Home Depot'},
    'MCD':  {name:'McDonalds',sector:'Restaurants',cap:'$210B',desc:'Global fast-food chain with 40K+ restaurants in 100+ countries'},
    'MDLZ': {name:'Mondelez',sector:'Consumer Staples',cap:'$90B',desc:'Snack foods (Oreo, Cadbury, Toblerone, Ritz) sold globally'},
    'MDT':  {name:'Medtronic',sector:'Medical Devices',cap:'$110B',desc:'Medical devices for cardiac, neurological, diabetes, and surgical care'},
    'MET':  {name:'MetLife',sector:'Insurance',cap:'$55B',desc:'Life insurance, annuities, employee benefits, and retirement solutions'},
    'MMM':  {name:'3M',sector:'Industrials',cap:'$70B',desc:'Diversified manufacturer of adhesives, abrasives, and healthcare products'},
    'MO':   {name:'Altria Group',sector:'Tobacco',cap:'$90B',desc:'Tobacco and nicotine products (Marlboro cigarettes, IQOS, on! pouches)'},
    'MS':   {name:'Morgan Stanley',sector:'Investment Banking',cap:'$190B',desc:'Investment banking, wealth management, trading, and institutional securities'},
    'NEE':  {name:'NextEra Energy',sector:'Utilities',cap:'$150B',desc:'Largest US renewable energy generator with wind and solar assets'},
    'NKE':  {name:'Nike',sector:'Consumer Discretionary',cap:'$100B',desc:'Athletic footwear, apparel, and equipment sold globally'},
    'PEP':  {name:'PepsiCo',sector:'Beverages / Snacks',cap:'$200B',desc:'Beverages (Pepsi, Gatorade) and snacks (Lays, Doritos, Quaker)'},
    'PM':   {name:'Philip Morris',sector:'Tobacco',cap:'$200B',desc:'International tobacco and reduced-risk products (IQOS heated tobacco)'},
    'PYPL': {name:'PayPal',sector:'Fintech',cap:'$70B',desc:'Digital payments platform for online transactions, Venmo, and Braintree'},
    'RTX':  {name:'RTX Corporation',sector:'Aerospace / Defense',cap:'$160B',desc:'Pratt & Whitney engines, Collins Aerospace, and Raytheon missile systems'},
    'SBUX': {name:'Starbucks',sector:'Restaurants',cap:'$100B',desc:'Global coffeehouse chain with 35K+ stores worldwide'},
    'SCHW': {name:'Charles Schwab',sector:'Financial Services',cap:'$130B',desc:'Brokerage, banking, and financial advisory services for retail investors'},
    'SO':   {name:'Southern Company',sector:'Utilities',cap:'$95B',desc:'Electric and gas utility serving southeastern US including Georgia Power'},
    'SPG':  {name:'Simon Property Group',sector:'REITs',cap:'$55B',desc:'Largest US shopping mall and premium outlet REIT'},
    'T':    {name:'AT&T',sector:'Telecom',cap:'$160B',desc:'Telecommunications providing wireless, broadband, and fiber services'},
    'TGT':  {name:'Target',sector:'Retail',cap:'$55B',desc:'General merchandise retail chain with grocery, apparel, and home goods'},
    'TMO':  {name:'Thermo Fisher Scientific',sector:'Life Sciences',cap:'$190B',desc:'Analytical instruments, reagents, and lab equipment for life sciences'},
    'TMUS': {name:'T-Mobile US',sector:'Telecom',cap:'$260B',desc:'Wireless carrier with nationwide 5G network and ~100M customers'},
    'UNP':  {name:'Union Pacific',sector:'Railroads',cap:'$150B',desc:'Largest US railroad operating 32K miles of track in western US'},
    'UPS':  {name:'UPS',sector:'Logistics',cap:'$100B',desc:'Global package delivery, freight, and supply chain management services'},
    'USB':  {name:'US Bancorp',sector:'Banking',cap:'$70B',desc:'Regional bank with consumer banking, wealth management, and payments'},
    'VZ':   {name:'Verizon',sector:'Telecom',cap:'$170B',desc:'Wireless telecommunications, broadband, and fiber optic services'},
    'WBA':  {name:'Walgreens Boots',sector:'Pharmacy',cap:'$10B',desc:'Pharmacy-led retail chain with healthcare clinics and wholesale distribution'},
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
    /* --- ETFs used by Catalyst + EFA strategies --- */
    'TLT':  {name:'iShares 20+ Year Treasury',sector:'Fixed Income ETF',cap:'ETF',desc:'Long-term US Treasury bond ETF tracking the ICE U.S. Treasury 20+ Year Bond Index'},
    'GLD':  {name:'SPDR Gold Shares',sector:'Commodities ETF',cap:'ETF',desc:'Gold bullion ETF backed by physical gold held in London vaults'},
    'DBC':  {name:'Invesco DB Commodity',sector:'Commodities ETF',cap:'ETF',desc:'Broad commodity ETF tracking energy, agriculture, precious and industrial metals'},
    'EFA':  {name:'iShares MSCI EAFE',sector:'International ETF',cap:'ETF',desc:'International developed markets ETF covering Europe, Australasia, and Far East'},
    'SPY':  {name:'SPDR S&P 500',sector:'Index ETF',cap:'ETF',desc:'Largest S&P 500 index ETF tracking the 500 largest US companies'},
    /* --- Newer top-40 universe stocks --- */
    'PLTR': {name:'Palantir Technologies',sector:'Software / AI',cap:'$250B',desc:'Data analytics and AI platforms for government intelligence and commercial enterprises'},
    'HOOD': {name:'Robinhood Markets',sector:'Fintech',cap:'$45B',desc:'Commission-free trading platform for stocks, crypto, and options'},
    'COIN': {name:'Coinbase Global',sector:'Crypto',cap:'$65B',desc:'Largest US cryptocurrency exchange for trading, staking, and custody'},
    'APP':  {name:'AppLovin',sector:'Ad Tech',cap:'$120B',desc:'Mobile app monetization and marketing platform powered by AI'},
    'SMCI': {name:'Super Micro Computer',sector:'IT Hardware',cap:'$30B',desc:'High-performance server and storage solutions for AI, cloud, and data centers'},
    'UBER': {name:'Uber Technologies',sector:'Ride-Hailing',cap:'$170B',desc:'Ride-sharing, food delivery (Uber Eats), and freight logistics platform'},
    'GEV':  {name:'GE Vernova',sector:'Energy / Power',cap:'$90B',desc:'Power generation, wind turbines, and grid electrification solutions (GE spin-off)'},
    'CRWD': {name:'CrowdStrike',sector:'Cybersecurity',cap:'$90B',desc:'Cloud-native endpoint security and threat intelligence platform (Falcon)'},
};

/* ============ TOOLTIP HELPER ============ */
function buildTickerTipWrap(symbol, innerEl) {
    var ci = COMPANY_INFO[symbol];
    if (!ci) return innerEl;
    var wrap = document.createElement('span');
    wrap.className = 'ticker-tip-wrap';
    wrap.appendChild(innerEl);
    var tip = document.createElement('div');
    tip.className = 'ticker-tip';
    tip.innerHTML = '<div class="ticker-tip-name">' + ci.name + '</div>' +
        '<span class="ticker-tip-sector">' + ci.sector + '</span>' +
        '<div class="ticker-tip-cap">Market Cap: <b>' + ci.cap + '</b></div>' +
        '<div class="ticker-tip-desc">' + ci.desc + '</div>';
    wrap.appendChild(tip);
    return wrap;
}

function attachTickerTips(container) {
    container.querySelectorAll('.ticker-tip-wrap').forEach(function(wrap) {
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

/* ============ GLOBALS ============ */
const REFRESH_MS = 30000;
let countdownSec = 30;
let currentPositions = {};
let lastSuccessTime = null;
var lastPortfolioData = null;
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
    if (!isFinite(v)) return '\u2014';
    const neg = v < 0;
    const abs = Math.abs(v);
    let s;
    if (abs >= 1e6) s = (abs/1e6).toFixed(2) + 'M';
    else s = abs.toLocaleString('en-US', {minimumFractionDigits:0, maximumFractionDigits:0});
    return (neg ? '-$' : '$') + s;
}

function fmtPct(v) {
    if (v == null || isNaN(v)) return '--';
    if (!isFinite(v)) return '\u2014';
    return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
}

function colorCls(v) {
    if (v == null || isNaN(v) || !isFinite(v)) return 'c-dim';
    if (v > 0) return 'c-green';
    if (v < 0) return 'c-red';
    return 'c-dim';
}

function timeAgo(isoStr) {
    if (!isoStr || isNaN(new Date(isoStr).getTime())) return '\u2014';
    // Server timestamps are UTC but lack 'Z' suffix — append it to avoid
    // JS interpreting them as local time (causes negative diff in non-UTC zones)
    var s = isoStr;
    if (!s.endsWith('Z') && !/[+-]\d{2}:?\d{2}$/.test(s)) s += 'Z';
    const d = new Date(s);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 0) return 'just now';
    if (diff < 60) return Math.floor(diff) + 's ago';
    if (diff < 3600) return Math.floor(diff/60) + 'm ago';
    if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
    return Math.floor(diff/86400) + 'd ago';
}

function escHtml(s) {
    if (!s) return '';
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

const TOAST_TIMEOUT_MS = 5000;
const TOAST_DEDUPE_MS = 10000;
const TOAST_MAX_VISIBLE = 3;
const _recentToasts = new Map();

function getErrorMessage(err) {
    if (!err) return 'Error desconocido';
    if (typeof err === 'string') return err;
    if (err.message) return err.message;
    return String(err);
}

function dismissToast(toast, immediate) {
    if (!toast) return;
    if (toast._dismissed) return;
    toast._dismissed = true;
    if (toast._timeoutId) clearTimeout(toast._timeoutId);
    if (immediate) {
        toast.remove();
        return;
    }
    toast.classList.remove('toast-visible');
    toast.classList.add('toast-hiding');
    setTimeout(function() {
        toast.remove();
    }, 220);
}

function showToast(message, type) {
    if (!message) return;
    var now = Date.now();
    _recentToasts.forEach(function(ts, key) {
        if (now - ts > TOAST_DEDUPE_MS) _recentToasts.delete(key);
    });
    var toastType = type || 'info';
    var dedupeKey = toastType + ':' + message;
    var lastSeen = _recentToasts.get(dedupeKey);
    if (lastSeen && (now - lastSeen) < TOAST_DEDUPE_MS) return;
    _recentToasts.set(dedupeKey, now);

    var container = document.getElementById('toast-container');
    if (!container) return;
    while (container.children.length >= TOAST_MAX_VISIBLE) {
        dismissToast(container.firstElementChild, true);
    }

    var toast = document.createElement('div');
    toast.className = 'toast toast-' + toastType;
    toast.setAttribute('role', toastType === 'error' ? 'alert' : 'status');
    toast.innerHTML =
        '<div class="toast-copy">' +
            '<span class="toast-label">' + escHtml(toastType.toUpperCase()) + '</span>' +
            '<span class="toast-message">' + escHtml(message) + '</span>' +
        '</div>' +
        '<button class="toast-close" type="button" aria-label="Cerrar notificacion">&times;</button>';

    var closeBtn = toast.querySelector('.toast-close');
    if (closeBtn) {
        closeBtn.addEventListener('click', function() {
            dismissToast(toast);
        });
    }

    container.appendChild(toast);
    requestAnimationFrame(function() {
        toast.classList.add('toast-visible');
    });
    toast._timeoutId = setTimeout(function() {
        dismissToast(toast);
    }, TOAST_TIMEOUT_MS);
}

function showFetchError(section, err, type) {
    showToast('Error cargando ' + section + ': ' + getErrorMessage(err), type || 'error');
}

/* ============ UPDATE FUNCTIONS ============ */
function updateStatusBar(p) {
    const rt = document.getElementById('regime-tag');
    if (!rt) return;
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

    var rawTs = p.timestamp || '';
    if (rawTs && !rawTs.endsWith('Z') && !/[+-]\d{2}:?\d{2}$/.test(rawTs)) rawTs += 'Z';
    const ts = rawTs ? new Date(rawTs).toLocaleString() : '--';
    document.getElementById('upd-tooltip').innerHTML =
        t('tooltip-last-update') + ': ' + ts + '<br>' + t('tooltip-next-in') + ': ' + countdownSec + 's';
}

function updateStalePriceWarning(freshness) {
    var badge = document.getElementById('stale-price-warning');
    var banner = document.getElementById('data-freshness-banner');
    if (!badge || !banner) return;

    var status = freshness && freshness.status ? freshness.status : 'live';
    var ageSeconds = null;
    if (freshness && freshness.price_age_seconds != null && !isNaN(freshness.price_age_seconds)) {
        ageSeconds = freshness.price_age_seconds;
    }
    var mins = ageSeconds != null ? Math.max(1, Math.round(ageSeconds / 60)) : null;

    if (status === 'live') {
        badge.style.display = 'none';
        banner.style.display = 'none';
        return;
    }

    if (status === 'offline') {
        badge.textContent = 'Engine offline';
        badge.className = 'stale-data stale-data-offline';
        banner.className = 'data-freshness-banner data-freshness-banner-offline';
        banner.textContent = mins != null
            ? 'Datos desactualizados: engine inactivo. Ultima actualizacion hace ' + mins + ' min.'
            : 'Datos desactualizados: engine inactivo.';
    } else if (status === 'market_closed') {
        badge.textContent = 'Mercado cerrado';
        badge.className = 'stale-data stale-data-closed';
        banner.className = 'data-freshness-banner data-freshness-banner-closed';
        banner.textContent = 'Mercado cerrado \u2014 precios al ultimo cierre.';
    } else {
        badge.textContent = mins != null ? 'Precios ' + mins + 'm atrasados' : 'Precios atrasados';
        badge.className = 'stale-data';
        banner.className = 'data-freshness-banner data-freshness-banner-stale';
        banner.textContent = mins != null
            ? 'Datos desactualizados: precios con ' + mins + ' min de retraso.'
            : 'Datos desactualizados: sin confirmacion reciente de precios.';
    }

    badge.style.display = 'inline';
    banner.style.display = 'block';
}

function updatePreclose(preclose) {
    if (!preclose) return;
    const dot = document.getElementById('preclose-dot');
    const label = document.getElementById('preclose-label');
    const timeEl = document.getElementById('preclose-time');
    const seg = document.getElementById('preclose-seg-window');
    if (!dot || !label || !timeEl || !seg) return;

    timeEl.textContent = preclose.current_time_et + ' ET';

    switch (preclose.phase) {
        case 'waiting':
            dot.className = 'preclose-dot preclose-dot-waiting';
            label.textContent = t('hdr-waiting-signal');
            label.style.color = 'var(--text-tertiary)';
            seg.classList.remove('active');
            break;
        case 'window_open':
            dot.className = 'preclose-dot preclose-dot-window';
            label.textContent = t('hdr-preclose-open');
            label.style.color = 'var(--yellow)';
            seg.classList.add('active');
            break;
        case 'entries_done':
            dot.className = 'preclose-dot preclose-dot-done';
            label.textContent = t('hdr-moc-sent');
            label.style.color = 'var(--green)';
            seg.classList.add('active');
            break;
        default: /* market_closed */
            dot.className = 'preclose-dot preclose-dot-closed';
            label.textContent = t('hdr-market-closed');
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
    document.getElementById('card-invested').textContent = t('metric-invested') + ': ' + fmt$(p.invested);

    const dd = document.getElementById('card-drawdown');
    dd.textContent = fmtPct(p.drawdown);
    dd.className = 'metric-value ' + (p.drawdown > -5 ? 'c-green' : p.drawdown > -10 ? 'c-yellow' : 'c-red');
    document.getElementById('card-peak').textContent = t('metric-peak') + ': ' + fmt$(p.peak_value);

    document.getElementById('card-positions').textContent = p.num_positions + ' / ' + p.max_positions;
    var regimeLabel = p.regime === 'RISK_ON' ? 'Risk On' : 'Risk Off';
    var efaNote = p.num_positions > p.max_positions ? ' · ' + t('positions-efa-note') : '';
    document.getElementById('card-maxpos').textContent = regimeLabel + (p.in_protection ? ' | DD Scaling' : '') + efaNote;
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
        tag.textContent = t('regime-risk-on') + ' (' + p.max_positions + ' pos)';
        tag.style.cssText = 'background:var(--green-dim);color:var(--green);border:1px solid rgba(34,197,94,0.3)';
    } else if (score >= 0.50) {
        tag.textContent = t('regime-transition') + ' (' + p.max_positions + ' pos)';
        tag.style.cssText = 'background:var(--yellow-dim);color:var(--yellow);border:1px solid rgba(234,179,8,0.3)';
    } else if (score >= 0.35) {
        tag.textContent = t('regime-caution') + ' (' + p.max_positions + ' pos)';
        tag.style.cssText = 'background:var(--yellow-dim);color:var(--yellow);border:1px solid rgba(234,179,8,0.3)';
    } else {
        tag.textContent = t('regime-risk-off') + ' (' + p.max_positions + ' pos)';
        tag.style.cssText = 'background:var(--red-dim);color:var(--red);border:1px solid rgba(239,68,68,0.3)';
    }
}


function _fillAlpha(alphaEl, alphaLabel, hydraRet, spyRet) {
    if (spyRet != null && hydraRet != null) {
        var diff = hydraRet - spyRet;
        var absDiff = Math.abs(diff).toFixed(2);
        if (diff >= 0) {
            alphaEl.textContent = '+' + absDiff + ' pp';
            alphaEl.className = 'perf-vs-alpha c-green';
            alphaLabel.textContent = t('perf-beating');
            alphaLabel.style.color = 'var(--green)';
        } else {
            alphaEl.textContent = '-' + absDiff + ' pp';
            alphaEl.className = 'perf-vs-alpha c-red';
            alphaLabel.textContent = t('perf-behind');
            alphaLabel.style.color = 'var(--red)';
        }
    } else {
        alphaEl.textContent = '--';
        alphaEl.className = 'perf-vs-alpha';
        alphaLabel.textContent = t('perf-vs');
        alphaLabel.style.color = '';
    }
}

function updatePerfBanner(p) {
    /* === ROW 1: DAILY (resets to 0% each morning) === */
    var dailyReturn = p.daily_return != null ? p.daily_return : 0;
    var hydraVal = document.getElementById('perf-hydra-val');
    hydraVal.textContent = fmtPct(dailyReturn);
    hydraVal.className = 'perf-side-value ' + colorCls(dailyReturn);
    document.getElementById('perf-hydra-sub').textContent = fmt$(p.portfolio_value);

    var spyDaily = p.spy_daily_return;
    var spyVal = document.getElementById('perf-spy-val');
    if (spyDaily != null) {
        spyVal.textContent = fmtPct(spyDaily);
        spyVal.className = 'perf-side-value ' + colorCls(spyDaily);
        var spyDollarChg = p.initial_capital * spyDaily / 100;
        document.getElementById('perf-spy-sub').textContent =
            (spyDollarChg >= 0 ? '+' : '') + fmt$(spyDollarChg);
    } else {
        spyVal.textContent = '--';
        spyVal.className = 'perf-side-value';
    }

    _fillAlpha(
        document.getElementById('perf-alpha'),
        document.getElementById('perf-alpha-label'),
        dailyReturn, spyDaily
    );

    /* === ROW 2: CUMULATIVE (since inception) === */
    var cumReturn = p.total_return != null ? p.total_return : 0;
    var spyCum = p.spy_cumulative;
    var cumVal = document.getElementById('perf-hydra-cum');
    if (cumVal) {
        cumVal.textContent = fmtPct(cumReturn);
        cumVal.className = 'perf-side-value ' + colorCls(cumReturn);
        var cumPortfolio = p.initial_capital * (1 + cumReturn / 100);
        document.getElementById('perf-hydra-cum-sub').textContent =
            '$' + p.initial_capital.toLocaleString() + ' \u2192 ' + fmt$(cumPortfolio);
    }

    var spyCumVal = document.getElementById('perf-spy-cum');
    if (spyCumVal) {
        if (spyCum != null) {
            spyCumVal.textContent = fmtPct(spyCum);
            spyCumVal.className = 'perf-side-value ' + colorCls(spyCum);
            var spyCumPortfolio = p.initial_capital * (1 + spyCum / 100);
            document.getElementById('perf-spy-cum-sub').textContent =
                '$' + p.initial_capital.toLocaleString() + ' \u2192 ' + fmt$(spyCumPortfolio);
        } else {
            spyCumVal.textContent = '--';
            spyCumVal.className = 'perf-side-value';
        }
    }

    var alphaCumEl = document.getElementById('perf-alpha-cum');
    if (alphaCumEl) {
        _fillAlpha(alphaCumEl, document.getElementById('perf-alpha-cum-label'), cumReturn, spyCum);
    }

    /* Period label */
    if (p.last_trading_date) {
        var days = p.trading_day || '?';
        document.getElementById('perf-period').textContent =
            t('live-test-prefix') + ' \u00B7 ' + t('day-label') + ' ' + days + ' \u00B7 ' + t('start-label') + ' Mar 16, 2026';
    }
}


function updatePositions(details) {
    const grid = document.getElementById('positions-grid');
    const totalBar = document.getElementById('positions-total-bar');
    currentPositions = {};

    if (!details || details.length === 0) {
        grid.innerHTML = '<div class="positions-empty"><div class="positions-empty-icon">&#9671;</div>' + t('strat-no-positions') + '</div>';
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
    const holdDays = 5; /* HYDRA hold period */

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
                '<div class="pos-datum"><span class="pos-datum-label">Shares</span><span class="pos-datum-value">' + Math.round(p.shares) + '</span></div>' +
            '</div>' +
            /* Row 2: Entry, Chg$, High */
            '<div class="pos-data-row">' +
                '<div class="pos-datum"><span class="pos-datum-label">Entry</span><span class="pos-datum-value">$' + p.entry_price.toFixed(2) + '</span></div>' +
                '<div class="pos-datum"><span class="pos-datum-label">' + t('pos-today') + '</span><span class="pos-datum-value ' + colorCls(priceChange) + '">' + priceChangeSign + '$' + Math.abs(priceChange).toFixed(2) + '</span></div>' +
                '<div class="pos-datum"><span class="pos-datum-label">High</span><span class="pos-datum-value">$' + (p.high_price || 0).toFixed(2) + '</span></div>' +
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
                    '<span class="pos-stop-val">$' + (p.position_stop_level || 0).toFixed(2) + '</span>' +
                '</div>' +
                trailHtml +
                (p.sector ? '<div class="pos-stop-item"><span class="pos-stop-dot" style="background:var(--purple);"></span><span class="pos-stop-label">' + escHtml(p.sector) + '</span></div>' : '') +
                (p.near_stop ? '<span style="margin-left:auto; font-size:11px; font-weight:700; color:var(--yellow); letter-spacing:0.5px;">' + t('near-stop') + '</span>' : '') +
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
    document.querySelectorAll('body > .ticker-tip').forEach(function(el) { el.remove(); });
    attachTickerTips(grid);

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
    document.getElementById('pt-count').textContent = details.length + (details.length !== 1 ? ' ' + t('position-plural') : ' ' + t('position-singular'));
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

    /* Collapsible behavior: collapsed when empty, expanded when has positions */
    if (rHero) {
        rHero.classList.add('rattle-collapsible');
        if (rPositions.length === 0) {
            if (!rHero._userToggled) rHero.classList.add('rattle-collapsed');
        } else {
            rHero.classList.remove('rattle-collapsed');
        }
        if (!rHero._clickBound) {
            rHero._clickBound = true;
            rHero.querySelector('.positions-hero-header').addEventListener('click', function() {
                rHero._userToggled = true;
                rHero.classList.toggle('rattle-collapsed');
            });
        }
    }
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
            var textNode = document.createTextNode(t('no-rattle-positions'));
            emptyDiv.appendChild(textNode);
            var subDiv = document.createElement('div');
            subDiv.style.cssText = 'font-size:11px;color:var(--text-tertiary);margin-top:4px;';
            subDiv.textContent = t('strat-rattle-waiting');
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
                top.appendChild(buildTickerTipWrap(rp.symbol, symSpan));
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
            attachTickerTips(rGrid);
        }
    }

    /* Capital allocation bar */
    var cap = hydra.capital;
    var allocBand = document.getElementById('hydra-alloc-band');
    if (cap && allocBand) {
        allocBand.style.display = 'flex';
        var cPct = (cap.hydra_pct || 0.5) * 100;
        var rPct = (cap.rattle_pct || 0.5) * 100;
        var ePct = (cap.efa_pct || 0) * 100;
        var catPct = (cap.catalyst_pct || 0) * 100;
        document.getElementById('hydra-bar-momentum').style.width = cPct + '%';
        document.getElementById('hydra-bar-rattle').style.width = rPct + '%';
        document.getElementById('hydra-bar-catalyst').style.width = catPct + '%';
        document.getElementById('hydra-bar-efa').style.width = ePct + '%';
        document.getElementById('hydra-m-pct').textContent = cPct.toFixed(0) + '%';
        document.getElementById('hydra-r-pct').textContent = rPct.toFixed(0) + '%';
        document.getElementById('hydra-cat-pct').textContent = catPct.toFixed(0) + '%';
        document.getElementById('hydra-e-pct').textContent = ePct.toFixed(0) + '%';
        document.getElementById('hydra-m-val').textContent = fmt$(cap.hydra_account || 0);
        document.getElementById('hydra-r-val').textContent = fmt$(cap.rattle_account || 0);
        document.getElementById('hydra-cat-val').textContent = fmt$(cap.catalyst_account || 0);
        document.getElementById('hydra-e-val').textContent = fmt$(cap.efa_value || 0);
        var recycled = cap.recycled_pct || 0;
        document.getElementById('hydra-recycled').textContent = (recycled * 100).toFixed(0) + '% recycled';
        var tag = document.getElementById('hydra-tag');
        if (recycled > 0) {
            tag.textContent = t('recycling-active');
            tag.style.cssText = 'color:var(--cyan); background:var(--cyan-dim);';
        } else {
            tag.textContent = t('no-recycling');
            tag.style.cssText = 'color:var(--text-muted); background:var(--bg-tertiary);';
        }
    }

    /* Catalyst positions */
    var catHero = document.getElementById('catalyst-positions-hero');
    if (catHero) {
        var cPositions = hydra.catalyst_positions || [];
        if (cPositions.length > 0 || hydra.available) {
            catHero.style.display = 'block';
        }

        document.getElementById('ch-count').textContent = cPositions.length;

        /* Count trend vs gold */
        var trendCount = 0, goldCount = 0;
        for (var ci = 0; ci < cPositions.length; ci++) {
            var sub = cPositions[ci].sub_strategy || '';
            if (sub.indexOf('gold') >= 0) goldCount++;
            if (sub.indexOf('trend') >= 0) trendCount++;
        }
        document.getElementById('ch-trend').textContent = trendCount + ' assets';
        document.getElementById('ch-trend').style.color = trendCount > 0 ? 'var(--green)' : 'var(--text-muted)';
        var goldEl = document.getElementById('ch-gold');
        goldEl.textContent = goldCount > 0 ? 'GLD' : '--';

        /* Collapsible */
        catHero.classList.add('rattle-collapsible');
        if (cPositions.length === 0) {
            if (!catHero._userToggled) catHero.classList.add('rattle-collapsed');
        } else {
            catHero.classList.remove('rattle-collapsed');
        }
        if (!catHero._clickBound) {
            catHero._clickBound = true;
            catHero.querySelector('.positions-hero-header').addEventListener('click', function() {
                catHero._userToggled = true;
                catHero.classList.toggle('rattle-collapsed');
            });
        }

        var catGrid = document.getElementById('catalyst-grid');
        if (catGrid) {
            catGrid.textContent = '';
            if (cPositions.length === 0) {
                var emptyDiv = document.createElement('div');
                emptyDiv.className = 'positions-empty';
                emptyDiv.style.gridColumn = '1 / -1';
                emptyDiv.textContent = t('no-catalyst-positions') || 'Catalyst positions will appear after first rebalance';
                catGrid.appendChild(emptyDiv);
            } else {
                for (var ci = 0; ci < cPositions.length; ci++) {
                    var cp = cPositions[ci];
                    var cpPnl = cp.pnl_pct || 0;
                    var cpUp = cpPnl >= 0;
                    var card = document.createElement('div');
                    card.className = 'pos-card ' + (cpUp ? 'pos-profit' : 'pos-loss');
                    card.style.borderTop = '2px solid var(--green)';

                    var top = document.createElement('div');
                    top.className = 'pos-top';
                    var sym = document.createElement('span');
                    sym.className = 'pos-symbol';
                    sym.textContent = cp.symbol;
                    top.appendChild(buildTickerTipWrap(cp.symbol, sym));
                    var tag = document.createElement('span');
                    tag.style.cssText = 'font-size:10px;color:var(--green);font-weight:600;margin-left:4px;padding:1px 4px;border-radius:3px;background:rgba(21,128,61,0.12);';
                    tag.textContent = (cp.sub_strategy || 'T').charAt(0).toUpperCase();
                    top.appendChild(tag);
                    var priceSpan = document.createElement('span');
                    priceSpan.style.cssText = 'font-size:15px;font-weight:700;color:var(--text-primary);font-family:var(--font-mono,monospace);margin-left:auto;margin-right:6px;';
                    priceSpan.textContent = '$' + (cp.current_price || 0).toFixed(2);
                    top.appendChild(priceSpan);
                    var badge = document.createElement('span');
                    badge.className = 'pos-pnl-badge ' + (cpUp ? 'pnl-up' : 'pnl-dn');
                    badge.textContent = fmtPct(cpPnl);
                    top.appendChild(badge);
                    card.appendChild(top);
                    catGrid.appendChild(card);
                }
                attachTickerTips(catGrid);
            }
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
        grid.innerHTML = '<span class="c-dim" style="font-size:12px;">' + t('no-universe') + '</span>';
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

    document.querySelectorAll('body > .ticker-tip').forEach(function(el) { el.remove(); });
    attachTickerTips(grid);
}






/* ============ CYCLE LOG ============ */
function fmtCyclePp(v) {
    if (v == null || isNaN(v)) return '--';
    return (v >= 0 ? '+' : '') + v.toFixed(2) + ' pp';
}

function cycleExitLabel(reason) {
    const labels = {
        position_stop: 'Stop loss',
        trailing_stop: 'Trailing',
        hold_expired: 'Rotación',
        universe_rotation: 'Rotación',
        carried_forward: 'Sigue activo',
    };
    if (!reason) return '--';
    return labels[reason] || reason.replace(/_/g, ' ');
}

function cycleReasonLabel(reason) {
    const labels = {
        stop_loss: 'stop',
        rotation: 'rotación',
        trailing: 'trailing',
    };
    if (!reason) return '--';
    return labels[reason] || reason.replace(/_/g, ' ');
}

function renderCycleReasonPills(exitsByReason) {
    if (!exitsByReason || typeof exitsByReason !== 'object') return '';
    const orderedKeys = ['stop_loss', 'rotation', 'trailing'];
    const extraKeys = Object.keys(exitsByReason).filter(function(key) {
        return orderedKeys.indexOf(key) === -1;
    });
    const keys = orderedKeys.concat(extraKeys).filter(function(key) {
        return exitsByReason[key];
    });
    if (!keys.length) return '';

    const pills = keys.map(function(key) {
        return '<span class="cl-reason-pill cl-reason-' + escHtml(key) + '">'
            + escHtml(String(exitsByReason[key])) + 'x ' + escHtml(cycleReasonLabel(key))
            + '</span>';
    });
    return '<div class="cl-reason-pills">' + pills.join('') + '</div>';
}

function renderCycleAlphaBadge(alphaPp) {
    if (alphaPp == null) return '';
    const cls = alphaPp > 0 ? 'cl-alpha-pos' : alphaPp < 0 ? 'cl-alpha-neg' : 'cl-alpha-flat';
    return '<div class="cl-alpha-box">'
        + '<span class="cl-alpha-label">Alpha vs S&amp;P</span>'
        + '<span class="cl-alpha-badge ' + cls + '">' + fmtCyclePp(alphaPp) + '</span>'
        + '</div>';
}

function renderCyclePositionsDetail(details) {
    if (!Array.isArray(details) || !details.length) return '';

    const rows = details.map(function(detail) {
        const pnl = detail && detail.pnl_pct != null ? detail.pnl_pct : null;
        const pnlCls = pnl > 0 ? 'cl-pos' : pnl < 0 ? 'cl-neg' : '';
        const exitCls = pnl > 0 ? 'cl-detail-exit-pos' : pnl < 0 ? 'cl-detail-exit-neg' : 'cl-detail-exit-flat';
        return '<tr>'
            + '<td class="cl-detail-symbol">' + escHtml(detail.symbol || '--') + '</td>'
            + '<td class="cl-detail-pnl ' + pnlCls + '">' + fmtPct(pnl) + '</td>'
            + '<td><span class="cl-detail-exit ' + exitCls + '">' + escHtml(cycleExitLabel(detail.exit_reason)) + '</span></td>'
            + '</tr>';
    });

    return '<div class="cl-detail-block">'
        + '<div class="cl-detail-title">Detalle</div>'
        + '<div class="cl-detail-table-wrap">'
        + '<table class="cl-detail-table">'
        + '<thead><tr><th>Ticker</th><th>P&amp;L</th><th>Razón de salida</th></tr></thead>'
        + '<tbody>' + rows.join('') + '</tbody>'
        + '</table>'
        + '</div>'
        + '</div>';
}

async function fetchCycleLog() {
    try {
        const res = await fetch('/api/cycle-log');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const cycles = await res.json();
        const tbody = document.getElementById('cycle-log-body');
        if (!tbody || !cycles.length) {
            if (tbody) tbody.innerHTML = '<tr><td colspan="7" style="color:var(--text-muted);text-align:center;">' + t('ml-no-cycles') + '</td></tr>';
            return;
        }
        let html = '';
        for (const c of cycles) {
            const isActive = c.status === 'active';
            const hydra = c.hydra_return != null ? (c.hydra_return >= 0 ? '+' : '') + c.hydra_return.toFixed(2) + '%' : '--';
            const spy = c.spy_return != null ? (c.spy_return >= 0 ? '+' : '') + c.spy_return.toFixed(2) + '%' : '--';
            const alpha = c.alpha != null ? (c.alpha >= 0 ? '+' : '') + c.alpha.toFixed(2) + ' pp' : '--';
            const hydraCls = c.hydra_return > 0 ? 'cl-pos' : c.hydra_return < 0 ? 'cl-neg' : '';
            const spyCls = c.spy_return > 0 ? 'cl-pos' : c.spy_return < 0 ? 'cl-neg' : '';
            const alphaCls = c.alpha > 0 ? 'cl-pos' : c.alpha < 0 ? 'cl-neg' : '';
            const period = c.end_date ? c.start_date + ' → ' + c.end_date : c.start_date + ' → ...';
            const alphaBadge = renderCycleAlphaBadge(c.alpha_pct != null ? c.alpha_pct : c.alpha);
            const reasonPills = renderCycleReasonPills(c.exits_by_reason);
            const detailTable = renderCyclePositionsDetail(c.positions_detail);
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
                    parts.push(escHtml(displayPositions[ti]));
                }
                // Show stopped tickers as strikethrough prefix
                var stoppedParts = [];
                for (var si = 0; si < stops.length; si++) {
                    var s = stops[si];
                    var label = '<s style="opacity:.5">' + escHtml(s.stopped) + '</s>';
                    if (s.replacement) label += '→<s style="opacity:.5">' + escHtml(s.replacement) + '</s>';
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
                '<td class="cl-tickers">'
                    + '<div class="cl-cycle-tickers">' + tickers + '</div>'
                    + '<div class="cl-cycle-meta-row">' + alphaBadge + reasonPills + '</div>'
                    + detailTable
                    + '</td>' +
                '<td class="cl-num ' + hydraCls + '">' + hydra + '</td>' +
                '<td class="cl-num ' + spyCls + '">' + spy + '</td>' +
                '<td class="cl-num ' + alphaCls + '">' + alpha + '</td>' +
                '<td>' + status + '</td>' +
                '</tr>';
        }
        tbody.innerHTML = html;
    } catch (e) {
        console.error('Cycle log error:', e);
        showFetchError('ciclo de rotacion', e);
        const tbody = document.getElementById('cycle-log-body');
        if (tbody) tbody.innerHTML = '<tr><td colspan="7" style="color:var(--red);text-align:center;">' + t('cl-error-text') + '</td></tr>';
    }
}

/* ============ FETCH & REFRESH ============ */
let _fetchRetries = 0;
const MAX_RETRIES = 5;
const RETRY_DELAYS = [3000, 5000, 8000, 12000, 20000];
const STARTING_RETRY_MS = 5000;
let _startupRetryTimer = null;

function showStartupLoading(message) {
    const loading = document.getElementById('startup-loading');
    const messageEl = document.getElementById('startup-loading-message');
    if (!loading || !messageEl) return;
    messageEl.textContent = (message || 'HYDRA iniciando...') + ' Reintentando en 5s.';
    loading.hidden = false;
}

function hideStartupLoading() {
    const loading = document.getElementById('startup-loading');
    if (loading) loading.hidden = true;
}

function scheduleStartupRetry() {
    if (_startupRetryTimer) return;
    _startupRetryTimer = setTimeout(function() {
        _startupRetryTimer = null;
        fetchAll();
    }, STARTING_RETRY_MS);
}

function clearStartupRetry() {
    if (!_startupRetryTimer) return;
    clearTimeout(_startupRetryTimer);
    _startupRetryTimer = null;
}

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
        priceEl.textContent = idxPrice.toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0});
        var idxPrev = pc['^GSPC'] || pc['GSPC'];
        if (idxPrev && idxPrev > 0) {
            var chg = ((idxPrice - idxPrev) / idxPrev) * 100;
            if (chg > 0) {
                chgEl.textContent = '+' + chg.toFixed(2) + '%';
                chgEl.style.color = 'var(--green)';
            } else if (chg < -0.001) {
                chgEl.textContent = chg.toFixed(2) + '%';
                chgEl.style.color = 'var(--red)';
            } else {
                chgEl.textContent = '0.00%';
                chgEl.style.color = 'var(--text-secondary)';
            }
        }
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
        const stateRes = await fetch('/api/state', {cache: 'no-store'});
        if (!stateRes.ok) throw new Error('HTTP ' + stateRes.status);
        const stateData = await stateRes.json();

        if (stateData.status === 'starting') {
            _fetchRetries = 0;
            clearStartupRetry();
            document.getElementById('offline-banner').style.display = 'none';
            updateStalePriceWarning(null);
            showStartupLoading(stateData.message || 'HYDRA iniciando...');
            countdownSec = Math.ceil(STARTING_RETRY_MS / 1000);
            scheduleStartupRetry();
            return;
        }

        if (stateData.status === 'offline') {
            hideStartupLoading();
            clearStartupRetry();
            updateStalePriceWarning(null);
            const banner = document.getElementById('offline-banner');
            banner.style.display = 'block';
            banner.textContent = _fetchRetries > 0
                ? t('waking-server') + ' ' + _fetchRetries + '/' + MAX_RETRIES
                : t('offline-banner');
            if (_fetchRetries < MAX_RETRIES) {
                setTimeout(fetchAll, RETRY_DELAYS[_fetchRetries]);
                _fetchRetries++;
            }
        } else {
            hideStartupLoading();
            clearStartupRetry();
            _fetchRetries = 0;
            document.getElementById('offline-banner').style.display = 'none';
            lastSuccessTime = new Date().toISOString();
            lastPortfolioData = stateData;
            const p = stateData.portfolio;
            updateStatusBar(p);
            updateStalePriceWarning(stateData._data_freshness);
            updateCards(p);
            updateRegimeBand(p);
            updatePerfBanner(p);
            updatePreclose(stateData.preclose);
            updatePositions(stateData.position_details);
            renderP2PScatter(stateData.position_details);
            if (stateData.hydra) updateHydra(stateData.hydra);
            if (stateData.prices) updateSpyTracker(stateData.prices, stateData.prev_closes);
            const posDict = {};
            if (stateData.position_details) {
                for (const pd of stateData.position_details) posDict[pd.symbol] = true;
            }
            updateUniverse(stateData.universe, posDict);

            // Overlay status (awaited to prevent race conditions on rapid fetchAll calls)
            try {
                const ovRes = await fetch('/api/overlay-status');
                if (ovRes.ok) {
                    const d = await ovRes.json();
                    if (!d.available) {
                        const ovScalar = document.getElementById('ov-scalar');
                        const ovTag = document.getElementById('ov-tag');
                        if (ovScalar) ovScalar.textContent = 'OFF';
                        if (ovTag) { ovTag.textContent = 'Unavailable'; ovTag.className = 'regime-band-tag'; }
                    } else {
                        const scalar = d.capital_scalar;
                        const ovScalar = document.getElementById('ov-scalar');
                        if (ovScalar) ovScalar.textContent = scalar != null ? scalar.toFixed(2) : '--';

                        const tag = document.getElementById('ov-tag');
                        if (tag) {
                            tag.textContent = d.scalar_label;
                            tag.className = 'regime-band-tag';
                            if (d.scalar_color === 'green') tag.style.cssText = 'color:var(--green); background:var(--green-dim);';
                            else if (d.scalar_color === 'yellow') tag.style.cssText = 'color:var(--yellow); background:var(--yellow-dim);';
                            else tag.style.cssText = 'color:var(--red); background:var(--red-dim);';
                        }

                        const colorVal = v => v >= 0.90 ? 'var(--green)' : v >= 0.60 ? 'var(--yellow)' : 'var(--red)';
                        if (d.per_overlay && d.credit_filter) {
                            const bso = d.per_overlay.bso;
                            const m2 = d.per_overlay.m2;
                            const fomc = d.per_overlay.fomc;

                            const bsoEl = document.getElementById('ov-bso');
                            if (bsoEl && bso != null) { bsoEl.textContent = bso.toFixed(2); bsoEl.style.color = colorVal(bso); }

                            const m2El = document.getElementById('ov-m2');
                            if (m2El && m2 != null) { m2El.textContent = m2.toFixed(2); m2El.style.color = colorVal(m2); }

                            const fomcEl = document.getElementById('ov-fomc');
                            if (fomcEl && fomc != null) { fomcEl.textContent = fomc.toFixed(2); fomcEl.style.color = colorVal(fomc); }

                            const fedEl = document.getElementById('ov-fed');
                            if (fedEl) { fedEl.textContent = d.fed_emergency_active ? 'ACTIVE' : 'Inactive'; fedEl.style.color = d.fed_emergency_active ? 'var(--red)' : 'var(--text-muted)'; }

                            const creditEl = document.getElementById('ov-credit');
                            if (creditEl) {
                                const excluded = d.credit_filter.excluded_sectors;
                                if (excluded && excluded.length > 0) {
                                    creditEl.textContent = excluded.join(', ');
                                    creditEl.style.color = 'var(--red)';
                                } else {
                                    creditEl.textContent = 'Clear';
                                    creditEl.style.color = 'var(--green)';
                                }
                            }
                        }
                    }
                }
            } catch (ovErr) {
                console.warn('Overlay status fetch failed:', ovErr.message);
                showFetchError('macro overlay', ovErr, 'warning');
            }
        }
    } catch (err) {
        console.error('Fetch error:', err);
        showFetchError('dashboard principal', err);
        hideStartupLoading();
        clearStartupRetry();
        const banner = document.getElementById('offline-banner');
        if (banner) {
            banner.style.display = 'block';
            banner.textContent = _fetchRetries > 0
                ? t('waking-server') + ' ' + _fetchRetries + '/' + MAX_RETRIES
                : t('offline-banner');
        }
        if (_fetchRetries < MAX_RETRIES) {
            setTimeout(fetchAll, RETRY_DELAYS[_fetchRetries]);
            _fetchRetries++;
        }
    }
}

let _mcChart = null;

async function fetchMonteCarlo() {
    try {
        const res = await fetch('/api/montecarlo');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        renderMonteCarloPanel(data);
    } catch (e) {
        console.error('Monte Carlo fetch failed:', e);
        showFetchError('Monte Carlo', e);
        const badge = document.getElementById('mc-badge');
        if (badge) {
            badge.textContent = t('mc-error-badge');
            badge.style.color = 'var(--red)';
            badge.style.background = 'var(--red-dim)';
        }
    }
}

function renderMonteCarloPanel(data) {
    const badge = document.getElementById('mc-badge');
    const summary = data.summary || {};
    const historical = data.historical_stats || {};
    if (badge) {
        const liveSource = data.source === 'live_cycle_log';
        const sampleSize = (data.historical_stats || {}).sample_size || 0;
        const sampleSuffix = liveSource && sampleSize > 0 && sampleSize < 30
            ? ' (' + sampleSize + ' ciclos)' : '';
        badge.textContent = (liveSource ? t('mc-source-live') : t('mc-source-backtest')) + sampleSuffix;
        badge.style.color = liveSource ? 'var(--green)' : 'var(--yellow)';
        badge.style.background = liveSource ? 'var(--green-dim)' : 'var(--yellow-dim)';
    }

    const medianEl = document.getElementById('mc-median-return');
    const rangeEl = document.getElementById('mc-outcome-range');
    const gainEl = document.getElementById('mc-prob-gain');
    const ddEl = document.getElementById('mc-prob-dd');
    if (medianEl) {
        medianEl.textContent = fmtPct(summary.median_return_pct || 0);
        medianEl.style.color = (summary.median_return_pct || 0) >= 0 ? 'var(--green)' : 'var(--red)';
    }
    if (rangeEl) {
        rangeEl.textContent = fmt$(summary.p5_outcome || 0) + ' / ' + fmt$(summary.p95_outcome || 0);
    }
    if (gainEl) {
        gainEl.textContent = (summary.prob_gain_10_pct || 0).toFixed(1) + '%';
        gainEl.style.color = (summary.prob_gain_10_pct || 0) >= 50 ? 'var(--green)' : 'var(--yellow)';
    }
    if (ddEl) {
        ddEl.textContent = (summary.prob_drawdown_better_than_20_pct || 0).toFixed(1) + '%';
        ddEl.style.color = (summary.prob_drawdown_better_than_20_pct || 0) >= 60 ? 'var(--green)' : 'var(--yellow)';
        ddEl.title = (historical.sample_size || 0) + ' ciclos base · seed ' + (data.seed || 666);
    }

    renderMonteCarloChart(data.fan_chart || {});
}

function renderMonteCarloChart(fan) {
    const canvas = document.getElementById('mcFanChart');
    if (!canvas || typeof Chart === 'undefined' || !fan.days || fan.days.length === 0) return;

    if (_mcChart) {
        _mcChart.destroy();
        _mcChart = null;
    }

    var initialVal = fan.p50[0] || 100000;
    var finalP50 = fan.p50[fan.p50.length - 1];
    var finalP5 = fan.p5[fan.p5.length - 1];
    var finalP95 = fan.p95[fan.p95.length - 1];
    var p10 = fan.p10 || fan.p25;
    var p90 = fan.p90 || fan.p75;

    /* Compact dollar format for annotations: $115.3K */
    var fmtCompact = function(v) {
        if (v >= 1e6) return '$' + (v / 1e6).toFixed(1) + 'M';
        if (v >= 1e3) return '$' + (v / 1e3).toFixed(1) + 'K';
        return '$' + Math.round(v);
    };

    var ctx = canvas.getContext('2d');

    /* Gradient for the P25-P75 core band */
    var coreGrad = ctx.createLinearGradient(0, 0, 0, canvas.parentElement.clientHeight || 280);
    coreGrad.addColorStop(0, 'rgba(34, 197, 94, 0.28)');
    coreGrad.addColorStop(1, 'rgba(34, 197, 94, 0.04)');

    /* Gradient for the P10-P90 mid band */
    var midGrad = ctx.createLinearGradient(0, 0, 0, canvas.parentElement.clientHeight || 280);
    midGrad.addColorStop(0, 'rgba(34, 197, 94, 0.14)');
    midGrad.addColorStop(1, 'rgba(34, 197, 94, 0.02)');

    /* Build month labels from day numbers */
    var dayToMonth = function(day) {
        var m = Math.round(day / 21);
        if (m === 0) return t('mc-start-label') || 'Inicio';
        return m + (m === 1 ? ' mes' : ' meses');
    };

    /* Annotation lines */
    var annotations = {
        breakeven: {
            type: 'line', yMin: initialVal, yMax: initialVal,
            borderColor: 'rgba(255, 255, 255, 0.2)', borderWidth: 1,
            borderDash: [6, 4],
            label: {
                display: true, content: 'Break-even',
                position: 'start', color: 'rgba(255,255,255,0.4)',
                backgroundColor: 'transparent', font: { size: 10 },
            },
        },
        target10: {
            type: 'line', yMin: initialVal * 1.10, yMax: initialVal * 1.10,
            borderColor: 'rgba(34, 197, 94, 0.2)', borderWidth: 1,
            borderDash: [4, 6],
            label: {
                display: true, content: '+10%',
                position: 'start', color: 'rgba(34, 197, 94, 0.5)',
                backgroundColor: 'transparent', font: { size: 10 },
            },
        },
        target20: {
            type: 'line', yMin: initialVal * 1.20, yMax: initialVal * 1.20,
            borderColor: 'rgba(34, 197, 94, 0.15)', borderWidth: 1,
            borderDash: [4, 6],
            label: {
                display: true, content: '+20%',
                position: 'start', color: 'rgba(34, 197, 94, 0.4)',
                backgroundColor: 'transparent', font: { size: 10 },
            },
        },
        finalP50: {
            type: 'label',
            xValue: fan.days.length - 1, yValue: finalP50,
            content: fmtCompact(finalP50), color: '#22c55e',
            backgroundColor: 'rgba(0,0,0,0.6)', borderRadius: 4,
            font: { size: 11, weight: 'bold', family: "'JetBrains Mono', monospace" },
            padding: { top: 3, bottom: 3, left: 6, right: 6 },
            position: { x: 'end' },
        },
        finalP95: {
            type: 'label',
            xValue: fan.days.length - 1, yValue: finalP95,
            content: fmtCompact(finalP95), color: 'rgba(34, 197, 94, 0.6)',
            backgroundColor: 'rgba(0,0,0,0.5)', borderRadius: 4,
            font: { size: 9, family: "'JetBrains Mono', monospace" },
            padding: { top: 2, bottom: 2, left: 4, right: 4 },
            position: { x: 'end' },
        },
        finalP5: {
            type: 'label',
            xValue: fan.days.length - 1, yValue: finalP5,
            content: fmtCompact(finalP5), color: 'rgba(239, 68, 68, 0.7)',
            backgroundColor: 'rgba(0,0,0,0.5)', borderRadius: 4,
            font: { size: 9, family: "'JetBrains Mono', monospace" },
            padding: { top: 2, bottom: 2, left: 4, right: 4 },
            position: { x: 'end' },
        },
    };

    _mcChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: fan.days,
            datasets: [
                /* Outer band: P95 (top boundary) */
                {
                    label: 'P95', data: fan.p95,
                    borderColor: 'rgba(34, 197, 94, 0.25)', borderWidth: 1,
                    borderDash: [3, 3], pointRadius: 0, fill: false,
                },
                /* P90 fills down to P95 → outermost top band */
                {
                    label: 'P90', data: p90,
                    borderColor: 'rgba(34, 197, 94, 0)', pointRadius: 0,
                    backgroundColor: 'rgba(34, 197, 94, 0.05)', fill: '-1',
                },
                /* P75 fills down to P90 → mid-upper band */
                {
                    label: 'P75', data: fan.p75,
                    borderColor: 'rgba(34, 197, 94, 0)', pointRadius: 0,
                    backgroundColor: midGrad, fill: '-1',
                },
                /* P25 fills up to P75 → core band */
                {
                    label: 'P25', data: fan.p25,
                    borderColor: 'rgba(34, 197, 94, 0)', pointRadius: 0,
                    backgroundColor: coreGrad, fill: '-1',
                },
                /* P10 fills down to P25 → mid-lower band */
                {
                    label: 'P10', data: p10,
                    borderColor: 'rgba(34, 197, 94, 0)', pointRadius: 0,
                    backgroundColor: midGrad, fill: '-1',
                },
                /* P5 fills down to P10 → outermost bottom band */
                {
                    label: 'P5', data: fan.p5,
                    borderColor: 'rgba(34, 197, 94, 0.25)', borderWidth: 1,
                    borderDash: [3, 3], pointRadius: 0,
                    backgroundColor: 'rgba(34, 197, 94, 0.05)', fill: '-1',
                },
                /* Median line (on top) */
                {
                    label: 'P50 (Mediana)', data: fan.p50,
                    borderColor: '#22c55e', backgroundColor: 'transparent',
                    borderWidth: 2.5, pointRadius: 0, tension: 0.2, fill: false,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            layout: { padding: { right: 80 } },
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: false },
                annotation: { annotations: annotations },
                tooltip: {
                    backgroundColor: 'rgba(15, 18, 30, 0.92)',
                    borderColor: 'rgba(34, 197, 94, 0.3)',
                    borderWidth: 1,
                    titleFont: { family: "'JetBrains Mono', monospace", size: 11 },
                    bodyFont: { family: "'JetBrains Mono', monospace", size: 11 },
                    padding: 10,
                    displayColors: false,
                    filter: function(item) {
                        return ['P5', 'P25', 'P50 (Mediana)', 'P75', 'P95'].indexOf(item.dataset.label) !== -1;
                    },
                    callbacks: {
                        title: function(items) {
                            var day = items[0].label;
                            return dayToMonth(day) + '  (' + t('mc-day-prefix') + ' ' + day + ')';
                        },
                        label: function(item) {
                            var pctChange = ((item.raw - initialVal) / initialVal * 100).toFixed(1);
                            var sign = pctChange >= 0 ? '+' : '';
                            return item.dataset.label + ':  ' + fmt$(item.raw) + '  (' + sign + pctChange + '%)';
                        },
                    },
                },
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255,255,255,0.04)' },
                    ticks: {
                        color: '#8f96ad',
                        maxRotation: 0,
                        autoSkip: false,
                        callback: function(value, index) {
                            var day = fan.days[index];
                            if (index === 0) return t('mc-start-label') || 'Hoy';
                            /* Show label at ~month boundaries (21 trading days/month).
                               With 5-day steps, closest points to month N are day 20,25,40,45...
                               Accept if within half a step of a month boundary. */
                            var step = fan.days.length > 1 ? fan.days[1] - fan.days[0] : 5;
                            var monthDay = Math.round(day / 21);
                            var remainder = Math.abs(day - monthDay * 21);
                            if (monthDay > 0 && monthDay <= 12 && remainder <= step / 2) return 'M' + monthDay;
                            return '';
                        },
                    },
                    title: { display: false },
                },
                y: {
                    grid: { color: 'rgba(255,255,255,0.04)' },
                    ticks: {
                        color: '#8f96ad',
                        callback: function(value) { return fmt$(value); },
                    },
                },
            },
        },
    });
}

function riskTone(score) {
    if (score < 30) return { cls: 'risk-low', color: 'var(--green)' };
    if (score < 60) return { cls: 'risk-moderate', color: 'var(--yellow)' };
    return { cls: score < 80 ? 'risk-high' : 'risk-extreme', color: 'var(--red)' };
}

function riskLabel(label) {
    if (label === 'LOW') return t('risk-low-label');
    if (label === 'MODERATE') return t('risk-moderate-label');
    if (label === 'HIGH') return t('risk-high-label');
    if (label === 'EXTREME') return t('risk-extreme-label');
    return '--';
}

function setRiskMetric(id, text, toneCls) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.className = 'risk-metric-value ' + toneCls;
}

function renderRiskPanel(data) {
    const gauge = document.getElementById('risk-gauge');
    const scoreEl = document.getElementById('risk-score');
    const labelEl = document.getElementById('risk-label');
    const badgeEl = document.getElementById('risk-badge');
    const captionEl = document.getElementById('risk-caption');
    if (!gauge || !scoreEl || !labelEl || !badgeEl || !captionEl) return;

    const score = Math.max(0, Math.min(100, Number(data.risk_score || 0)));
    const tone = riskTone(score);
    const label = riskLabel(data.risk_label);
    const sweep = Math.round(score * 3.6);

    gauge.style.background =
        'conic-gradient(' + tone.color + ' 0deg, ' + tone.color + ' ' + sweep +
        'deg, rgba(255,255,255,0.06) ' + sweep + 'deg 360deg)';
    scoreEl.textContent = score.toFixed(1);
    scoreEl.style.color = tone.color;
    labelEl.textContent = label;
    badgeEl.textContent = label;
    badgeEl.style.color = tone.color;
    badgeEl.style.background =
        tone.cls === 'risk-low' ? 'var(--green-dim)' :
        tone.cls === 'risk-moderate' ? 'var(--yellow-dim)' : 'var(--red-dim)';
    captionEl.textContent =
        (data.num_positions || 0) + ' ' + t('risk-positions-label') +
        ' · ' + (data.lookback_days || 30) + 'd';

    setRiskMetric('risk-concentration', fmtPct((data.concentration_risk || 0) * 100), tone.cls);
    setRiskMetric('risk-sector', fmtPct(data.sector_concentration || 0), tone.cls);
    setRiskMetric('risk-correlation', (data.correlation_risk || 0).toFixed(2), tone.cls);
    setRiskMetric(
        'risk-var',
        fmt$(data.var_95 || 0) + ' / ' + fmtPct(data.var_95_pct || 0),
        tone.cls
    );
    setRiskMetric('risk-maxpos', fmtPct(data.max_position_pct || 0), tone.cls);
    setRiskMetric('risk-beta', (data.beta || 0).toFixed(2), tone.cls);
}

async function fetchRiskData() {
    try {
        const res = await fetch('/api/risk');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        if (data.error && (data.num_positions || 0) === 0) {
            renderRiskPanel({
                risk_score: 0,
                risk_label: 'LOW',
                num_positions: 0,
                lookback_days: 30,
                concentration_risk: 0,
                sector_concentration: 0,
                correlation_risk: 0,
                var_95: 0,
                var_95_pct: 0,
                max_position_pct: 0,
                beta: 0,
            });
            return;
        }
        renderRiskPanel(data);
    } catch (e) {
        console.error('Risk fetch failed:', e);
        showFetchError('riesgo', e);
        var badge = document.getElementById('risk-badge');
        if (badge) {
            badge.textContent = t('risk-error-badge');
            badge.style.color = 'var(--red)';
            badge.style.background = 'var(--red-dim)';
        }
    }
}

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
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        if (data.error) {
            showToast('Error cargando analitica de trades: ' + data.error, 'error');
            document.getElementById('ta-table-container').innerHTML =
                '<div style="color:var(--red);font-size:12px;">Error: ' + escHtml(data.error) + '</div>';
            return;
        }
        taData = data;
        document.getElementById('ta-badge').textContent =
            (data.overall ? data.overall.total_trades.toLocaleString() + ' trades' : '--');
        renderTAButtons();
        renderTATable(taActiveSeg);
    } catch(e) {
        console.error('TA error:', e);
        showFetchError('analitica de trades', e);
        var badge = document.getElementById('ta-badge');
        if (badge) {
            badge.textContent = t('ta-error-badge');
            badge.style.color = 'var(--red)';
            badge.style.background = 'var(--red-dim)';
        }
        document.getElementById('ta-table-container').innerHTML =
            '<div style="color:var(--red);font-size:12px;">Failed to load: ' + escHtml(e.message) + '</div>';
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
        html += `<td style="color:var(--text-primary);font-weight:500;">${escHtml(cat)}</td>`;
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
        if (!res.ok) throw new Error('HTTP ' + res.status);
        var data = await res.json();
        if (!data.equity || data.equity.length === 0) return;
        renderEquityAndDrawdown(data.equity, data.milestones || []);
    } catch (e) {
        console.error('Equity fetch error:', e);
        showFetchError('curva de equity', e);
        var badge = document.getElementById('eq-badge');
        if (badge) {
            badge.textContent = t('eq-error-badge');
            badge.style.color = 'var(--red)';
            badge.style.background = 'var(--red-dim)';
        }
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

/* ============ P2P SCATTERPLOT ============ */
let _p2pChart = null;

const P2P_SECTOR_COLORS = {
    'Technology':         { bg: 'rgba(14,165,233,0.85)',  border: '#0ea5e9', glow: 'rgba(14,165,233,0.4)' },
    'Healthcare':         { bg: 'rgba(16,185,129,0.85)',  border: '#10b981', glow: 'rgba(16,185,129,0.4)' },
    'Semiconductors':     { bg: 'rgba(6,182,212,0.85)',   border: '#06b6d4', glow: 'rgba(6,182,212,0.4)' },
    'Financial Services': { bg: 'rgba(59,130,246,0.85)',  border: '#3b82f6', glow: 'rgba(59,130,246,0.4)' },
    'Banking':            { bg: 'rgba(14,165,233,0.85)',  border: '#0ea5e9', glow: 'rgba(14,165,233,0.4)' },
    'Energy':             { bg: 'rgba(234,88,12,0.85)',   border: '#ea580c', glow: 'rgba(234,88,12,0.4)' },
    'Retail':             { bg: 'rgba(236,72,153,0.85)',  border: '#ec4899', glow: 'rgba(236,72,153,0.4)' },
    'Software':           { bg: 'rgba(56,189,248,0.85)',  border: '#38bdf8', glow: 'rgba(56,189,248,0.4)' },
    'default':            { bg: 'rgba(148,163,184,0.85)', border: '#94a3b8', glow: 'rgba(148,163,184,0.4)' }
};

function getSectorColor(sector) {
    if (!sector) return P2P_SECTOR_COLORS['default'];
    for (var key in P2P_SECTOR_COLORS) {
        if (sector.toLowerCase().indexOf(key.toLowerCase()) !== -1) return P2P_SECTOR_COLORS[key];
    }
    return P2P_SECTOR_COLORS['default'];
}

function renderP2PScatter(positions) {
    var card = document.getElementById('p2p-scatter-card');
    if (!positions || positions.length === 0) {
        card.style.display = 'none';
        return;
    }
    card.style.display = '';

    var isDark = document.body.classList.contains('dark');
    var gridColor = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)';
    var zeroLineColor = isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.12)';
    var labelColor = isDark ? '#a0a0b8' : '#555570';
    var tooltipBg = isDark ? 'rgba(22,22,50,0.95)' : 'rgba(255,255,255,0.97)';
    var tooltipText = isDark ? '#e4e4f0' : '#1a1a2e';
    var tooltipBorder = isDark ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.10)';

    // Build legend
    var legendEl = document.getElementById('p2p-legend');
    var sectorsSeen = {};
    var legendHtml = '';
    positions.forEach(function(p) {
        var sec = p.sector || 'Other';
        if (!sectorsSeen[sec]) {
            sectorsSeen[sec] = true;
            var c = getSectorColor(sec);
            legendHtml += '<div class="p2p-legend-item">'
                + '<div class="p2p-legend-dot" style="background:' + c.border + '; color:' + c.border + ';"></div>'
                + sec + '</div>';
        }
    });
    legendEl.innerHTML = legendHtml;

    // Chart data — X: Return %, Y: Days Held, Size: Market Value
    var mvValues = positions.map(function(p) { return p.market_value || 1; });
    var maxMv = mvValues.length > 0 ? Math.max.apply(null, mvValues) : 1;
    var dataPoints = positions.map(function(p) {
        var sc = getSectorColor(p.sector);
        var radius = Math.max(10, Math.min(32, 10 + ((p.market_value || 0) / maxMv) * 22));
        return {
            x: p.pnl_pct || 0,
            y: p.days_held || 0,
            r: radius,
            symbol: p.symbol,
            sector: p.sector || 'Other',
            marketValue: p.market_value || 0,
            pnlDollar: p.pnl_dollar || 0,
            pnlPct: p.pnl_pct || 0,
            entryPrice: p.entry_price || 0,
            currentPrice: p.current_price || 0,
            shares: p.shares || 0,
            adaptiveStop: p.adaptive_stop_pct,
            daysRemaining: p.days_remaining || 0,
            _bgColor: sc.bg,
            _borderColor: sc.border,
            _glowColor: sc.glow
        };
    });

    // Stats
    var best = positions[0], worst = positions[0], totalVal = 0, sumRet = 0;
    positions.forEach(function(p) {
        if ((p.pnl_pct || 0) > (best.pnl_pct || 0)) best = p;
        if ((p.pnl_pct || 0) < (worst.pnl_pct || 0)) worst = p;
        totalVal += p.market_value || 0;
        sumRet += p.pnl_pct || 0;
    });
    var avgRet = sumRet / positions.length;
    var bestEl = document.getElementById('p2p-best');
    var worstEl = document.getElementById('p2p-worst');
    var avgEl = document.getElementById('p2p-avg');
    bestEl.textContent = best.symbol + ' ' + (best.pnl_pct >= 0 ? '+' : '') + best.pnl_pct.toFixed(2) + '%';
    bestEl.style.color = best.pnl_pct >= 0 ? 'var(--green)' : 'var(--red)';
    worstEl.textContent = worst.symbol + ' ' + (worst.pnl_pct >= 0 ? '+' : '') + worst.pnl_pct.toFixed(2) + '%';
    worstEl.style.color = worst.pnl_pct >= 0 ? 'var(--green)' : 'var(--red)';
    avgEl.textContent = (avgRet >= 0 ? '+' : '') + avgRet.toFixed(2) + '%';
    avgEl.style.color = avgRet >= 0 ? 'var(--green)' : 'var(--red)';
    document.getElementById('p2p-total').textContent = '$' + totalVal.toLocaleString('en-US', {maximumFractionDigits:0});
    document.getElementById('p2p-badge').textContent = positions.length + ' ' + t('p2p-positions');

    // Destroy previous chart
    if (_p2pChart) _p2pChart.destroy();

    var ctx = document.getElementById('p2pScatterChart').getContext('2d');

    _p2pChart = new Chart(ctx, {
        type: 'bubble',
        data: {
            datasets: [{
                data: dataPoints,
                backgroundColor: dataPoints.map(function(d) { return d._bgColor; }),
                borderColor: dataPoints.map(function(d) { return d._borderColor; }),
                borderWidth: 2,
                hoverBorderWidth: 3,
                hoverBorderColor: '#fff'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: 800,
                easing: 'easeOutQuart'
            },
            layout: { padding: { top: 20, right: 20, bottom: 4, left: 8 } },
            plugins: {
                legend: { display: false },
                tooltip: {
                    enabled: true,
                    backgroundColor: tooltipBg,
                    titleColor: tooltipText,
                    bodyColor: tooltipText,
                    borderColor: tooltipBorder,
                    borderWidth: 1,
                    cornerRadius: 10,
                    padding: 14,
                    titleFont: { family: "'JetBrains Mono', monospace", size: 14, weight: '800' },
                    bodyFont: { family: "'Inter', sans-serif", size: 12 },
                    displayColors: false,
                    callbacks: {
                        title: function(items) {
                            var d = items[0].raw;
                            return d.symbol + '  ' + (d.pnlPct >= 0 ? '+' : '') + d.pnlPct.toFixed(2) + '%';
                        },
                        label: function(item) {
                            var d = item.raw;
                            return [
                                t('tt-sector') + ': ' + d.sector,
                                t('tt-value') + ': $' + d.marketValue.toLocaleString('en-US', {maximumFractionDigits:0}),
                                'P&L: ' + (d.pnlDollar >= 0 ? '+$' : '-$') + Math.abs(d.pnlDollar).toLocaleString('en-US', {maximumFractionDigits:0}),
                                t('tt-price') + ': $' + d.entryPrice.toFixed(2) + ' → $' + d.currentPrice.toFixed(2),
                                t('tt-shares') + ': ' + d.shares,
                                t('tt-days') + ': ' + d.y + '/5  (' + t('tt-remaining') + ' ' + d.daysRemaining + ')',
                                d.adaptiveStop != null ? 'Stop: ' + d.adaptiveStop.toFixed(0) + '%' : ''
                            ].filter(Boolean);
                        }
                    }
                },
                annotation: {
                    annotations: {
                        zeroLine: {
                            type: 'line',
                            xMin: 0, xMax: 0,
                            borderColor: zeroLineColor,
                            borderWidth: 2,
                            borderDash: [6, 4],
                            label: {
                                display: true,
                                content: 'Breakeven',
                                position: 'start',
                                color: labelColor,
                                font: { size: 10, family: "'Inter', sans-serif", weight: '600' },
                                backgroundColor: 'transparent',
                                padding: 2
                            }
                        }
                    }
                }
            },
            scales: {
                x: {
                    title: {
                        display: true,
                        text: t('p2p-axis-return'),
                        color: labelColor,
                        font: { size: 11, weight: '700', family: "'Inter', sans-serif" },
                        padding: { top: 6 }
                    },
                    grid: {
                        color: gridColor,
                        drawTicks: false
                    },
                    ticks: {
                        color: labelColor,
                        font: { size: 11, family: "'JetBrains Mono', monospace" },
                        callback: function(v) { return (v >= 0 ? '+' : '') + v.toFixed(1) + '%'; }
                    },
                    border: { color: gridColor }
                },
                y: {
                    title: {
                        display: true,
                        text: t('p2p-axis-days'),
                        color: labelColor,
                        font: { size: 11, weight: '700', family: "'Inter', sans-serif" },
                        padding: { bottom: 6 }
                    },
                    grid: {
                        color: gridColor,
                        drawTicks: false
                    },
                    ticks: {
                        color: labelColor,
                        font: { size: 11, family: "'JetBrains Mono', monospace" },
                        stepSize: 1,
                        callback: function(v) { return v + 'd'; }
                    },
                    border: { color: gridColor },
                    suggestedMin: 0,
                    suggestedMax: 5
                }
            }
        },
        plugins: [{
            id: 'p2pLabels',
            afterDatasetsDraw: function(chart) {
                var ctx2 = chart.ctx;
                var meta = chart.getDatasetMeta(0);
                ctx2.save();
                meta.data.forEach(function(el, i) {
                    var d = chart.data.datasets[0].data[i];
                    ctx2.font = '700 12px "JetBrains Mono", monospace';
                    ctx2.fillStyle = isDark ? '#fff' : '#1a1a2e';
                    ctx2.textAlign = 'center';
                    ctx2.textBaseline = 'middle';
                    // Draw symbol label above the bubble
                    ctx2.shadowColor = isDark ? 'rgba(0,0,0,0.6)' : 'rgba(255,255,255,0.8)';
                    ctx2.shadowBlur = 4;
                    ctx2.fillText(d.symbol, el.x, el.y - el.options.radius - 8);
                    ctx2.shadowBlur = 0;
                });
                ctx2.restore();
            }
        }, {
            id: 'p2pGlow',
            beforeDatasetsDraw: function(chart) {
                var ctx2 = chart.ctx;
                var meta = chart.getDatasetMeta(0);
                ctx2.save();
                meta.data.forEach(function(el, i) {
                    var d = chart.data.datasets[0].data[i];
                    ctx2.beginPath();
                    ctx2.arc(el.x, el.y, el.options.radius + 4, 0, Math.PI * 2);
                    ctx2.fillStyle = d._glowColor;
                    ctx2.fill();
                });
                ctx2.restore();
            }
        }]
    });
}

async function fetchAnnualReturns() {
    try {
        var res = await fetch('/api/annual-returns');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        var data = await res.json();
        if (!data.data || data.data.length === 0) return;
        _annualData = { data: data.data, positive: data.positive_years, total: data.total_years };
        renderAnnualReturns(data.data, data.positive_years, data.total_years);
    } catch (e) {
        console.error('Annual returns fetch error:', e);
        showFetchError('retornos anuales', e);
        var badge = document.getElementById('ar-badge');
        if (badge) {
            badge.textContent = t('ar-error-badge');
            badge.style.color = 'var(--red)';
            badge.style.background = 'var(--red-dim)';
        }
    }
}

function renderAnnualReturns(data, positiveYears, totalYears) {
    var ctx = document.getElementById('annualReturnsChart');
    if (!ctx) return;

    var isDark = document.body.classList.contains('dark');
    var years = data.map(function(d) { return d.year; });
    var hydraRets = data.map(function(d) { return d.hydra; });
    var spyRets = data.map(function(d) { return d.spy; });

    /* ── Badge ─────────────────────────────────────────────────────────── */
    var badge = document.getElementById('ar-badge');
    if (badge) badge.textContent = positiveYears + '/' + totalYears + ' ' + t('ar-positive-count');

    /* ── Per-year derived flags ─────────────────────────────────────────── */
    var underperforms = data.map(function(d) {
        return d.spy != null && d.hydra < d.spy;
    });

    /* ── Stat block ─────────────────────────────────────────────────────── */
    var hydraWins = 0;
    var totalAlpha  = 0;
    var validPairs  = 0;
    data.forEach(function(d) {
        if (d.spy != null) {
            if (d.hydra > d.spy) hydraWins++;
            totalAlpha += (d.hydra - d.spy);
            validPairs++;
        }
    });
    var hydraLosses = validPairs - hydraWins;
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
    var elTotalEn = document.getElementById('ar-stat-total-en');
    if (elTotalEn)  elTotalEn.textContent = totalYears;
    if (elBeats)    elBeats.textContent    = hydraWins + '/' + validPairs;
    if (elLoses) {
        elLoses.textContent = hydraLosses + '/' + validPairs;
        /* Colour the "loses" count red only when meaningful */
        elLoses.className = 'ar-stat-value' + (hydraLosses > 0 ? ' negative' : ' positive');
    }
    if (elAlpha) {
        elAlpha.textContent = alphaSign + avgAlpha.toFixed(1) + ' pp';
        elAlpha.className   = 'ar-stat-value' + (avgAlpha >= 0 ? ' positive' : ' negative');
    }

    /* ── Design tokens ──────────────────────────────────────────────────── */
    /*
     * HYDRA bars:  solid green (positive) / solid red (negative).
     *                No opacity tricks — colour alone carries the sign.
     * SPY bars:      low-opacity indigo ghost — pure reference, not competitor.
     * Underperform:  communicated through a small yellow diamond drawn on the
     *                Y-axis tick by the custom plugin, not through bar colour.
     */
    var hydraColors = hydraRets.map(function(v) {
        if (v >= 0) return isDark ? '#22c55e' : '#15803d';
        return isDark ? '#f87171' : '#b91c1c';
    });
    var spyColors = spyRets.map(function(v) {
        if (v == null) return 'transparent';
        return isDark ? 'rgba(255, 255, 255, 0.12)' : 'rgba(0, 0, 0, 0.12)';
    });
    var spyBorderColors = spyRets.map(function(v) {
        if (v == null) return 'transparent';
        return isDark ? 'rgba(255, 255, 255, 0.25)' : 'rgba(0, 0, 0, 0.25)';
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
                    data: hydraRets,
                    backgroundColor: hydraColors,
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
            /* Right padding: enough room for the HYDRA value labels */
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
                            var hydraVal = null, spy = null;
                            items.forEach(function(it) {
                                if (it.dataset.label === 'HYDRA') hydraVal = it.parsed.x;
                                if (it.dataset.label === 'S&P 500') spy = it.parsed.x;
                            });
                            if (hydraVal != null && spy != null) {
                                var diff = hydraVal - spy;
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
             * Plugin 1 — HYDRA value labels
             * Drawn only for dataset 0 (HYDRA).
             * Positive bars: label to the RIGHT of bar end.
             * Negative bars: label to the LEFT of bar end.
             * Font: 10px JetBrains Mono / colour tracks sign.
             */
            {
                id: 'arValueLabels',
                afterDatasetsDraw: function(chart, args, opts) {
                    if (args.index !== 0) return;   /* HYDRA only */
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
             * For years where HYDRA < SPY, paint a 3px wide yellow left-edge
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

/* ============ LIVE COMPARISON CHART (HYDRA vs S&P 500, %) ============ */
var _liveCompChart = null;
async function fetchLiveCompChart() {
    try {
        var res = await fetch('/api/live-chart');
        if (!res.ok) return;
        var data = await res.json();
        renderLiveCompChart(data);
    } catch (e) { /* silent */ }
}

function renderLiveCompChart(data) {
    var canvas = document.getElementById('liveCompChart');
    if (!canvas || typeof Chart === 'undefined') return;
    if (!data.dates || data.dates.length < 2) {
        document.getElementById('live-perf-section').style.display = 'none';
        return;
    }

    var isDark = document.body.classList.contains('dark');

    // Only show up to yesterday's close — today is still intraday
    var today = new Date().toISOString().slice(0, 10);
    var cutoff = data.dates.length;
    for (var ci = 0; ci < data.dates.length; ci++) {
        if (data.dates[ci] >= today) { cutoff = ci; break; }
    }
    var dates = data.dates.slice(0, cutoff);
    var rawHydra = (data.hydra || data.compass || []).slice(0, cutoff);
    var rawSpy = (data.spy || []).slice(0, cutoff);
    if (!rawHydra || dates.length < 2) return;
    var hydra = rawHydra.map(function(v) { return +(v - 100).toFixed(2); });
    var spy = rawSpy.map(function(v) { return +(v - 100).toFixed(2); });

    // Adaptive x-axis labels based on data density
    var tradingDays = dates.length;
    var useMonthLabels = tradingDays > 40;
    var MONTH_ABBR = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];

    var dayLabels;
    if (useMonthLabels) {
        // Show "Mar", "Abr", "May" at month boundaries; empty string for other points
        var lastMonth = -1;
        dayLabels = dates.map(function(d) {
            var m = parseInt(d.slice(5, 7), 10) - 1; // 0-based month
            if (m !== lastMonth) { lastMonth = m; return MONTH_ABBR[m]; }
            return '';
        });
    } else {
        // Show day numbers: 1, 2, 3 ...
        dayLabels = dates.map(function(_, i) { return String(i + 1); });
    }

    // Subtitle: "Días de Trading: N · dd/mm/yyyy – dd/mm/yyyy"
    var sub = document.getElementById('live-perf-subtitle');
    if (sub) {
        var fmtDate = function(s) { var p = s.split('-'); return p[2] + '/' + p[1] + '/' + p[0]; };
        sub.textContent = (t('ml-trading-days') || 'Día') + ': ' + tradingDays + ' \u00b7 ' +
            fmtDate(dates[0]) + ' \u2013 ' + fmtDate(dates[dates.length - 1]);
    }

    var greenLine = isDark ? '#4ade80' : '#16a34a';
    var greenFill = isDark ? 'rgba(34,197,94,0.12)' : 'rgba(22,163,74,0.08)';
    var blueLine = isDark ? 'rgba(56,189,248,0.7)' : 'rgba(14,165,233,0.6)';
    var blueFill = isDark ? 'rgba(56,189,248,0.06)' : 'rgba(14,165,233,0.04)';
    var gridColor = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)';
    var tickColor = isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.5)';
    var zeroColor = isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.12)';

    if (_liveCompChart) _liveCompChart.destroy();
    _liveCompChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
            labels: dayLabels,
            datasets: [
                {
                    label: 'HYDRA',
                    data: hydra,
                    borderColor: greenLine,
                    borderWidth: tradingDays > 120 ? 1.5 : 2.5,
                    fill: true,
                    backgroundColor: greenFill,
                    pointRadius: tradingDays <= 30 ? 4 : 0,
                    pointBackgroundColor: greenLine,
                    pointBorderColor: isDark ? '#1a1a2e' : '#fff',
                    pointBorderWidth: 2,
                    pointHoverRadius: tradingDays > 120 ? 4 : 6,
                    tension: tradingDays > 120 ? 0.3 : 0.25,
                },
                {
                    label: 'S&P 500',
                    data: spy,
                    borderColor: blueLine,
                    borderWidth: tradingDays > 120 ? 1.2 : 1.8,
                    borderDash: tradingDays > 120 ? [4, 2] : [6, 3],
                    fill: true,
                    backgroundColor: blueFill,
                    pointRadius: tradingDays <= 30 ? 3 : 0,
                    pointBackgroundColor: blueLine,
                    pointBorderColor: isDark ? '#1a1a2e' : '#fff',
                    pointBorderWidth: 1.5,
                    pointHoverRadius: tradingDays > 120 ? 3 : 5,
                    tension: tradingDays > 120 ? 0.3 : 0.25,
                }
            ]
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
                    displayColors: true,
                    callbacks: {
                        title: function(items) {
                            var idx = items[0].dataIndex;
                            var d = dates[idx];
                            var p = d.split('-');
                            var dateStr = p[2] + '/' + p[1] + '/' + p[0];
                            if (useMonthLabels) {
                                return dateStr + '  \u00b7  ' + t('day-label') + ' ' + (idx + 1);
                            }
                            return t('day-label') + ' ' + (idx + 1) + '  \u00b7  ' + dateStr;
                        },
                        label: function(ctx) {
                            var sign = ctx.parsed.y >= 0 ? '+' : '';
                            return ' ' + ctx.dataset.label + ':  ' + sign + ctx.parsed.y.toFixed(2) + '%';
                        }
                    }
                },
                annotation: {
                    annotations: {
                        zeroLine: {
                            type: 'line',
                            yMin: 0, yMax: 0,
                            borderColor: zeroColor,
                            borderWidth: 1,
                            borderDash: [4, 4],
                        }
                    }
                }
            },
            scales: {
                x: {
                    ticks: {
                        color: tickColor,
                        font: { family: "'JetBrains Mono', monospace", size: 10 },
                        maxRotation: 0,
                        autoSkip: !useMonthLabels,
                        callback: function(val, idx) {
                            if (useMonthLabels) {
                                // Only show labels at month boundaries (non-empty labels)
                                return dayLabels[idx] || null;
                            }
                            return val;
                        }
                    },
                    grid: {
                        color: function(ctx) {
                            // Subtle grid line at month boundaries in month mode
                            if (useMonthLabels && dayLabels[ctx.index]) return gridColor;
                            return useMonthLabels ? 'transparent' : gridColor;
                        }
                    },
                    border: { color: gridColor },
                    title: {
                        display: !useMonthLabels,
                        text: 'Día de Trading',
                        color: tickColor,
                        font: { family: "'Inter', sans-serif", size: 10, weight: '600' },
                    },
                },
                y: {
                    ticks: {
                        color: tickColor,
                        font: { family: "'JetBrains Mono', monospace", size: 10 },
                        callback: function(v) {
                            return (v >= 0 ? '+' : '') + v.toFixed(1) + '%';
                        }
                    },
                    grid: { color: gridColor },
                    border: { color: gridColor },
                }
            }
        }
    });
}

/* ============ INIT ============ */
document.addEventListener('DOMContentLoaded', function() {
    fetchEquityData();
    fetchAnnualReturns();
    fetchLiveCompChart();
    fetchAll();
    fetchCycleLog();
    fetchRiskData();
    fetchMonteCarlo();

    fetchTradeAnalytics();
    fetchFundComparison();
    var _pollTimers = [];
    function _startPolling() {
        _pollTimers.push(setInterval(fetchRiskData, 300000));
        _pollTimers.push(setInterval(fetchMonteCarlo, 300000));
        _pollTimers.push(setInterval(function() { fetchAll(); fetchCycleLog(); if (!_startupRetryTimer) countdownSec = 30; }, REFRESH_MS));
        _pollTimers.push(setInterval(function() {
            countdownSec = Math.max(0, countdownSec - 1);
            document.getElementById('countdown').textContent = countdownSec;
        }, 1000));
        _pollTimers.push(setInterval(updateMarketTimer, 1000));
    }
    function _stopPolling() {
        _pollTimers.forEach(function(id) { clearInterval(id); });
        _pollTimers = [];
    }
    _startPolling();
    document.addEventListener('visibilitychange', function() {
        if (document.hidden) { _stopPolling(); } else { _startPolling(); fetchAll(); }
    });

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
            lbl.textContent = t('paper-trading-live');
            lbl.style.color = 'var(--green)';
            const left = (mktClose * 60) - (mins * 60 + s);
            const hh = Math.floor(left / 3600), mm = Math.floor((left % 3600) / 60), ss = left % 60;
            cd.textContent = t('market-closes') + ' ' + hh + 'h ' + String(mm).padStart(2,'0') + 'm ' + String(ss).padStart(2,'0') + 's';
        } else {
            lbl.textContent = t('hdr-market-closed');
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
            cd.textContent = t('market-opens') + ' ' + hh + 'h ' + String(mm).padStart(2,'0') + 'm ' + String(ss).padStart(2,'0') + 's';
        }
    }
    updateMarketTimer();
});

/* ============ EXPERIMENT ANALYSIS PANEL ============ */
function fetchExpAnalysis() {
    const container = document.getElementById('exp-analysis-container');
    if (!container) return;

    const totalExp = 68;
    const failed = 57;
    const approved = 3;  /* v8 HYDRA + Exp #34 IG Cash Yield + EXP59 HYDRA */
    const partial = 2;   /* RATTLESNAKE standalone + QUANTUM */
    const failRate = ((failed / totalExp) * 100).toFixed(1);

    /* Category breakdown */
    const categories = [
        { name: 'Motor (signal/params)', tried: 18, failed: 16, examples: 'v8.1 shorts, rank-hysteresis, VORTEX, behavioral, ensemble, preemptive stop, profit target, MWF, Genius Layer' },
        { name: 'Alternative engines', tried: 7, failed: 5, examples: 'VIPER ETF, ECLIPSE pairs, QUANTUM RSI, RATTLESNAKE mean-rev' },
        { name: 'Geographic expansion', tried: 2, failed: 2, examples: 'HYDRA EU (STOXX), HYDRA Asia (N225)' },
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
    html += '<div class="exp-stat-box"><div class="exp-stat-label">HYDRA CAGR</div><div class="exp-stat-val" style="color:var(--green);">15.62%</div><div class="exp-stat-note">Survivorship-corrected (882 PIT tickers) | +Catalyst 4th pillar</div></div>';
    html += '<div class="exp-stat-box"><div class="exp-stat-label">WORST EXPERIMENT</div><div class="exp-stat-val" style="color:var(--red);">-20.87%</div><div class="exp-stat-note">HYDRA EU v1 ($100K &rarr; $507)</div></div>';
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
    html += '<div class="exp-proposal-desc">68 experiments confirm HYDRA (Momentum + Rattlesnake + Catalyst + EFA) as the optimal configuration. EXP68 validated 4th pillar (cross-asset trend + gold): 15.62% CAGR, 1.08 Sharpe, -21.7% MaxDD.</div>';
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
        if (!res.ok) throw new Error('HTTP ' + res.status);
        var data = await res.json();
        renderMLTerminal(data.log_entries || [], data.insights || {});
        renderMLInterpretation(data.interpretation_live || data.interpretation || '', 'ml-interpret-live', 'ml-interpret-live-time');
        renderMLKpis(data.kpis || {});
    } catch (e) {
        console.error('ML fetch failed:', e);
        showFetchError('ML', e);
    }
}

function renderMLKpis(k) {
    function setText(id, val) {
        var el = document.getElementById(id);
        if (el) el.textContent = val;
    }
    function fmtRatioPct(v) {
        if (v == null) return '--';
        return (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%';
    }
    function fmtDollar(v) {
        if (v == null) return '--';
        var sign = v >= 0 ? '+' : '';
        return sign + '$' + Math.abs(v).toLocaleString('en-US', {maximumFractionDigits: 0});
    }

    setText('ml-kpi-outcomes', k.total_outcomes != null ? k.total_outcomes : '--');
    setText('ml-kpi-entries-exits', (k.total_entries || 0) + ' entries / ' + (k.total_exits || 0) + ' exits');

    var wrEl = document.getElementById('ml-kpi-winrate');
    if (wrEl) {
        var wr = k.win_rate != null ? (k.win_rate * 100).toFixed(0) + '%' : '--';
        wrEl.textContent = wr;
        wrEl.className = 'ml-kpi-value' + (k.win_rate != null ? (k.win_rate >= 0.5 ? ' c-green' : ' c-red') : '');
    }
    setText('ml-kpi-stoprate', 'Stop rate: ' + (k.stop_rate != null ? (k.stop_rate * 100).toFixed(0) + '%' : '--'));

    var arEl = document.getElementById('ml-kpi-avgreturn');
    if (arEl) {
        arEl.textContent = k.avg_return != null ? fmtRatioPct(k.avg_return) : '--';
        arEl.className = 'ml-kpi-value' + (k.avg_return != null ? (k.avg_return >= 0 ? ' c-green' : ' c-red') : '');
    }
    setText('ml-kpi-bestworst', 'Best: ' + fmtRatioPct(k.best_trade) + ' / Worst: ' + fmtRatioPct(k.worst_trade));

    var pnlEl = document.getElementById('ml-kpi-pnl');
    if (pnlEl) {
        pnlEl.textContent = k.total_pnl != null ? fmtDollar(k.total_pnl) : '--';
        pnlEl.className = 'ml-kpi-value' + (k.total_pnl != null ? (k.total_pnl >= 0 ? ' c-green' : ' c-red') : '');
    }
    setText('ml-kpi-alpha', 'Alpha vs S&P: ' + (k.avg_alpha != null ? fmtRatioPct(k.avg_alpha) : '--'));

    setText('ml-kpi-days', k.trading_days != null ? k.trading_days : '--');
    setText('ml-kpi-decisions', (k.total_decisions || 0) + ' ' + t('ml-decisions'));

    setText('ml-kpi-phase', k.phase != null ? k.phase + '/3' : '--');
    var progressEl = document.getElementById('ml-kpi-progress');
    if (progressEl) progressEl.style.width = (k.phase2_progress_pct || 0) + '%';
    if (k.phase < 2) {
        setText('ml-kpi-phase-sub', (k.days_to_phase2 || '--') + ' ' + t('ml-days-to-phase2'));
    } else {
        setText('ml-kpi-phase-sub', t('ml-phase-label') + ' ' + k.phase + ' ' + t('ml-phase-active'));
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

        if (r._type !== 'backtest') {
            var lineCls = 'ml-line';
            if (r._type === 'decision') {
                var dt = r.decision_type || '';
                if (dt === 'entry') lineCls += ' ml-line-entry';
                else if (dt === 'exit') lineCls += ' ml-line-exit';
                else if (dt === 'skip') lineCls += ' ml-line-skip';
            } else if (r._type === 'snapshot') lineCls += ' ml-line-snapshot';
            else if (r._type === 'outcome') lineCls += ' ml-line-outcome';
            html += '<div class="' + lineCls + '"><span class="ml-line-ts">' + ts + '</span>' + badge + '<span class="ml-line-detail">' + detail + '</span></div>';
        }
    });

    logEl.innerHTML = html;

    /* Auto-scroll on new entries */
    if (entries.length > _mlLastCount) {
        logEl.scrollTop = logEl.scrollHeight;
        _mlLastCount = entries.length;
    }
}

function renderMLInterpretation(text, elId, timeElId) {
    var el = document.getElementById(elId);
    var timeEl = document.getElementById(timeElId);
    if (!el) return;
    if (!text) {
        el.innerHTML = '<p class="ml-interpret-loading">' + t('ml-waiting-analysis') + '</p>';
        return;
    }
    /* Simple markdown-to-HTML (sanitize first to prevent XSS) */
    var html = escHtml(text)
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

/* Poll ML data every 60s (managed by visibilitychange via _pollTimers) */
var _mlTimer = setInterval(fetchMLLearning, 60000);
/* Initial load on page ready */
document.addEventListener('DOMContentLoaded', function() {
    fetchMLLearning();
});
document.addEventListener('visibilitychange', function() {
    if (document.hidden) { clearInterval(_mlTimer); _mlTimer = null; }
    else if (!_mlTimer) { _mlTimer = setInterval(fetchMLLearning, 60000); fetchMLLearning(); }
});

/* ============ FUND COMPARISON PAGE ============ */

var _fcData = null;
var _fcEquityChart = null;
var _fcDrawdownChart = null;
var _fcScatterChart = null;
var _fcRollingChart = null;

async function fetchFundComparison() {
    try {
        var res = await fetch('/api/fund-comparison');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        var data = await res.json();
        _fcData = data;
        renderFCHeroKpis(data);
        renderFCMetrics(data);
        renderFCEquityChart(data);
        renderFCDrawdownChart(data);
        renderFCCrisisCards(data);
        renderFCScatterChart(data);
        renderFCRollingChart(data);
        renderFCAnnual(data);
        renderFCNotes(data);
    } catch (e) {
        console.error('Fund comparison fetch failed:', e);
        showFetchError('comparativa de fondos', e);
        var body = document.getElementById('fc-metrics-body');
        if (body) body.innerHTML = '<tr><td colspan="10" style="color:var(--red);text-align:center;">' + t('fc-error-text') + '</td></tr>';
    }
}

function _fcEscapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function _fcCreateRow(cells, isHighlight) {
    var tr = document.createElement('tr');
    if (isHighlight) tr.className = 'fc-row-highlight';
    cells.forEach(function(cell) {
        var td = document.createElement('td');
        if (cell.cls) td.className = cell.cls;
        if (cell.style) td.setAttribute('style', cell.style);
        td.textContent = cell.text;
        tr.appendChild(td);
    });
    return tr;
}

function renderFCMetrics(data) {
    var tbody = document.getElementById('fc-metrics-body');
    if (!tbody) return;
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
    data.funds.forEach(function(f) {
        var row = _fcCreateRow([
            {text: f.name, cls: 'fc-fund-name'},
            {text: f.type},
            {text: String(f.inception)},
            {text: f.cagr.toFixed(1) + '%', cls: f.cagr >= 0 ? 'fc-pos' : 'fc-neg'},
            {text: f.sharpe.toFixed(2)},
            {text: f.max_dd.toFixed(1) + '%', cls: 'fc-neg'},
            {text: f.volatility.toFixed(1) + '%'},
            {text: '+' + f.cumulative.toFixed(0) + '%'},
            {text: f.expense_ratio != null ? f.expense_ratio.toFixed(2) + '%' : '\u2014'},
            {text: f.aum || '\u2014'},
        ], f.highlight);
        tbody.appendChild(row);
    });
}

function renderFCEquityChart(data) {
    var canvas = document.getElementById('fc-equity-chart');
    if (!canvas || typeof Chart === 'undefined') return;

    /* Build unified monthly timeline from all funds' growth_100k data */
    var allMonths = {};
    data.funds.forEach(function(f) {
        if (f.growth_100k) {
            Object.keys(f.growth_100k).forEach(function(m) { allMonths[m] = true; });
        }
    });
    var monthLabels = Object.keys(allMonths).sort();

    /* Fallback: if no growth_100k data, use annual returns compounding */
    var useMonthly = monthLabels.length > 0;
    if (!useMonthly) {
        monthLabels = [];
        for (var y = 2000; y <= 2026; y++) monthLabels.push(String(y));
    }

    /* Color palette: HYDRA highlighted, others distinct */
    var colors = [
        '#00e676', /* HYDRA Net — bright green */
        '#78909c', /* SPY — grey (benchmark) */
        '#2196f3', /* AQR — blue */
        '#e91e63', /* MTUM — pink */
        '#fdd835', /* QQQ — yellow */
        '#ff7043', /* BRK.B — deep orange */
    ];
    var datasets = [];

    data.funds.forEach(function(f, idx) {
        var values = [];
        if (useMonthly && f.growth_100k) {
            monthLabels.forEach(function(m) {
                values.push(f.growth_100k[m] != null ? f.growth_100k[m] : null);
            });
        } else {
            /* Fallback: compound annual returns */
            var val = 100000;
            monthLabels.forEach(function(year) {
                var yr = parseInt(year);
                var ret = (f.annual_returns && f.annual_returns[yr] != null) ? f.annual_returns[yr] : null;
                if (ret !== null) {
                    val = val * (1 + ret / 100);
                    values.push(val);
                } else {
                    values.push(null);
                }
            });
        }
        datasets.push({
            label: f.name,
            data: values,
            borderColor: colors[idx % colors.length],
            backgroundColor: 'transparent',
            borderWidth: f.highlight ? 2.5 : 1.2,
            borderDash: f.highlight ? [] : [4, 2],
            pointRadius: 0,
            tension: 0.1,
            spanGaps: false,
        });
    });

    if (_fcEquityChart) _fcEquityChart.destroy();
    _fcEquityChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: { labels: monthLabels, datasets: datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        color: '#ccc',
                        font: { size: 10 },
                        boxWidth: 14,
                        padding: 8,
                        usePointStyle: true,
                    }
                },
                tooltip: {
                    callbacks: {
                        title: function(items) {
                            if (!items.length) return '';
                            var lbl = items[0].label || '';
                            /* Show year-month or just year */
                            return lbl.length === 7 ? lbl : lbl;
                        },
                        label: function(ctx) {
                            if (ctx.raw == null) return ctx.dataset.label + ': N/A';
                            return ctx.dataset.label + ': $' + Math.round(ctx.raw).toLocaleString();
                        }
                    }
                },
                zoom: {
                    zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: 'x' },
                    pan: { enabled: true, mode: 'x' },
                },
            },
            scales: {
                x: {
                    ticks: {
                        color: '#999',
                        font: { size: 10 },
                        maxTicksLimit: 14,
                        callback: function(val, idx) {
                            var d = this.getLabelForValue(val);
                            /* Show only Jan of each year (YYYY-01) or plain year */
                            if (!d) return '';
                            if (d.length === 7) return d.endsWith('-01') ? d.slice(0, 4) : '';
                            return d;
                        }
                    },
                    grid: { color: 'rgba(255,255,255,0.05)' },
                },
                y: {
                    type: 'logarithmic',
                    ticks: {
                        color: '#999',
                        callback: function(v) {
                            if (v >= 1000000) return '$' + (v / 1000000).toFixed(1) + 'M';
                            if (v >= 1000) return '$' + (v / 1000).toFixed(0) + 'K';
                            return '$' + v;
                        }
                    },
                    grid: { color: 'rgba(255,255,255,0.05)' },
                }
            }
        }
    });
}

/* renderFCCrisis removed — replaced by renderFCCrisisCards */

function renderFCAnnual(data) {
    /* Dynamically determine year range from data */
    var yearSet = {};
    data.funds.forEach(function(f) {
        if (f.annual_returns) {
            Object.keys(f.annual_returns).forEach(function(y) { yearSet[y] = true; });
        }
    });
    var allYears = Object.keys(yearSet).map(Number).sort();

    var thead = document.getElementById('fc-annual-head');
    var tbody = document.getElementById('fc-annual-body');
    if (!thead || !tbody) return;

    // Build header row with DOM
    while (thead.firstChild) thead.removeChild(thead.firstChild);
    var headRow = document.createElement('tr');
    var thFund = document.createElement('th');
    thFund.textContent = t('fc-th-fund');
    headRow.appendChild(thFund);
    allYears.forEach(function(y) {
        var th = document.createElement('th');
        th.textContent = y;
        headRow.appendChild(th);
    });
    thead.appendChild(headRow);

    // Build body rows
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
    data.funds.forEach(function(f) {
        var tr = document.createElement('tr');
        if (f.highlight) tr.className = 'fc-row-highlight';
        var tdName = document.createElement('td');
        tdName.className = 'fc-fund-name fc-hm-name';
        tdName.textContent = f.name;
        tr.appendChild(tdName);
        allYears.forEach(function(y) {
            var td = document.createElement('td');
            td.className = 'fc-hm-cell';
            var ret = (f.annual_returns && f.annual_returns[y] != null) ? f.annual_returns[y] : null;
            if (ret !== null) {
                var alpha = Math.min(0.6, Math.abs(ret) / 50);
                var bg = ret >= 0
                    ? 'rgba(0,230,118,' + alpha + ')'
                    : 'rgba(255,82,82,' + alpha + ')';
                td.style.background = bg;
                td.textContent = (ret > 0 ? '+' : '') + ret.toFixed(1);
            } else {
                td.className += ' fc-na';
                td.textContent = '\u2014';
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

function renderFCNotes(data) {
    var ul = document.getElementById('fc-notes-list');
    if (!ul || !data.notes) return;
    while (ul.firstChild) ul.removeChild(ul.firstChild);
    data.notes.forEach(function(n) {
        var li = document.createElement('li');
        li.textContent = n;
        ul.appendChild(li);
    });
}

/* ---- Hero KPI cards ---- */
function renderFCHeroKpis(data) {
    var hydra = null, spy = null;
    data.funds.forEach(function(f) {
        if (f.highlight) hydra = f;
        if (f.id === 'spy' || (f.name && f.name.indexOf('SPY') !== -1 && !f.highlight)) spy = f;
    });
    if (!hydra) return;
    var el = function(id) { return document.getElementById(id); };
    if (el('fc-hero-cagr')) el('fc-hero-cagr').textContent = hydra.cagr.toFixed(1) + '%';
    if (el('fc-hero-dd')) el('fc-hero-dd').textContent = hydra.max_dd.toFixed(1) + '%';
    if (el('fc-hero-sharpe')) el('fc-hero-sharpe').textContent = hydra.sharpe.toFixed(2);
    if (spy) {
        if (el('fc-hero-cagr-vs')) el('fc-hero-cagr-vs').textContent = 'vs ' + spy.cagr.toFixed(1) + '% S&P';
        if (el('fc-hero-dd-vs')) el('fc-hero-dd-vs').textContent = 'vs ' + spy.max_dd.toFixed(1) + '% S&P';
        if (el('fc-hero-sharpe-vs')) el('fc-hero-sharpe-vs').textContent = 'vs ' + spy.sharpe.toFixed(2) + ' S&P';
    }
    /* Update growth insight */
    if (hydra.cumulative && el('fc-growth-insight')) {
        var final$ = Math.round(100000 * (1 + hydra.cumulative / 100));
        el('fc-growth-insight').textContent = '$100K → $' + (final$ / 1000000).toFixed(1) + 'M en 26 años';
    }
}

/* ---- Drawdown (underwater) chart ---- */
function renderFCDrawdownChart(data) {
    var canvas = document.getElementById('fc-drawdown-chart');
    if (!canvas || typeof Chart === 'undefined') return;

    /* Only plot HYDRA + SPY for clarity */
    var targets = [];
    data.funds.forEach(function(f) {
        if (f.highlight || f.id === 'spy' || (f.name && f.name.indexOf('SPY') !== -1 && !f.highlight)) {
            if (f.growth_100k) targets.push(f);
        }
    });
    if (!targets.length) return;

    /* Compute drawdown series from growth_100k */
    var allMonths = {};
    targets.forEach(function(f) {
        Object.keys(f.growth_100k).forEach(function(m) { allMonths[m] = true; });
    });
    var months = Object.keys(allMonths).sort();

    var ddColors = ['rgba(0,230,118,0.5)', 'rgba(255,82,82,0.45)'];
    var ddBorders = ['#00e676', '#ff5252'];
    var datasets = [];

    targets.forEach(function(f, idx) {
        var peak = 0;
        var ddValues = [];
        months.forEach(function(m) {
            var v = f.growth_100k[m];
            if (v == null) { ddValues.push(null); return; }
            if (v > peak) peak = v;
            ddValues.push(peak > 0 ? ((v - peak) / peak) * 100 : 0);
        });
        datasets.push({
            label: f.name,
            data: ddValues,
            borderColor: ddBorders[idx % ddBorders.length],
            backgroundColor: ddColors[idx % ddColors.length],
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.1,
            fill: true,
            spanGaps: false,
        });
    });

    if (_fcDrawdownChart) _fcDrawdownChart.destroy();
    _fcDrawdownChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: { labels: months, datasets: datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: true, position: 'top', labels: { color: '#ccc', font: { size: 10 }, boxWidth: 14, padding: 8, usePointStyle: true } },
                tooltip: {
                    callbacks: {
                        label: function(ctx) {
                            if (ctx.raw == null) return ctx.dataset.label + ': N/A';
                            return ctx.dataset.label + ': ' + ctx.raw.toFixed(1) + '%';
                        }
                    }
                }
            },
            scales: {
                x: {
                    ticks: { color: '#999', font: { size: 9 }, maxTicksLimit: 12,
                        callback: function(val) { var d = this.getLabelForValue(val); return d && d.length === 7 && d.endsWith('-01') ? d.slice(0, 4) : ''; }
                    },
                    grid: { color: 'rgba(255,255,255,0.05)' },
                },
                y: {
                    max: 0,
                    ticks: { color: '#999', callback: function(v) { return v.toFixed(0) + '%'; } },
                    grid: { color: 'rgba(255,255,255,0.05)' },
                }
            }
        }
    });
}

/* ---- Crisis cards (replaces table) ---- */
function renderFCCrisisCards(data) {
    var container = document.getElementById('fc-crisis-cards');
    if (!container) return;
    while (container.firstChild) container.removeChild(container.firstChild);

    var periods = data.crisis_periods || [];
    var hydra = null, spy = null;
    data.funds.forEach(function(f) {
        if (f.highlight) hydra = f;
        if (f.id === 'spy' || (f.name && f.name.indexOf('SPY') !== -1 && !f.highlight)) spy = f;
    });

    periods.forEach(function(p) {
        var card = document.createElement('div');
        card.className = 'fc-crisis-card';

        var nameEl = document.createElement('div');
        nameEl.className = 'fc-crisis-card-name';
        nameEl.textContent = p.name;
        card.appendChild(nameEl);

        var periodEl = document.createElement('div');
        periodEl.className = 'fc-crisis-card-period';
        periodEl.textContent = p.period;
        card.appendChild(periodEl);

        var retEl = document.createElement('div');
        retEl.className = 'fc-crisis-card-returns';

        [hydra, spy].forEach(function(f) {
            if (!f) return;
            var span = document.createElement('span');
            span.className = 'fc-crisis-card-fund';
            var cr = f.crisis_returns && f.crisis_returns[p.id];
            var v = cr && cr['return'] != null ? cr['return'] : null;
            if (v !== null) {
                span.textContent = f.name + ': ' + (v > 0 ? '+' : '') + v.toFixed(1) + '%';
                span.classList.add(v >= 0 ? 'fc-pos' : 'fc-neg');
            } else {
                span.textContent = f.name + ': N/A';
            }
            retEl.appendChild(span);
        });

        card.appendChild(retEl);
        container.appendChild(card);
    });
}

/* ---- Risk-return scatter ---- */
function renderFCScatterChart(data) {
    var canvas = document.getElementById('fc-scatter-chart');
    if (!canvas || typeof Chart === 'undefined') return;

    var scatterColors = [
        '#00e676', '#78909c', '#2196f3', '#e91e63', '#fdd835', '#ff7043',
        '#ab47bc', '#26a69a', '#8d6e63', '#5c6bc0'
    ];

    var points = [];
    data.funds.forEach(function(f, idx) {
        points.push({
            x: f.volatility,
            y: f.cagr,
            label: f.name,
            sharpe: f.sharpe,
            highlight: f.highlight,
            color: scatterColors[idx % scatterColors.length],
            radius: f.highlight ? 10 : 6 + Math.max(0, f.sharpe) * 3,
        });
    });

    if (_fcScatterChart) _fcScatterChart.destroy();
    _fcScatterChart = new Chart(canvas.getContext('2d'), {
        type: 'scatter',
        data: {
            datasets: points.map(function(p) {
                return {
                    label: p.label,
                    data: [{ x: p.x, y: p.y }],
                    backgroundColor: p.color,
                    borderColor: p.highlight ? '#fff' : p.color,
                    borderWidth: p.highlight ? 2 : 1,
                    pointRadius: p.radius,
                    pointHoverRadius: p.radius + 3,
                };
            })
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function(ctx) {
                            var ds = ctx.dataset;
                            var pt = ctx.raw;
                            return ds.label + ' — CAGR: ' + pt.y.toFixed(1) + '%, Vol: ' + pt.x.toFixed(1) + '%';
                        }
                    }
                },
                /* Label each point */
                datalabels: false
            },
            scales: {
                x: {
                    title: { display: true, text: 'Volatilidad (%)', color: '#999', font: { size: 11 } },
                    ticks: { color: '#999', callback: function(v) { return v + '%'; } },
                    grid: { color: 'rgba(255,255,255,0.05)' },
                },
                y: {
                    title: { display: true, text: 'CAGR (%)', color: '#999', font: { size: 11 } },
                    ticks: { color: '#999', callback: function(v) { return v + '%'; } },
                    grid: { color: 'rgba(255,255,255,0.05)' },
                }
            }
        },
        plugins: [{
            /* Inline labels next to each dot */
            afterDraw: function(chart) {
                var ctx = chart.ctx;
                ctx.font = '10px sans-serif';
                ctx.textBaseline = 'middle';
                chart.data.datasets.forEach(function(ds, i) {
                    var meta = chart.getDatasetMeta(i);
                    if (!meta.data.length) return;
                    var pt = meta.data[0];
                    ctx.fillStyle = ds.borderColor || ds.backgroundColor;
                    ctx.fillText(ds.label, pt.x + pt.options.radius + 4, pt.y);
                });
            }
        }]
    });
}

/* ---- Rolling 5-year CAGR ---- */
function renderFCRollingChart(data) {
    var canvas = document.getElementById('fc-rolling-chart');
    if (!canvas || typeof Chart === 'undefined') return;

    /* Only plot HYDRA + SPY */
    var targets = [];
    data.funds.forEach(function(f) {
        if (f.highlight || f.id === 'spy' || (f.name && f.name.indexOf('SPY') !== -1 && !f.highlight)) {
            if (f.annual_returns) targets.push(f);
        }
    });
    if (!targets.length) return;

    var allYears = {};
    targets.forEach(function(f) {
        Object.keys(f.annual_returns).forEach(function(y) { allYears[parseInt(y)] = true; });
    });
    var years = Object.keys(allYears).map(Number).sort();

    /* Compute rolling 5yr CAGR: geometric mean of years [y-4..y] */
    var window = 5;
    var rollingYears = [];
    var datasets = [];
    var rollingColors = ['#00e676', '#ff5252'];

    targets.forEach(function(f, idx) {
        var vals = [];
        var labels = [];
        for (var i = window - 1; i < years.length; i++) {
            var product = 1;
            var valid = true;
            for (var j = 0; j < window; j++) {
                var yr = years[i - (window - 1) + j];
                var r = f.annual_returns[yr];
                if (r == null) { valid = false; break; }
                product *= (1 + r / 100);
            }
            if (valid) {
                var cagr5 = (Math.pow(product, 1 / window) - 1) * 100;
                vals.push(cagr5);
                if (idx === 0) rollingYears.push(years[i]);
            } else {
                vals.push(null);
                if (idx === 0) rollingYears.push(years[i]);
            }
        }
        datasets.push({
            label: f.name,
            data: vals,
            borderColor: rollingColors[idx % rollingColors.length],
            backgroundColor: 'transparent',
            borderWidth: f.highlight ? 2.5 : 1.5,
            borderDash: f.highlight ? [] : [5, 3],
            pointRadius: 0,
            tension: 0.2,
        });
    });

    if (_fcRollingChart) _fcRollingChart.destroy();
    _fcRollingChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: { labels: rollingYears.map(String), datasets: datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: true, position: 'top', labels: { color: '#ccc', font: { size: 10 }, boxWidth: 14, padding: 8, usePointStyle: true } },
                tooltip: {
                    callbacks: {
                        title: function(items) { return items.length ? items[0].label + ' (5yr ending)' : ''; },
                        label: function(ctx) {
                            if (ctx.raw == null) return ctx.dataset.label + ': N/A';
                            return ctx.dataset.label + ': ' + ctx.raw.toFixed(1) + '%';
                        }
                    }
                }
            },
            scales: {
                x: {
                    ticks: { color: '#999', font: { size: 10 }, maxTicksLimit: 14 },
                    grid: { color: 'rgba(255,255,255,0.05)' },
                },
                y: {
                    ticks: { color: '#999', callback: function(v) { return v.toFixed(0) + '%'; } },
                    grid: { color: 'rgba(255,255,255,0.05)' },
                    title: { display: true, text: 'CAGR 5 años (%)', color: '#999', font: { size: 11 } }
                }
            }
        }
    });
}

function refreshDashboard() {
    if (lastPortfolioData) {
        var d = lastPortfolioData;
        var p = d.portfolio;
        updateStatusBar(p);
        updateStalePriceWarning(d._data_freshness);
        updateCards(p);
        updateRegimeBand(p);
        updatePerfBanner(p);
        updatePreclose(d.preclose);
        updatePositions(d.position_details);
        if (d.hydra) updateHydra(d.hydra);
        var posDict = {};
        if (d.position_details) {
            for (var i = 0; i < d.position_details.length; i++) posDict[d.position_details[i].symbol] = true;
        }
        updateUniverse(d.universe, posDict);
    }
}

