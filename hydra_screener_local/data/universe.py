"""
Manejo del universo de acciones.
Soporta tanto lista pequeña como el S&P 500 completo de forma ligera.
"""
import pandas as pd
import re
import requests
from io import StringIO
import os
import logging
import time
import json
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

CACHE_DAYS = 7  # refrescar la lista cada 7 días

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_MODULE_DIR)
DATA_CACHE_DIR = os.path.join(PROJECT_ROOT, "data_cache")


def _json_cache_path(universe: str) -> str:
    return os.path.join(DATA_CACHE_DIR, f"universe_cache_{universe}.json")

# Cache path relativo al archivo del módulo (robusto aunque se ejecute desde otro cwd)
def _get_cache_path(universe: str = "sp500") -> str:
    module_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(module_dir)  # sube de data/ a hydra_screener_local/
    safe_name = {
        "sp500": "sp500_tickers.csv",
        "nasdaq100": "nasdaq100_tickers.csv",
        "dow30": "dow30_tickers.csv",
        "russell1000": "russell1000_tickers.csv",
        "russell2000": "russell2000_tickers.csv",
        "russell3000": "russell3000_tickers.csv",
    }.get(universe.lower(), "sp500_tickers.csv")
    return os.path.join(project_root, "output", safe_name)


def _get_headers():
    """Headers realistas para evitar bloqueos de scraping."""
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }


def _get_with_retry(url: str, timeout: int = 20, attempts: int = 3, backoff: float = 2.0, headers: dict | None = None) -> requests.Response | None:
    """Wrapper around requests.get with exponential backoff and logging on failure."""
    for attempt in range(attempts):
        try:
            resp = requests.get(url, headers=headers or _get_headers(), timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as e:
            logger.warning("Request to %s failed (attempt %d/%d): %s", url, attempt + 1, attempts, e)
            if attempt < attempts - 1:
                sleep_time = backoff ** (attempt + 1)
                time.sleep(sleep_time)
    return None


def _fetch_sp500_from_slickcharts(timeout: int = 20) -> list[str] | None:
    """
    Fuente principal recomendada: Slickcharts (muy estable y limpia para S&P 500).
    https://slickcharts.com/sp500
    """
    url = "https://slickcharts.com/sp500"
    resp = _get_with_retry(url, timeout=timeout)
    if resp is None:
        return None
    try:
        # Slickcharts suele tener la tabla principal como la primera o con id 'constituents'
        tables = pd.read_html(StringIO(resp.text))
        # Buscamos la tabla que tenga la columna 'Symbol'
        for table in tables:
            cols = [str(c).strip() for c in table.columns]
            if "Symbol" in cols:
                tickers = table["Symbol"].dropna().astype(str).str.strip().tolist()
                if len(tickers) > 400:  # Sanity check: S&P 500 real tiene ~503
                    return tickers
        return None
    except Exception as e:
        logger.warning("_fetch_sp500_from_slickcharts parsing failed: %s", e)
        return None


def _fetch_sp500_from_wikipedia(timeout: int = 20) -> list[str] | None:
    """
    Fuente secundaria: Wikipedia (mejorada con headers y parsers múltiples).
    """
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    resp = _get_with_retry(url, timeout=timeout)
    if resp is None:
        return None
    try:
        # Intentamos varios parsers (html5lib es más tolerante)
        for flavor in ["html5lib", "lxml", None]:
            try:
                tables = pd.read_html(StringIO(resp.text), flavor=flavor)
                if tables:
                    df = tables[0]
                    # La primera tabla suele tener la columna "Symbol"
                    if "Symbol" in df.columns:
                        tickers = (
                            df["Symbol"]
                            .dropna()
                            .astype(str)
                            .str.strip()
                            .str.upper()
                            .tolist()
                        )
                        if len(tickers) > 400:
                            return tickers
            except Exception as e:
                logger.warning("_fetch_sp500_from_wikipedia parser %s failed: %s", flavor, e)
                continue
        return None
    except Exception as e:
        logger.warning("_fetch_sp500_from_wikipedia failed: %s", e)
        return None


def _fetch_sp500_from_github(timeout: int = 20) -> list[str] | None:
    """
    Fuente terciaria confiable: datasets públicos en GitHub (raw CSV).
    Muy estable y mantenido por la comunidad.
    """
    # Uno de los repos más usados y estables para constituents actuales
    url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
    try:
        resp = requests.get(url, headers=_get_headers(), timeout=timeout)
        resp.raise_for_status()
        df = pd.read_csv(StringIO(resp.text))
        if "Symbol" in df.columns:
            tickers = (
                df["Symbol"]
                .dropna()
                .astype(str)
                .str.strip()
                .str.upper()
                .tolist()
            )
            if len(tickers) > 400:
                return tickers
        return None
    except Exception as e:
        logger.warning("_fetch_sp500_from_github failed: %s", e)
        return None


def _fetch_sp500_from_barchart(timeout: int = 25) -> list[str] | None:
    """
    Fuente adicional: Barchart (tabla de constituents del S&P 500).
    """
    url = "https://www.barchart.com/stocks/indices/spx/constituents"
    try:
        resp = requests.get(url, headers=_get_headers(), timeout=timeout)
        resp.raise_for_status()
        tables = pd.read_html(StringIO(resp.text))
        for table in tables:
            cols = [str(c).strip().lower() for c in table.columns]
            if "symbol" in cols:
                col_name = table.columns[cols.index("symbol")]
                tickers = (
                    table[col_name]
                    .dropna()
                    .astype(str)
                    .str.strip()
                    .str.upper()
                    .tolist()
                )
                if len(tickers) > 400:
                    return tickers
        return None
    except Exception as e:
        logger.warning("_fetch_sp500_from_barchart failed: %s", e)
        return None


def _fetch_sp500_from_github_steven(timeout: int = 20) -> list[str] | None:
    """
    Fuente GitHub adicional: stevenruidigao/sp500 (comúnmente mantenida).
    """
    url = "https://raw.githubusercontent.com/stevenruidigao/sp500/master/sp500.csv"
    try:
        resp = requests.get(url, headers=_get_headers(), timeout=timeout)
        resp.raise_for_status()
        df = pd.read_csv(StringIO(resp.text))
        # Este repo suele usar columna "Symbol" o "Ticker"
        for col in df.columns:
            if str(col).lower() in ("symbol", "ticker"):
                tickers = (
                    df[col]
                    .dropna()
                    .astype(str)
                    .str.strip()
                    .str.upper()
                    .tolist()
                )
                if len(tickers) > 400:
                    return tickers
        return None
    except Exception as e:
        logger.warning("_fetch_sp500_from_github_steven failed: %s", e)
        return None


def _fetch_sp500_from_github_saikr(timeout: int = 20) -> list[str] | None:
    """
    Fuente GitHub adicional: saikr789 (lista SP500_TICKERS).
    """
    url = "https://raw.githubusercontent.com/saikr789/stock-market-prediction/master/data/SP500_TICKERS.csv"
    resp = _get_with_retry(url, timeout=timeout)
    if resp is None:
        return None
    try:
        df = pd.read_csv(StringIO(resp.text))
        # Este archivo suele tener la columna "0" o "Symbol"
        for col in df.columns:
            col_lower = str(col).lower()
            if col_lower in ("symbol", "ticker", "0"):
                tickers = (
                    df[col]
                    .dropna()
                    .astype(str)
                    .str.strip()
                    .str.upper()
                    .tolist()
                )
                if len(tickers) > 400:
                    return tickers
        return None
    except Exception as e:
        logger.warning("_fetch_sp500_from_github_saikr parsing failed: %s", e)
        return None


def get_sp500_tickers(use_cache: bool = True) -> list[str]:
    """
    Devuelve la lista actual de tickers del S&P 500 (siempre única y limpia).

    Estrategia "todas las fuentes posibles":
    1. Caché local (7 días) - rápido
    2. Slickcharts (principal, muy estable)
    3. Barchart
    4. Wikipedia (mejorada con headers + múltiples parsers)
    5. Múltiples repos de GitHub (datasets, stevenruidigao, saikr789, etc.)
    6. Lista de respaldo grande y limpia (~362 tickers únicos)

    Intenta TODAS las fuentes públicas razonables antes de caer en el fallback.
    """
    # 1. Caché
    cache_path = _get_cache_path("sp500")
    if use_cache and os.path.exists(cache_path):
        mod_time = datetime.fromtimestamp(os.path.getmtime(cache_path))
        if datetime.now() - mod_time < timedelta(days=CACHE_DAYS):
            df = pd.read_csv(cache_path)
            tickers = df["ticker"].dropna().astype(str).str.strip().unique().tolist()
            return sorted(tickers)  # orden consistente

    print("Descargando lista actualizada del S&P 500 (todas las fuentes posibles)...", end=" ", flush=True)

    tickers = None
    source = None

    # Lista de todas las fuentes posibles (ordenadas por confiabilidad + velocidad)
    sources = [
        ("Slickcharts", _fetch_sp500_from_slickcharts),
        ("Barchart", _fetch_sp500_from_barchart),
        ("Wikipedia", _fetch_sp500_from_wikipedia),
        ("GitHub (datasets)", _fetch_sp500_from_github),
        ("GitHub (stevenruidigao)", _fetch_sp500_from_github_steven),
        ("GitHub (saikr789)", _fetch_sp500_from_github_saikr),
    ]

    for name, fetch_func in sources:
        try:
            tickers = fetch_func()
            if tickers and len(tickers) > 400:
                source = name
                break
        except Exception as e:
            logger.warning("Source %s raised unexpected error: %s", name, e)
            continue

    if tickers:
        # Limpiar y deduplicar
        clean = sorted(list(set(str(t).strip().upper() for t in tickers if t and str(t).strip())))

        # Guardar en caché (usa la ruta robusta)
        cache_path = _get_cache_path("sp500")
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        pd.DataFrame({"ticker": clean}).to_csv(cache_path, index=False)

        # TASK-201: write json cache for fallback observability
        os.makedirs(DATA_CACHE_DIR, exist_ok=True)
        json_cache = _json_cache_path("sp500")
        with open(json_cache, "w", encoding="utf-8") as f:
            json.dump({"date": datetime.now().isoformat(), "tickers": clean, "source": source}, f, indent=2)

        try:
            print(f"✓ {len(clean)} tickers ({source})")
        except UnicodeEncodeError:
            print(f"[OK] {len(clean)} tickers ({source})")

        return clean

    # TASK-201: try json cache fallback before hardcoded
    json_cache = _json_cache_path("sp500")
    if os.path.exists(json_cache):
        try:
            with open(json_cache, "r", encoding="utf-8") as f:
                data = json.load(f)
            cached_date = data.get("date", "unknown")
            cached_n = len(data.get("tickers", []))
            logger.warning("using cached universe from %s (%d tickers) — all live sources failed", cached_date, cached_n)
            print(f"WARNING: using cached universe from {cached_date} ({cached_n} tickers) — all live sources failed")
            return data.get("tickers", [])
        except Exception as e:
            logger.warning("Failed to load universe cache: %s", e)

    # Último recurso: Fallback (nunca falla)
    try:
        print("✗ Error en TODAS las fuentes online")
    except UnicodeEncodeError:
        print("[ERR] Error en TODAS las fuentes online")

    print("Usando lista de respaldo grande y limpia (~362 tickers únicos).")
    return get_fallback_sp500_tickers()


def get_fallback_sp500_tickers() -> list[str]:
    """Lista de respaldo grande y limpia (362 tickers unicos, 2025-2026).
    Deduplicada preservando orden aproximado de capitalizacion.
    Se usa cuando falla la descarga de Wikipedia.
    """
    return [
        "AAPL",
        "MSFT",
        "NVDA",
        "AMZN",
        "GOOGL",
        "GOOG",
        "META",
        "AVGO",
        "TSLA",
        "AMD",
        "INTC",
        "QCOM",
        "TXN",
        "AMAT",
        "LRCX",
        "KLAC",
        "SNPS",
        "CDNS",
        "ASML",
        "MU",
        "ARM",
        "CRWD",
        "PANW",
        "SNOW",
        "DDOG",
        "NET",
        "PLTR",
        "ZS",
        "MDB",
        "DOCU",
        "OKTA",
        "NOW",
        "TEAM",
        "ADBE",
        "CRM",
        "ORCL",
        "IBM",
        "CSCO",
        "ACN",
        "CTSH",
        "IT",
        "WDAY",
        "ANET",
        "FTNT",
        "NFLX",
        "DIS",
        "CMCSA",
        "VZ",
        "T",
        "TMUS",
        "CHTR",
        "PARA",
        "WBD",
        "ROKU",
        "SPOT",
        "UBER",
        "LYFT",
        "ABNB",
        "DASH",
        "COIN",
        "HOOD",
        "RBLX",
        "DKNG",
        "COST",
        "WMT",
        "TGT",
        "HD",
        "LOW",
        "NKE",
        "SBUX",
        "MCD",
        "YUM",
        "CMG",
        "DPZ",
        "TJX",
        "ROST",
        "DG",
        "DLTR",
        "KR",
        "WBA",
        "CVS",
        "EL",
        "CL",
        "KMB",
        "GIS",
        "K",
        "HSY",
        "PEP",
        "KO",
        "MDLZ",
        "KDP",
        "STZ",
        "BF-B",
        "UNH",
        "JNJ",
        "LLY",
        "ABBV",
        "MRK",
        "PFE",
        "TMO",
        "DHR",
        "ABT",
        "BMY",
        "AMGN",
        "GILD",
        "ISRG",
        "SYK",
        "BSX",
        "MDT",
        "EW",
        "DXCM",
        "BIIB",
        "REGN",
        "VRTX",
        "ILMN",
        "HUM",
        "CI",
        "ELV",
        "CNC",
        "MOH",
        "WAT",
        "ZTS",
        "IDXX",
        "BRK-B",
        "JPM",
        "V",
        "MA",
        "AXP",
        "GS",
        "MS",
        "BAC",
        "WFC",
        "C",
        "BLK",
        "SCHW",
        "SPGI",
        "MCO",
        "ICE",
        "CME",
        "COF",
        "USB",
        "PNC",
        "TFC",
        "BK",
        "STT",
        "AIG",
        "MET",
        "PRU",
        "AFL",
        "ALL",
        "TRV",
        "PGR",
        "CB",
        "MMC",
        "AON",
        "AJG",
        "CAT",
        "DE",
        "HON",
        "UPS",
        "BA",
        "LMT",
        "RTX",
        "NOC",
        "GD",
        "GE",
        "MMM",
        "ITW",
        "ETN",
        "EMR",
        "ROK",
        "PH",
        "CMI",
        "PCAR",
        "IR",
        "OTIS",
        "CARR",
        "TT",
        "JCI",
        "FAST",
        "GWW",
        "URI",
        "PWR",
        "EME",
        "FIX",
        "XOM",
        "CVX",
        "COP",
        "EOG",
        "MPC",
        "PSX",
        "VLO",
        "SLB",
        "BKR",
        "HAL",
        "OXY",
        "WMB",
        "KMI",
        "OKE",
        "MRO",
        "FANG",
        "APA",
        "DVN",
        "HES",
        "CTRA",
        "LIN",
        "APD",
        "ECL",
        "SHW",
        "FCX",
        "NEM",
        "DOW",
        "DD",
        "PPG",
        "LYB",
        "ALB",
        "MOS",
        "AMT",
        "PLD",
        "EQIX",
        "CCI",
        "PSA",
        "O",
        "SPG",
        "AVB",
        "EQR",
        "DLR",
        "NEE",
        "DUK",
        "SO",
        "D",
        "EXC",
        "AEP",
        "SRE",
        "PEG",
        "ED",
        "XEL",
        "WEC",
        "AWK",
        "F",
        "GM",
        "RIVN",
        "LCID",
        "PCG",
        "PM",
        "MO",
        "CLX",
        "CHD",
        "MKC",
        "HRL",
        "SJM",
        "CPB",
        "CAG",
        "BG",
        "ADM",
        "CTVA",
        "CF",
        "FMC",
        "IFF",
        "EMN",
        "CE",
        "SEE",
        "PKG",
        "AVY",
        "WRK",
        "IP",
        "NUE",
        "STLD",
        "RS",
        "X",
        "CLF",
        "AA",
        "KALU",
        "CMC",
        "PHM",
        "DHI",
        "LEN",
        "TOL",
        "NVR",
        "MTH",
        "KBH",
        "TMHC",
        "MAR",
        "HLT",
        "H",
        "IHG",
        "WH",
        "CHH",
        "BYD",
        "WYNN",
        "MGM",
        "LVS",
        "BKNG",
        "EXPE",
        "TRIP",
        "SABR",
        "RCL",
        "CCL",
        "NCLH",
        "ALK",
        "DAL",
        "UAL",
        "LUV",
        "JBLU",
        "AAL",
        "FDX",
        "EXPD",
        "CHRW",
        "JBHT",
        "ODFL",
        "SAIA",
        "XPO",
        "TER",
        "ON",
        "MPWR",
        "SWKS",
        "QRVO",
        "COHR",
        "AEIS",
        "MTSI",
        "DIOD",
        "ADSK",
        "ANSS",
        "PTC",
        "SSNC",
        "TYL",
        "MANH",
        "PCTY",
        "PAYC",
        "BR",
        "PYPL",
        "SQ",
        "FIS",
        "FISV",
        "GPN",
        "WU",
        "EEFT",
        "HOLX",
        "RMD",
        "STE",
        "PODD",
        "ALGN",
        "TFX",
        "COO",
        "HSIC",
        "PDCO",
        "PG",
        "HII",
        "LDOS",
        "CACI",
        "SAIC",
        "LEIDOS",
        "FLIR",
        "KTOS",
        "AVAV",
        "MRVL",
        "NXPI",
        "MCHP",
        "ADI",
        "STM",
        "GFS",
        "UMC"
    ]


# ============================================================
# NEW: Nasdaq-100 and Dow Jones 30 support
# ============================================================

def _fetch_nasdaq100_from_slickcharts(timeout: int = 20) -> list[str] | None:
    """Fuente principal para Nasdaq-100: https://slickcharts.com/nasdaq100"""
    url = "https://slickcharts.com/nasdaq100"
    resp = _get_with_retry(url, timeout=timeout)
    if resp is None:
        return None
    try:
        tables = pd.read_html(StringIO(resp.text))
        for table in tables:
            cols = [str(c).strip() for c in table.columns]
            if "Symbol" in cols:
                tickers = table["Symbol"].dropna().astype(str).str.strip().tolist()
                if len(tickers) > 90:  # Nasdaq-100 ~100
                    return tickers
        return None
    except Exception as e:
        logger.warning("_fetch_nasdaq100_from_slickcharts parsing failed: %s", e)
        return None


def _fetch_nasdaq100_from_wikipedia(timeout: int = 20) -> list[str] | None:
    """Wikipedia Nasdaq-100"""
    url = "https://en.wikipedia.org/wiki/Nasdaq-100"
    resp = _get_with_retry(url, timeout=timeout)
    if resp is None:
        return None
    try:
        for flavor in ["html5lib", "lxml", None]:
            try:
                tables = pd.read_html(StringIO(resp.text), flavor=flavor)
                if tables:
                    for df in tables:
                        if "Ticker" in df.columns or "Symbol" in df.columns:
                            col = "Ticker" if "Ticker" in df.columns else "Symbol"
                            tickers = df[col].dropna().astype(str).str.strip().str.upper().tolist()
                            if len(tickers) > 90:
                                return tickers
            except Exception as e:
                logger.warning("_fetch_nasdaq100_from_wikipedia parser %s failed: %s", flavor, e)
                continue
        return None
    except Exception as e:
        logger.warning("_fetch_nasdaq100_from_wikipedia failed: %s", e)
        return None


def get_nasdaq100_tickers(use_cache: bool = True) -> list[str]:
    """Devuelve tickers del Nasdaq-100 con cache y múltiples fuentes."""
    cache_path = _get_cache_path("nasdaq100")
    if use_cache and os.path.exists(cache_path):
        mod_time = datetime.fromtimestamp(os.path.getmtime(cache_path))
        if datetime.now() - mod_time < timedelta(days=CACHE_DAYS):
            df = pd.read_csv(cache_path)
            return sorted(df["ticker"].dropna().astype(str).str.strip().unique().tolist())

    print("Descargando lista actualizada del Nasdaq-100 ...", end=" ", flush=True)
    tickers = None
    source = None

    sources = [
        ("Slickcharts", _fetch_nasdaq100_from_slickcharts),
        ("Wikipedia", _fetch_nasdaq100_from_wikipedia),
    ]

    for name, fetch_func in sources:
        try:
            tickers = fetch_func()
            if tickers and len(tickers) > 90:
                source = name
                break
        except Exception as e:
            logger.warning("Source %s raised unexpected error: %s", name, e)
            continue

    if tickers:
        clean = sorted(list(set(str(t).strip().upper() for t in tickers if t and str(t).strip())))
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        pd.DataFrame({"ticker": clean}).to_csv(cache_path, index=False)

        # TASK-201 review fix: extend json cache to nasdaq100
        os.makedirs(DATA_CACHE_DIR, exist_ok=True)
        json_cache = _json_cache_path("nasdaq100")
        with open(json_cache, "w", encoding="utf-8") as f:
            json.dump({"date": datetime.now().isoformat(), "tickers": clean, "source": source}, f, indent=2)

        try:
            print(f"✓ {len(clean)} tickers ({source})")
        except UnicodeEncodeError:
            print(f"[OK] {len(clean)} tickers ({source})")
        return clean

    # TASK-201 review fix: json cache fallback for nasdaq100
    json_cache = _json_cache_path("nasdaq100")
    if os.path.exists(json_cache):
        try:
            with open(json_cache, "r", encoding="utf-8") as f:
                data = json.load(f)
            cached_date = data.get("date", "unknown")
            cached_n = len(data.get("tickers", []))
            logger.warning("using cached universe from %s (%d tickers) — all live sources failed", cached_date, cached_n)
            print(f"WARNING: using cached universe from {cached_date} ({cached_n} tickers) — all live sources failed")
            return data.get("tickers", [])
        except Exception as e:
            logger.warning("Failed to load universe cache: %s", e)

    # Fallback hardcoded Nasdaq-100 (approximate, stable large names as of 2026)
    print("Usando lista de respaldo para Nasdaq-100.")
    return get_fallback_nasdaq100_tickers()


def get_fallback_nasdaq100_tickers() -> list[str]:
    """Fallback list for Nasdaq-100 (approximate large constituents as of 2026)."""
    return sorted(list(set([
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "AVGO", "TSLA", "AMD",
        "INTC", "QCOM", "TXN", "AMAT", "LRCX", "KLAC", "SNPS", "CDNS", "ASML", "MU",
        "ARM", "CRWD", "PANW", "SNOW", "DDOG", "NET", "PLTR", "ZS", "MDB", "DOCU",
        "OKTA", "NOW", "TEAM", "ADBE", "CRM", "ORCL", "IBM", "CSCO", "ANET", "FTNT",
        "NFLX", "DIS", "CMCSA", "VZ", "T", "TMUS", "CHTR", "WBD", "ROKU", "SPOT",
        "UBER", "DASH", "COIN", "COST", "ISRG", "REGN", "VRTX", "GILD", "AMGN", "BIIB",
        "ILMN", "DXCM", "MRNA", "PDD", "JD", "BIDU", "NTES", "BABA", "TSM", "ASML",
        "AVGO", "LRCX", "KLAC", "SNPS", "CDNS", "ANSS", "PTC", "ADSK", "WDAY", "DDOG",
        "CRWD", "PANW", "ZS", "OKTA", "NET", "PLTR", "MDB", "SNOW", "TEAM", "NOW",
        "ADBE", "CRM", "ORCL", "INTU", "ADP", "PAYX", "FISV", "GPN", "SQ", "PYPL",
        "ROKU", "PDD", "JD", "BIDU", "NTES", "BABA", "TSM"
    ])))


def _fetch_dow30_from_slickcharts(timeout: int = 20) -> list[str] | None:
    """Dow Jones 30 from Slickcharts: https://slickcharts.com/dowjones"""
    url = "https://slickcharts.com/dowjones"
    try:
        resp = requests.get(url, headers=_get_headers(), timeout=timeout)
        resp.raise_for_status()
        tables = pd.read_html(StringIO(resp.text))
        for table in tables:
            cols = [str(c).strip() for c in table.columns]
            if "Symbol" in cols:
                tickers = table["Symbol"].dropna().astype(str).str.strip().tolist()
                if len(tickers) > 25:  # Dow has 30
                    return tickers
        return None
    except Exception as e:
        logger.warning("_fetch_dow30_from_slickcharts failed: %s", e)
        return None


def get_dow30_tickers(use_cache: bool = True) -> list[str]:
    """Devuelve los 30 componentes del Dow Jones."""
    cache_path = _get_cache_path("dow30")
    if use_cache and os.path.exists(cache_path):
        mod_time = datetime.fromtimestamp(os.path.getmtime(cache_path))
        if datetime.now() - mod_time < timedelta(days=CACHE_DAYS):
            df = pd.read_csv(cache_path)
            return sorted(df["ticker"].dropna().astype(str).str.strip().unique().tolist())

    print("Descargando lista del Dow Jones 30 ...", end=" ", flush=True)
    tickers = None
    source = None

    sources = [
        ("Slickcharts", _fetch_dow30_from_slickcharts),
    ]

    for name, fetch_func in sources:
        try:
            tickers = fetch_func()
            if tickers and len(tickers) > 25:
                source = name
                break
        except Exception as e:
            logger.warning("Source %s raised unexpected error: %s", name, e)
            continue

    if tickers:
        clean = sorted(list(set(str(t).strip().upper() for t in tickers if t and str(t).strip())))
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        pd.DataFrame({"ticker": clean}).to_csv(cache_path, index=False)

        # TASK-201 round 3: add json cache for dow30 (it resolves via network)
        os.makedirs(DATA_CACHE_DIR, exist_ok=True)
        json_cache = _json_cache_path("dow30")
        with open(json_cache, "w", encoding="utf-8") as f:
            json.dump({"date": datetime.now().isoformat(), "tickers": clean, "source": source}, f, indent=2)

        try:
            print(f"✓ {len(clean)} tickers ({source})")
        except UnicodeEncodeError:
            print(f"[OK] {len(clean)} tickers ({source})")
        return clean

    # TASK-201 round 3: json cache fallback for dow30
    json_cache = _json_cache_path("dow30")
    if os.path.exists(json_cache):
        try:
            with open(json_cache, "r", encoding="utf-8") as f:
                data = json.load(f)
            cached_date = data.get("date", "unknown")
            cached_n = len(data.get("tickers", []))
            logger.warning("using cached universe from %s (%d tickers) — all live sources failed", cached_date, cached_n)
            print(f"WARNING: using cached universe from {cached_date} ({cached_n} tickers) — all live sources failed")
            return data.get("tickers", [])
        except Exception as e:
            logger.warning("Failed to load universe cache: %s", e)

    # Reliable fallback for Dow 30 (as of mid-2026, standard components)
    print("Usando lista de respaldo para Dow 30.")
    return sorted([
        "AAPL", "AMGN", "AMZN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS",
        "DOW", "GS", "HD", "HON", "IBM", "INTC", "JNJ", "JPM", "KO", "MCD",
        "MMM", "MRK", "MSFT", "NKE", "PG", "TRV", "UNH", "V", "VZ", "WMT"
    ])


# ============================================================
# Russell 1000 support - to integrate MANY more acciones (large + mid caps ~1000 total)
# ============================================================

def _fetch_russell1000_from_slickcharts(timeout: int = 25) -> list[str] | None:
    """Slickcharts Russell 1000 if available: https://slickcharts.com/russell1000"""
    url = "https://slickcharts.com/russell1000"
    try:
        resp = requests.get(url, headers=_get_headers(), timeout=timeout)
        resp.raise_for_status()
        tables = pd.read_html(StringIO(resp.text))
        for table in tables:
            cols = [str(c).strip() for c in table.columns]
            if "Symbol" in cols:
                tickers = table["Symbol"].dropna().astype(str).str.strip().tolist()
                if len(tickers) > 800:  # Russell 1000 ~1000
                    return tickers
        return None
    except Exception as e:
        logger.warning("_fetch_russell1000_from_slickcharts failed: %s", e)
        return None


def _fetch_russell1000_from_barchart(timeout: int = 25) -> list[str] | None:
    """Barchart for Russell 1000 constituents."""
    url = "https://www.barchart.com/stocks/indices/russell/rut1000/constituents"
    try:
        resp = requests.get(url, headers=_get_headers(), timeout=timeout)
        resp.raise_for_status()
        tables = pd.read_html(StringIO(resp.text))
        for table in tables:
            cols = [str(c).strip().lower() for c in table.columns]
            if "symbol" in cols:
                col_name = table.columns[cols.index("symbol")]
                tickers = (
                    table[col_name]
                    .dropna()
                    .astype(str)
                    .str.strip()
                    .str.upper()
                    .tolist()
                )
                if len(tickers) > 800:
                    return tickers
        return None
    except Exception as e:
        logger.warning("_fetch_russell1000_from_barchart failed: %s", e)
        return None


# ============================================================
# NASDAQ screener API - universo US completo rankeado por market cap
# (proxy metodológico de los Russell: R1000 = top 1000 por cap,
#  R2000 = puestos 1001-3000, igual que la metodología FTSE Russell)
# ============================================================

_NASDAQ_RANKED_CACHE: list[str] | None = None  # cache en memoria por proceso


def _fetch_us_stocks_ranked_by_marketcap(timeout: int = 60) -> list[str] | None:
    """
    Descarga TODAS las acciones listadas en US (NASDAQ/NYSE/AMEX, ~7000) desde
    la API del screener de NASDAQ, en UNA sola request, y las devuelve
    ordenadas por market cap descendente (formato Yahoo: BRK.B → BRK-B).

    Excluye símbolos no estándar (warrants/units/preferred con ^ o /).
    """
    global _NASDAQ_RANKED_CACHE
    if _NASDAQ_RANKED_CACHE is not None:
        return _NASDAQ_RANKED_CACHE

    url = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=25&offset=0&download=true"
    headers = {
        "User-Agent": _get_headers()["User-Agent"],
        "Accept": "application/json",
        "Origin": "https://www.nasdaq.com",
        "Referer": "https://www.nasdaq.com/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        rows = resp.json().get("data", {}).get("rows", [])
    except Exception as e:
        logger.warning("_fetch_us_stocks_ranked_by_marketcap failed: %s", e)
        return None

    parsed = []
    for row in rows:
        sym = (row.get("symbol") or "").strip().upper()
        cap_raw = (row.get("marketCap") or "").replace(",", "").strip()
        if not sym or not cap_raw:
            continue
        # Solo símbolos comunes (acciones + clases tipo BRK.B); fuera warrants/units/preferred
        if not re.fullmatch(r"[A-Z]{1,5}([.\-/][A-Z])?", sym):
            continue
        try:
            cap = float(cap_raw)
        except ValueError:
            continue
        if cap <= 0:
            continue
        parsed.append((sym.replace(".", "-").replace("/", "-"), cap))

    if len(parsed) < 3500:  # sanity: esperamos ~6500+ con cap
        return None

    parsed.sort(key=lambda x: -x[1])
    # dedup conservando el de mayor cap
    seen, ranked = set(), []
    for sym, _ in parsed:
        if sym not in seen:
            seen.add(sym)
            ranked.append(sym)

    _NASDAQ_RANKED_CACHE = ranked
    return ranked


def _fetch_russell1000_from_nasdaq(timeout: int = 60) -> list[str] | None:
    """Proxy Russell 1000: top 1000 acciones US por market cap."""
    ranked = _fetch_us_stocks_ranked_by_marketcap(timeout=timeout)
    if ranked and len(ranked) >= 3000:
        return ranked[:1000]
    return None


def _fetch_russell2000_from_nasdaq(timeout: int = 60) -> list[str] | None:
    """Proxy Russell 2000: puestos 1001-3000 por market cap (small caps)."""
    ranked = _fetch_us_stocks_ranked_by_marketcap(timeout=timeout)
    if ranked and len(ranked) >= 3000:
        return ranked[1000:3000]
    return None


def get_russell1000_tickers(use_cache: bool = True) -> list[str]:
    """Devuelve tickers del Russell 1000 (large + mid cap ~1000 US stocks)."""
    cache_path = _get_cache_path("russell1000")
    if use_cache and os.path.exists(cache_path):
        mod_time = datetime.fromtimestamp(os.path.getmtime(cache_path))
        if datetime.now() - mod_time < timedelta(days=CACHE_DAYS):
            df = pd.read_csv(cache_path)
            return sorted(df["ticker"].dropna().astype(str).str.strip().unique().tolist())

    print("Descargando lista actualizada del Russell 1000 (más acciones mid/large)...", end=" ", flush=True)
    tickers = None
    source = None

    sources = [
        ("NASDAQ marketcap top-1000", _fetch_russell1000_from_nasdaq),
        ("Slickcharts", _fetch_russell1000_from_slickcharts),
        ("Barchart", _fetch_russell1000_from_barchart),
    ]

    for name, fetch_func in sources:
        try:
            tickers = fetch_func()
            if tickers and len(tickers) > 800:
                source = name
                break
        except Exception as e:
            logger.warning("Source %s raised unexpected error: %s", name, e)
            continue

    if tickers:
        clean = sorted(list(set(str(t).strip().upper() for t in tickers if t and str(t).strip())))
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        pd.DataFrame({"ticker": clean}).to_csv(cache_path, index=False)

        # TASK-201 round 3: add json cache for russell1000 (resolves via network)
        os.makedirs(DATA_CACHE_DIR, exist_ok=True)
        json_cache = _json_cache_path("russell1000")
        with open(json_cache, "w", encoding="utf-8") as f:
            json.dump({"date": datetime.now().isoformat(), "tickers": clean, "source": source}, f, indent=2)

        try:
            print(f"✓ {len(clean)} tickers ({source})")
        except UnicodeEncodeError:
            print(f"[OK] {len(clean)} tickers ({source})")
        return clean

    # TASK-201 round 3: json cache fallback for russell1000
    json_cache = _json_cache_path("russell1000")
    if os.path.exists(json_cache):
        try:
            with open(json_cache, "r", encoding="utf-8") as f:
                data = json.load(f)
            cached_date = data.get("date", "unknown")
            cached_n = len(data.get("tickers", []))
            logger.warning("using cached universe from %s (%d tickers) — all live sources failed", cached_date, cached_n)
            print(f"WARNING: using cached universe from {cached_date} ({cached_n} tickers) — all live sources failed")
            return data.get("tickers", [])
        except Exception as e:
            logger.warning("Failed to load universe cache: %s", e)

    # Fallback: use a broad list based on sp500 fallback + common mids (expandable)
    print("Usando lista de respaldo amplia para Russell 1000 (combinando SP500 + mids comunes).")
    sp_fallback = get_fallback_sp500_tickers()
    # Add common mid-cap names not always in SP500 (approximate, for robustness)
    extra_mids = [
        "AAPL","MSFT","NVDA","AMZN","GOOGL","META","AVGO","TSLA","AMD","INTC",
        "MRVL","NXPI","MCHP","ADI","ON","MPWR","SWKS","QRVO","COHR","AEIS",
        "MTSI","DIOD","TER","ONTO","AMAT","LRCX","KLAC","SNPS","CDNS","ASML",
        "MU","ARM","CRWD","PANW","SNOW","DDOG","NET","PLTR","ZS","MDB",
        "DOCU","OKTA","NOW","TEAM","ADBE","CRM","ORCL","IBM","CSCO","ANET",
        "FTNT","NFLX","DIS","CMCSA","VZ","T","TMUS","CHTR","WBD","ROKU",
        "SPOT","UBER","DASH","COIN","HOOD","RBLX","DKNG","COST","WMT","TGT",
        "HD","LOW","NKE","SBUX","MCD","YUM","CMG","DPZ","TJX","ROST",
        "DG","DLTR","KR","WBA","CVS","EL","CL","KMB","GIS","K","HSY",
        "PEP","KO","MDLZ","KDP","STZ","BF-B","UNH","JNJ","LLY","ABBV",
        "MRK","PFE","TMO","DHR","ABT","BMY","AMGN","GILD","ISRG","SYK",
        "BSX","MDT","EW","DXCM","BIIB","REGN","VRTX","ILMN","HUM","CI",
        "ELV","CNC","MOH","WAT","ZTS","IDXX","BRK-B","JPM","V","MA",
        "AXP","GS","MS","BAC","WFC","C","BLK","SCHW","SPGI","MCO",
        "ICE","CME","COF","USB","PNC","TFC","BK","STT","AIG","MET",
        "PRU","AFL","ALL","TRV","PGR","CB","MMC","AON","AJG","CAT",
        "DE","HON","UPS","BA","LMT","RTX","NOC","GD","GE","MMM",
        "ITW","ETN","EMR","ROK","PH","CMI","PCAR","IR","OTIS","CARR",
        "TT","JCI","FAST","GWW","URI","PWR","EME","FIX","XOM","CVX",
        "COP","EOG","MPC","PSX","VLO","SLB","BKR","HAL","OXY","WMB",
        "KMI","OKE","MRO","FANG","APA","DVN","HES","CTRA","LIN","APD",
        "ECL","SHW","FCX","NEM","DOW","DD","PPG","LYB","ALB","MOS",
        "AMT","PLD","EQIX","CCI","PSA","O","SPG","AVB","EQR","DLR",
        "NEE","DUK","SO","D","EXC","AEP","SRE","PEG","ED","XEL",
        "WEC","AWK","F","GM","RIVN","LCID","PCG","PM","MO","CLX",
        "CHD","MKC","HRL","SJM","CPB","CAG","BG","ADM","CTVA","CF",
        "FMC","IFF","EMN","CE","SEE","PKG","AVY","WRK","IP","NUE",
        "STLD","RS","X","CLF","AA","KALU","CMC","PHM","DHI","LEN",
        "TOL","NVR","MTH","KBH","TMHC","MAR","HLT","H","IHG","WH",
        "CHH","BYD","WYNN","MGM","LVS","BKNG","EXPE","TRIP","SABR","RCL",
        "CCL","NCLH","ALK","DAL","UAL","LUV","JBLU","AAL","FDX","EXPD",
        "CHRW","JBHT","ODFL","SAIA","XPO","TER","ON","MPWR","SWKS","QRVO",
        "COHR","AEIS","MTSI","DIOD","ADSK","ANSS","PTC","SSNC","TYL","MANH",
        "PCTY","PAYC","BR","PYPL","SQ","FIS","GPN","WU","EEFT","HOLX",
        "RMD","STE","PODD","ALGN","TFX","COO","HSIC","PDCO","PG","HII",
        "LDOS","CACI","SAIC","KTOS","AVAV","MRVL","NXPI","MCHP","ADI","STM",
        "GFS","UMC","QCOM","TXN","AMAT","LRCX","KLAC","SNPS","CDNS","ASML",
        "MU","ARM","CRWD","PANW","SNOW","DDOG","NET","PLTR","ZS","MDB",
        "DOCU","OKTA","NOW","TEAM","ADBE","CRM","ORCL","IBM","CSCO","ANET",
        "FTNT","NFLX","DIS","CMCSA","VZ","T","TMUS","CHTR","WBD","ROKU",
        "SPOT","UBER","DASH","COIN","HOOD","RBLX","DKNG","COST","WMT","TGT",
        "HD","LOW","NKE","SBUX","MCD","YUM","CMG","DPZ","TJX","ROST",
        "DG","DLTR","KR","WBA","CVS","EL","CL","KMB","GIS","K","HSY",
        "PEP","KO","MDLZ","KDP","STZ","BF-B","UNH","JNJ","LLY","ABBV",
        "MRK","PFE","TMO","DHR","ABT","BMY","AMGN","GILD","ISRG","SYK",
        "BSX","MDT","EW","DXCM","BIIB","REGN","VRTX","ILMN","HUM","CI",
        "ELV","CNC","MOH","WAT","ZTS","IDXX","BRK-B","JPM","V","MA",
        "AXP","GS","MS","BAC","WFC","C","BLK","SCHW","SPGI","MCO",
        "ICE","CME","COF","USB","PNC","TFC","BK","STT","AIG","MET",
        "PRU","AFL","ALL","TRV","PGR","CB","MMC","AON","AJG","CAT",
        "DE","HON","UPS","BA","LMT","RTX","NOC","GD","GE","MMM",
        "ITW","ETN","EMR","ROK","PH","CMI","PCAR","IR","OTIS","CARR",
        "TT","JCI","FAST","GWW","URI","PWR","EME","FIX","XOM","CVX",
        "COP","EOG","MPC","PSX","VLO","SLB","BKR","HAL","OXY","WMB",
        "KMI","OKE","MRO","FANG","APA","DVN","HES","CTRA","LIN","APD",
        "ECL","SHW","FCX","NEM","DOW","DD","PPG","LYB","ALB","MOS",
        "AMT","PLD","EQIX","CCI","PSA","O","SPG","AVB","EQR","DLR",
        "NEE","DUK","SO","D","EXC","AEP","SRE","PEG","ED","XEL",
        "WEC","AWK","F","GM","RIVN","LCID","PCG","PM","MO","CLX",
        "CHD","MKC","HRL","SJM","CPB","CAG","BG","ADM","CTVA","CF",
        "FMC","IFF","EMN","CE","SEE","PKG","AVY","WRK","IP","NUE",
        "STLD","RS","X","CLF","AA","KALU","CMC","PHM","DHI","LEN",
        "TOL","NVR","MTH","KBH","TMHC","MAR","HLT","H","IHG","WH",
        "CHH","BYD","WYNN","MGM","LVS","BKNG","EXPE","TRIP","SABR","RCL",
        "CCL","NCLH","ALK","DAL","UAL","LUV","JBLU","AAL","FDX","EXPD",
        "CHRW","JBHT","ODFL","SAIA","XPO","TER","ON","MPWR","SWKS","QRVO",
        "COHR","AEIS","MTSI","DIOD","ADSK","ANSS","PTC","SSNC","TYL","MANH",
        "PCTY","PAYC","BR","PYPL","SQ","FIS","GPN","WU","EEFT","HOLX",
        "RMD","STE","PODD","ALGN","TFX","COO","HSIC","PDCO","PG","HII",
        "LDOS","CACI","SAIC","KTOS","AVAV"
    ]
    combined = list(set(sp_fallback + extra_mids))
    return sorted(combined)[:1100]  # cap reasonably ~1000+


# ============================================================
# Russell 2000 support - small caps for even broader "más acciones"
# ============================================================

def _fetch_russell2000_from_slickcharts(timeout: int = 25) -> list[str] | None:
    """Slickcharts Russell 2000: https://slickcharts.com/russell2000"""
    url = "https://slickcharts.com/russell2000"
    resp = _get_with_retry(url, timeout=timeout)
    if resp is None:
        return None
    try:
        tables = pd.read_html(StringIO(resp.text))
        for table in tables:
            cols = [str(c).strip() for c in table.columns]
            if "Symbol" in cols:
                tickers = table["Symbol"].dropna().astype(str).str.strip().tolist()
                if len(tickers) > 1500:  # Russell 2000 ~2000
                    return tickers
        return None
    except Exception as e:
        logger.warning("_fetch_russell2000_from_slickcharts parsing failed: %s", e)
        return None


def _fetch_russell2000_from_barchart(timeout: int = 25) -> list[str] | None:
    """Barchart Russell 2000 constituents."""
    url = "https://www.barchart.com/stocks/indices/russell/rut2000/constituents"
    resp = _get_with_retry(url, timeout=timeout)
    if resp is None:
        return None
    try:
        tables = pd.read_html(StringIO(resp.text))
        for table in tables:
            cols = [str(c).strip().lower() for c in table.columns]
            if "symbol" in cols:
                col_name = table.columns[cols.index("symbol")]
                tickers = (
                    table[col_name]
                    .dropna()
                    .astype(str)
                    .str.strip()
                    .str.upper()
                    .tolist()
                )
                if len(tickers) > 1500:
                    return tickers
        return None
    except Exception as e:
        logger.warning("_fetch_russell2000_from_barchart parsing failed: %s", e)
        return None


def get_russell2000_tickers(use_cache: bool = True) -> list[str]:
    """Devuelve tickers del Russell 2000 (small caps ~2000 stocks)."""
    cache_path = _get_cache_path("russell2000")
    if use_cache and os.path.exists(cache_path):
        mod_time = datetime.fromtimestamp(os.path.getmtime(cache_path))
        if datetime.now() - mod_time < timedelta(days=CACHE_DAYS):
            df = pd.read_csv(cache_path)
            return sorted(df["ticker"].dropna().astype(str).str.strip().unique().tolist())

    print("Descargando lista actualizada del Russell 2000 (small caps para más acciones)...", end=" ", flush=True)
    tickers = None
    source = None

    sources = [
        ("NASDAQ marketcap 1001-3000", _fetch_russell2000_from_nasdaq),
        ("Slickcharts", _fetch_russell2000_from_slickcharts),
        ("Barchart", _fetch_russell2000_from_barchart),
    ]

    for name, fetch_func in sources:
        try:
            tickers = fetch_func()
            if tickers and len(tickers) > 1500:
                source = name
                break
        except Exception as e:
            logger.warning("Source %s raised unexpected error: %s", name, e)
            continue

    if tickers:
        clean = sorted(list(set(str(t).strip().upper() for t in tickers if t and str(t).strip())))
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        pd.DataFrame({"ticker": clean}).to_csv(cache_path, index=False)

        # TASK-201 review fix: extend json cache to russell2000
        os.makedirs(DATA_CACHE_DIR, exist_ok=True)
        json_cache = _json_cache_path("russell2000")
        with open(json_cache, "w", encoding="utf-8") as f:
            json.dump({"date": datetime.now().isoformat(), "tickers": clean, "source": source}, f, indent=2)

        try:
            print(f"✓ {len(clean)} tickers ({source})")
        except UnicodeEncodeError:
            print(f"[OK] {len(clean)} tickers ({source})")
        return clean

    # TASK-201 review fix: json cache fallback for russell2000
    json_cache = _json_cache_path("russell2000")
    if os.path.exists(json_cache):
        try:
            with open(json_cache, "r", encoding="utf-8") as f:
                data = json.load(f)
            cached_date = data.get("date", "unknown")
            cached_n = len(data.get("tickers", []))
            logger.warning("using cached universe from %s (%d tickers) — all live sources failed", cached_date, cached_n)
            print(f"WARNING: using cached universe from {cached_date} ({cached_n} tickers) — all live sources failed")
            return data.get("tickers", [])
        except Exception as e:
            logger.warning("Failed to load universe cache: %s", e)

    # Fallback: broad small/mid cap names (expanded to make 'all' wider even on fallback; real fetches preferred)
    print("Usando lista de respaldo AMPLIA para Russell 2000 (small/mid caps + SP500 para universo mas amplio).")
    sp_fb = get_fallback_sp500_tickers()
    r2k_fallback = sp_fb + [
        "AA", "AAL", "AAPL", "ABBV", "ABNB", "ABT", "ACN", "ADBE", "ADI", "ADM", "ADP", "ADSK", "AEE", "AEP", "AES",
        "AFL", "AIG", "AIZ", "AJG", "AKAM", "ALB", "ALGN", "ALK", "ALL", "ALNY", "AMAT", "AMCR", "AMD", "AME", "AMGN",
        "AMT", "AMZN", "ANET", "ANSS", "AON", "AOS", "APA", "APD", "APH", "APTV", "ARE", "ATO", "AVB", "AVGO", "AVY",
        "AWK", "AXP", "AZO", "BA", "BAC", "BAX", "BBY", "BDX", "BEN", "BF-B", "BIIB", "BIO", "BK", "BKNG", "BKR",
        "BLK", "BMY", "BR", "BRK-B", "BRO", "BSX", "BWA", "BXP", "C", "CAG", "CAH", "CARR", "CAT", "CB", "CBOE", "CBRE",
        "CCI", "CCL", "CDNS", "CE", "CEG", "CF", "CFG", "CHD", "CHRW", "CI", "CINF", "CL", "CLX", "CMA", "CMCSA", "CME",
        "CMG", "CMI", "CMS", "CNC", "CNP", "COF", "COIN", "COST", "CPB", "CPRT", "CPT", "CRL", "CRM", "CSCO", "CSX",
        "CTAS", "CTLT", "CTRA", "CTSH", "CTVA", "CVS", "CVX", "CZR", "D", "DAL", "DD", "DE", "DFS", "DG", "DGX", "DHI",
        "DHR", "DIS", "DISH", "DLR", "DLTR", "DOV", "DOW", "DPZ", "DRI", "DTE", "DUK", "DVA", "DVN", "DXCM", "EA", "EBAY",
        "ECL", "ED", "EFX", "EG", "EIX", "EL", "ELV", "EMN", "EMR", "ENPH", "EOG", "EPAM", "EQIX", "EQR", "EQT", "ES",
        "ESS", "ETN", "ETR", "ETSY", "EVRG", "EW", "EXC", "EXPD", "EXPE", "EXR", "F", "FANG", "FAST", "FCX", "FDS",
        "FDX", "FE", "FFIV", "FIS", "FISV", "FITB", "FLIR", "FMC", "FOX", "FOXA", "FRC", "FRT", "FTNT", "FTV", "GD",
        "GE", "GEHC", "GEN", "GILD", "GIS", "GL", "GLW", "GM", "GPC", "GPN", "GRMN", "GS", "GWW", "HAL", "HAS", "HBAN",
        "HCA", "HD", "HES", "HIG", "HII", "HLT", "HOLX", "HON", "HPE", "HPQ", "HRL", "HSIC", "HST", "HSY", "HUBB",
        "HUM", "HWM", "IBM", "ICE", "IDXX", "IEX", "IFF", "ILMN", "INCY", "INTC", "INTU", "INVH", "IP", "IPG", "IQV",
        "IR", "IRM", "ISRG", "IT", "ITW", "IVZ", "JBHT", "JBLU", "JCI", "JKHY", "JNJ", "JNPR", "JPM", "JWN", "K", "KDP",
        "KEY", "KEYS", "KHC", "KIM", "KLAC", "KMB", "KMI", "KMX", "KO", "KR", "L", "LDOS", "LEN", "LH", "LHX", "LIN",
        "LKQ", "LMT", "LNC", "LNT", "LOW", "LRCX", "LUMN", "LUV", "LVS", "LW", "LYB", "LYV", "MA", "MAA", "MAR", "MAS",
        "MCD", "MCHP", "MCK", "MCO", "MDT", "MET", "META", "MGM", "MHK", "MKC", "MKTX", "MLM", "MMC", "MMM", "MNST",
        "MO", "MOH", "MOS", "MPC", "MPWR", "MRK", "MRO", "MS", "MSCI", "MSFT", "MSI", "MTB", "MTCH", "MTD", "MU",
        "NCLH", "NDAQ", "NDSN", "NEE", "NEM", "NFLX", "NI", "NKE", "NOC", "NOW", "NRG", "NSC", "NTAP", "NTRS", "NUE",
        "NVDA", "NVR", "NWS", "NWSA", "NXPI", "O", "ODFL", "OGN", "OKE", "OMC", "ON", "ORCL", "ORLY", "OTIS", "OXY",
        "PARA", "PAYC", "PAYX", "PCAR", "PCG", "PEG", "PEP", "PFE", "PFG", "PG", "PGR", "PH", "PHM", "PKG", "PLD",
        "PM", "PNC", "PNR", "PNW", "PODD", "POOL", "PPG", "PPL", "PRU", "PSA", "PSX", "PTC", "PWR", "PYPL", "QCOM",
        "QRVO", "RCL", "REG", "REGN", "RF", "RHI", "RJF", "RL", "RMD", "ROK", "ROL", "ROP", "ROST", "RSG", "RTX",
        "RVTY", "SBAC", "SBUX", "SCHW", "SEDG", "SEE", "SHW", "SIVB", "SJM", "SLB", "SNA", "SNPS", "SO", "SPG", "SPGI",
        "SRE", "STE", "STLD", "STT", "STX", "STZ", "SWK", "SWKS", "SYF", "SYK", "SYY", "T", "TAP", "TDG", "TDY",
        "TECH", "TEL", "TER", "TFC", "TFX", "TGT", "TJX", "TMO", "TMUS", "TROW", "TRV", "TSCO", "TSLA", "TSN", "TT",
        "TTWO", "TXN", "TXT", "TYL", "UAL", "UDR", "UHS", "ULTA", "UNH", "UNP", "UPS", "URI", "USB", "V", "VFC",
        "VICI", "VLO", "VMC", "VNO", "VRSK", "VRSN", "VRTX", "VTR", "VTRS", "VZ", "WAB", "WAT", "WBA", "WBD", "WDC",
        "WEC", "WELL", "WFC", "WHR", "WM", "WMB", "WMT", "WRB", "WRK", "WST", "WTW", "WY", "WYNN", "XEL", "XOM",
        "XRAY", "XYL", "YUM", "ZBH", "ZBRA", "ZION", "ZTS"
    ]
    combined = list(set(sp_fb + r2k_fallback))
    return sorted(combined)[:2500]  # wider fallback ~2000+ to simulate broader real universe


# ============================================================
# Russell 3000 = R1000 + R2000 (convenience)
# ============================================================

def get_russell3000_tickers(use_cache: bool = True) -> list[str]:
    """Convenience: Russell 3000 = union of R1000 + R2000."""
    r1k = get_russell1000_tickers(use_cache=use_cache)
    r2k = get_russell2000_tickers(use_cache=use_cache)
    combined = sorted(set(r1k) | set(r2k))
    return combined


def get_universe(full_sp500: bool = False, universe: str = None) -> list[str]:
    """
    Devuelve el universo a usar (siempre unico y ordenado).
    Soporta:
      - universe="sp500" (o full_sp500=True legacy)
      - universe="nasdaq100"
      - universe="dow30"
      - universe="russell1000" → ~1000 large+mid cap US
      - universe="russell2000" → ~2000 small caps (más acciones)
      - universe="russell3000" → R1000 + R2000 (~3000 total)
      - universe="all"       → combina SP500 + Nasdaq100 + Dow30 + R1000 + R2000 (máxima amplitud ~2500+ tickers únicos)
      - universe="custom" o full_sp500=False → INITIAL_UNIVERSE
    """
    if universe is None:
        if full_sp500:
            universe = "sp500"
        else:
            try:
                from config import UNIVERSE as cfg_u
                universe = cfg_u
            except Exception:
                universe = "custom" if not full_sp500 else "sp500"

    u = str(universe).lower().strip() if universe else "sp500"

    if u == "all":
        # Busca en todos los índices a la vez y elige de entre todos (sin separar por índice)
        # Ahora incluye Russell 1000 + Russell 2000 para integrar MUCHAS MÁS acciones (large + mid + small caps)
        print("Obteniendo universo COMBINADO AMPLIADO (SP500 + Nasdaq100 + Dow30 + Russell1000 + Russell2000)...")
        sp = get_sp500_tickers()
        nd = get_nasdaq100_tickers()
        dj = get_dow30_tickers()
        # Force real fetches (no cache) for the new Russell indices to get the widest possible universe
        r1k = get_russell1000_tickers(use_cache=False)
        r2k = get_russell2000_tickers(use_cache=False)
        tickers = list(set(sp) | set(nd) | set(dj) | set(r1k) | set(r2k))
        print(f"  Universo combinado ampliado: {len(tickers)} tickers únicos (incluye small/mid/large vía Russell)")
    elif u == "russell1000":
        tickers = get_russell1000_tickers()
    elif u == "russell2000":
        tickers = get_russell2000_tickers()
    elif u == "russell3000":
        tickers = get_russell3000_tickers()
    elif u in ["sp500", "s&p500", "s&p 500", "spx"]:
        tickers = get_sp500_tickers()
    elif u in ["nasdaq100", "nasdaq-100", "ndx", "nasdaq"]:
        tickers = get_nasdaq100_tickers()
    elif u in ["dow30", "djia", "dow jones", "dow"]:
        tickers = get_dow30_tickers()
    else:
        from config import INITIAL_UNIVERSE
        tickers = INITIAL_UNIVERSE

    # Garantizar sin duplicados (importante para fetch y filtros)
    seen = set()
    unique = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


# ---------------------------------------------------------------------------
# TASK-324: point-in-time S&P 500 membership
# ---------------------------------------------------------------------------

def _yahoo_ticker(sym: str) -> str:
    s = str(sym).strip().upper().replace(".", "-")
    return s


def _parse_wiki_change_tables(tables) -> list[dict]:
    """Best-effort parse of Wikipedia 'Selected changes to the list'."""
    rows = []
    for df in tables[1:]:
        cols = [str(c).lower() for c in df.columns]
        flat = " ".join(cols)
        if "added" not in flat or "removed" not in flat:
            continue
        # flatten multiindex
        df = df.copy()
        df.columns = ["_".join(str(x) for x in c if str(x) != "nan") if isinstance(c, tuple) else str(c)
                      for c in df.columns]
        def _col(*needles, _df=df):
            for c in _df.columns:
                cl = str(c).lower()
                if all(n in cl for n in needles):
                    return c
            return None
        date_col = _col("date")
        add_col = _col("added", "ticker") or _col("added")
        rem_col = _col("removed", "ticker") or _col("removed")
        if not date_col or not add_col or not rem_col:
            continue
        for _, r in df.iterrows():
            try:
                dt = pd.to_datetime(r[date_col], errors="coerce")
            except Exception:
                continue
            if pd.isna(dt):
                continue
            added = _yahoo_ticker(r[add_col]) if pd.notna(r[add_col]) else ""
            removed = _yahoo_ticker(r[rem_col]) if pd.notna(r[rem_col]) else ""
            if added in {"", "NAN", "NONE"}:
                added = ""
            if removed in {"", "NAN", "NONE"}:
                removed = ""
            if not added and not removed:
                continue
            rows.append({"date": dt.strftime("%Y-%m-%d"), "added": added, "removed": removed})
        if rows:
            break
    return rows


# TASK-325: original Clenow file keeps -YYYYMM entity IDs; the Updated file extends
# past 2019-01-11 but strips those suffixes. Prefer original on overlap, append Updated
# after the original's last date. Cache v2 so a v1 (original-only, ends 2019) file is
# not reused silently.
_PIT_CACHE_VERSION = 2
_PIT_GITHUB_ORIG = (
    "https://raw.githubusercontent.com/fja05680/sp500/master/"
    "S%26P%20500%20Historical%20Components%20%26%20Changes.csv"
)
_PIT_GITHUB_UPDATED = (
    "https://raw.githubusercontent.com/fja05680/sp500/master/"
    "S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv"
)
_DELIST_SUFFIX = re.compile(r"^(.+)-(\d{6})$")


def _parse_fja_snapshots(text: str) -> dict:
    """date -> list of yahoo-normalised tickers from an fja05680 components CSV."""
    out = {}
    sdf = pd.read_csv(StringIO(text))
    date_col = sdf.columns[0]
    tickers_col = sdf.columns[1] if len(sdf.columns) > 1 else None
    if tickers_col is None:
        return out
    for _, r in sdf.iterrows():
        dt = pd.to_datetime(r[date_col], errors="coerce")
        if pd.isna(dt):
            continue
        raw = str(r[tickers_col])
        names = [_yahoo_ticker(x) for x in raw.replace(";", ",").split(",") if x.strip()]
        if len(names) > 50:
            out[dt.strftime("%Y-%m-%d")] = names
    return out


def fetch_sp500_pit_payload(timeout: int = 25) -> dict:
    """
    Current constituents + Wikipedia selected-changes + fja05680 snapshots.
    Cached under data_cache/sp500_pit.json. Never raises.
    """
    cache = os.path.join(DATA_CACHE_DIR, "sp500_pit.json")
    if os.path.exists(cache):
        try:
            with open(cache, "r", encoding="utf-8") as f:
                data = json.load(f)
            if (
                data.get("cache_version") == _PIT_CACHE_VERSION
                and data.get("current")
                and data.get("changes") is not None
                and data.get("snapshots")
            ):
                return data
        except Exception as e:
            logger.warning("PIT cache unreadable: %s", e)

    current = _fetch_sp500_from_wikipedia() or get_sp500_tickers()
    current = [_yahoo_ticker(t) for t in current]
    changes = []
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    resp = _get_with_retry(url, timeout=timeout)
    if resp is not None:
        # html5lib is not a declared dependency; Wikipedia selected-changes is the
        # fallback only. Primary path is the github snapshots.
        for flavor in ["lxml", None]:
            try:
                tables = pd.read_html(StringIO(resp.text), flavor=flavor)
                changes = _parse_wiki_change_tables(tables)
                if changes:
                    break
            except Exception as e:
                logger.warning("PIT wikipedia parse flavor %s failed: %s", flavor, e)

    snapshots = {}
    orig_n = 0
    extra_n = 0
    orig_resp = _get_with_retry(_PIT_GITHUB_ORIG, timeout=timeout)
    if orig_resp is not None:
        try:
            snapshots = _parse_fja_snapshots(orig_resp.text)
            orig_n = len(snapshots)
        except Exception as e:
            logger.warning("fja05680 original PIT csv parse failed: %s", e)

    upd_resp = _get_with_retry(_PIT_GITHUB_UPDATED, timeout=timeout)
    if upd_resp is not None:
        try:
            updated = _parse_fja_snapshots(upd_resp.text)
            last_orig = max(snapshots) if snapshots else None
            for d, names in updated.items():
                if last_orig is None or d > last_orig:
                    snapshots[d] = names
                    extra_n += 1
        except Exception as e:
            logger.warning("fja05680 updated PIT csv parse failed: %s", e)

    payload = {
        "updated": datetime.now().isoformat(),
        "cache_version": _PIT_CACHE_VERSION,
        "source_wiki": bool(changes),
        "source_github": bool(snapshots),
        "github_orig_snapshots": orig_n,
        "github_updated_extra": extra_n,
        "current": current,
        "changes": changes,
        "snapshots": snapshots,
    }
    try:
        os.makedirs(DATA_CACHE_DIR, exist_ok=True)
        tmp = cache + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, cache)
    except Exception as e:
        logger.warning("PIT cache write failed: %s", e)
    return payload


def _blocked_strip_bares(payload: dict) -> set:
    """Bare symbols we must not map a -YYYYMM suffix onto (live or later reused)."""
    cached = payload.get("_blocked_bares")
    if isinstance(cached, set):
        return cached
    blocked = {_yahoo_ticker(t) for t in (payload.get("current") or [])}
    snaps = payload.get("snapshots") or {}
    unsuffixed_dates = {}
    suffixes = []
    for date, names in snaps.items():
        for raw in names:
            m = _DELIST_SUFFIX.match(raw)
            if m:
                suffixes.append((m.group(1), m.group(2)))
            else:
                unsuffixed_dates.setdefault(raw, []).append(date)
    for bare, yyyymm in suffixes:
        delist = f"{yyyymm[:4]}-{yyyymm[4:6]}-01"
        for d in unsuffixed_dates.get(bare, ()):
            if d >= delist:
                blocked.add(bare)
                break
    payload["_blocked_bares"] = blocked
    return blocked


def pit_yahoo_symbol(raw: str, payload: dict | None = None) -> str | None:
    """Map a PIT member to a yfinance column, or None if that would reuse a live ticker.

    Suffixed names (AAMRQ-201312) strip to the bare symbol only when that bare symbol
    is not in `current` and does not appear unsuffixed in any snapshot on/after the
    delist month. Better to have no prices than the prices of a different company.
    """
    raw = _yahoo_ticker(raw)
    if not raw:
        return None
    m = _DELIST_SUFFIX.match(raw)
    if not m:
        return raw
    bare = m.group(1)
    if payload is None:
        return None
    if bare in _blocked_strip_bares(payload):
        return None
    return bare


def membership_as_of(as_of: str, payload: dict | None = None) -> list[str]:
    """S&P 500 membership on as_of (YYYY-MM-DD). Prefers github snapshots; else wiki walk.

    Returns the snapshot's raw names (may include -YYYYMM entity IDs). Join to prices
    with yahoo_membership_as_of.
    """
    payload = payload or fetch_sp500_pit_payload()
    as_ts = pd.Timestamp(as_of)

    snaps = payload.get("snapshots") or {}
    if snaps:
        dates = sorted(d for d in snaps if pd.Timestamp(d) <= as_ts)
        if dates:
            return list(snaps[dates[-1]])

    members = set(payload.get("current") or [])
    for ch in sorted(payload.get("changes") or [], key=lambda x: x["date"], reverse=True):
        if pd.Timestamp(ch["date"]) <= as_ts:
            continue
        if ch.get("added"):
            members.discard(ch["added"])
        if ch.get("removed"):
            members.add(ch["removed"])
    return sorted(members)


def yahoo_membership_as_of(as_of: str, payload: dict | None = None) -> list[str]:
    """PIT members mapped to yfinance symbols; reused tickers dropped, not remapped."""
    payload = payload or fetch_sp500_pit_payload()
    out, seen = [], set()
    for raw in membership_as_of(as_of, payload):
        y = pit_yahoo_symbol(raw, payload)
        if y and y not in seen:
            seen.add(y)
            out.append(y)
    return out