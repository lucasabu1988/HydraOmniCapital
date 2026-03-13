"""
test_tiingo_delisted.py — Test Tiingo API for historical data on critical delisted S&P 500 stocks.

PURPOSE:
    Tiingo claims to have historical price data going back further than yfinance for delisted/bankrupt
    stocks. This script probes whether Tiingo can fill the survivorship bias gap identified in Exp #40:
    ENE, LEH, WCOM, BSC, WB, WM, CIT, and others that had no data from Stooq or yfinance.

TIINGO FREE TIER LIMITS:
    - 500 requests/hour
    - Each ticker = 1 metadata call + 1 price sample call = 2 API calls
    - Full 475-ticker historical universe: 475 * 2 = 950 calls = ~1.9 hours at 500/hr
    - With a 3-second inter-request delay: 950 * 3s = ~48 minutes of wall clock time
    - Recommended: run during off-peak hours, check partial results if interrupted

RATE CALCULATION (for reference):
    Universe size:        475 tickers  (fja05680/sp500 repo unique tickers)
    Calls per ticker:     2            (metadata + price sample)
    Total calls:          950
    Free tier limit:      500 calls/hr
    Minimum time:         950 / 500 = 1.90 hours (hitting limit perfectly)
    With 3s sleep:        950 * 3s  = 47.5 minutes (safe, well under limit)
    Recommended sleep:    3.0s between calls to stay < 1200/hr (Tiingo stated max ~1200/hr)

USAGE:
    # Option 1: environment variable (preferred)
    TIINGO_TOKEN=your_token_here python scripts/test_tiingo_delisted.py

    # Option 2: command-line argument
    python scripts/test_tiingo_delisted.py --token your_token_here

    # Option 3: uses hardcoded token from omnicapital_v8_compass_tiingo.py (already in project)
    python scripts/test_tiingo_delisted.py

OUTPUT:
    - Console report for each ticker: EXISTS / NO_DATA / ERROR + date range + row count
    - Writes results/tiingo_delisted_coverage.json with full details
    - Summary table at the end: which tickers have data and what date range
"""

import argparse
import json
import os
import time
import requests
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

# Hardcoded fallback from omnicapital_v8_compass_tiingo.py (already in project)
TIINGO_API_KEY_FALLBACK = '2b4b5626b2849123c9dac0769e418f9b0ccd2a56'

TIINGO_BASE_URL = 'https://api.tiingo.com/tiingo/daily'

# ---------------------------------------------------------------------------
# PRIMARY TEST TARGETS — critical bankruptcy/acquisition tickers from Exp #40
#
# These are the stocks most likely to have free data NOWHERE (yfinance, Stooq)
# because bankrupt companies lose their exchange listing and data vendors stop
# maintaining their historical records. If Tiingo has any of these, it directly
# closes the survivorship bias gap without paying for Norgate Data.
# ---------------------------------------------------------------------------
DELISTED_TARGETS = {
    # Bankruptcy — complete equity wipeout, maximum survivorship bias impact
    'ENE':  'Enron Corp (bankrupt Dec 2001, delisted)',
    'WCOM': 'WorldCom (bankrupt Jul 2002, became MCI 2003)',
    'CIT':  'CIT Group (bankrupt Nov 2009, relisted as new entity)',
    'LEH':  'Lehman Brothers (bankrupt Sep 2008, delisted)',
    'WM':   'Washington Mutual (bankrupt Sep 2008, delisted) -- CAUTION: ticker reused by Waste Management',

    # Forced acquisitions / emergency mergers — partial survivorship bias
    'BSC':  'Bear Stearns (acquired by JPMorgan Mar 2008)',
    'WB':   'Wachovia (acquired by Wells Fargo Oct 2008)',
    'COUN': 'Countrywide Financial (acquired by BofA Jul 2008)',

    # Near-bankrupt / heavily distressed — survived but pre-2008 data often missing in yfinance
    'AIG':  'AIG (survived, but critical pre-2008 data needed for full backtest)',
    'C':    'Citigroup (survived massive dilution — verify pre-2009 adjusted data is correct)',
    'FNM':  'Fannie Mae (delisted 2010, conservatorship Sep 2008)',
    'FRE':  'Freddie Mac (delisted 2010, conservatorship Sep 2008)',

    # Additional notable S&P 500 deletions that Exp #40 flagged as missing
    'GM':   'General Motors old entity (bankrupt Jun 2009) -- CAUTION: ticker reused by new GM',
    'PALM': 'Palm Inc (acquired by HP Apr 2010)',
    'SUNW': 'Sun Microsystems (acquired by Oracle Jan 2010)',
    'EDS':  'Electronic Data Systems (acquired by HP Aug 2008)',
    'MWD':  'Morgan Stanley Dean Witter (renamed to MS 2002)',
    'S':    'Sprint Nextel / Sprint Corp (merged with T-Mobile 2020) -- verify ticker continuity',
}

# ---------------------------------------------------------------------------
# RATE CALCULATION CONSTANTS
# ---------------------------------------------------------------------------
FULL_UNIVERSE_TICKERS = 475       # fja05680/sp500 repo unique tickers
CALLS_PER_TICKER      = 2         # metadata + price sample
TOTAL_CALLS           = FULL_UNIVERSE_TICKERS * CALLS_PER_TICKER
RATE_LIMIT_PER_HOUR   = 500       # Tiingo free tier
SLEEP_BETWEEN_CALLS   = 3.0       # seconds (safe: 3600/3 = 1200/hr >> 500/hr, stays well under)

# ---------------------------------------------------------------------------
# HELPER: rate-aware GET
# ---------------------------------------------------------------------------

def tiingo_get(url: str, params: dict, sleep_secs: float = SLEEP_BETWEEN_CALLS):
    """Single GET to Tiingo with rate-limit handling and sleep."""
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429:
                wait = 60 * (attempt + 1)
                print(f"      [Rate limit 429] Sleeping {wait}s (attempt {attempt + 1}/3)...")
                time.sleep(wait)
                continue
            time.sleep(sleep_secs)
            return r
        except requests.exceptions.RequestException as exc:
            print(f"      [Network error] {exc} (attempt {attempt + 1}/3)")
            time.sleep(10)
    return None


# ---------------------------------------------------------------------------
# CORE PROBE FUNCTIONS
# ---------------------------------------------------------------------------

def probe_metadata(ticker: str, token: str, sleep_secs: float = SLEEP_BETWEEN_CALLS) -> dict:
    """
    Hit GET /tiingo/daily/{ticker} to check if the ticker exists and retrieve
    the start/end date of available data according to Tiingo's index.

    Returns a dict with keys:
        exists: bool
        tiingo_start: str | None  (ISO date)
        tiingo_end:   str | None
        name:         str | None
        description:  str | None
        error:        str | None
    """
    url = f'{TIINGO_BASE_URL}/{ticker}'
    r = tiingo_get(url, {'token': token}, sleep_secs=sleep_secs)
    if r is None:
        return {'exists': False, 'error': 'Network timeout / all retries failed'}
    if r.status_code == 404:
        return {'exists': False, 'error': f'HTTP 404 — ticker not in Tiingo index'}
    if r.status_code == 403:
        return {'exists': False, 'error': 'HTTP 403 — token invalid or plan restriction'}
    if r.status_code != 200:
        return {'exists': False, 'error': f'HTTP {r.status_code}: {r.text[:200]}'}

    try:
        data = r.json()
    except Exception as exc:
        return {'exists': False, 'error': f'JSON parse error: {exc}'}

    return {
        'exists':        True,
        'tiingo_start':  data.get('startDate'),
        'tiingo_end':    data.get('endDate'),
        'name':          data.get('name'),
        'description':   data.get('description', '')[:120],  # truncate for display
        'error':         None,
    }


def probe_price_sample(ticker: str, token: str, start_date: str, end_date: str,
                        sleep_secs: float = SLEEP_BETWEEN_CALLS) -> dict:
    """
    Pull a small price sample (first 5 trading days) around the given start_date.
    Uses the /tiingo/daily/{ticker}/prices endpoint with a narrow window.

    Returns a dict with keys:
        rows:       int
        first_date: str | None
        last_date:  str | None
        sample:     list[dict]  (first 5 rows)
        error:      str | None
    """
    url = f'{TIINGO_BASE_URL}/{ticker}/prices'
    params = {
        'startDate': start_date,
        'endDate':   end_date,
        'token':     token,
    }
    r = tiingo_get(url, params, sleep_secs=sleep_secs)
    if r is None:
        return {'rows': 0, 'first_date': None, 'last_date': None, 'sample': [], 'error': 'Network timeout'}
    if r.status_code != 200:
        return {'rows': 0, 'first_date': None, 'last_date': None, 'sample': [],
                'error': f'HTTP {r.status_code}: {r.text[:200]}'}

    try:
        data = r.json()
    except Exception as exc:
        return {'rows': 0, 'first_date': None, 'last_date': None, 'sample': [],
                'error': f'JSON parse error: {exc}'}

    if not data:
        return {'rows': 0, 'first_date': None, 'last_date': None, 'sample': [],
                'error': 'Empty response — ticker exists in index but no price data in this range'}

    rows = len(data)
    first_date = data[0].get('date', 'N/A')[:10]
    last_date  = data[-1].get('date', 'N/A')[:10]

    # Build compact sample (5 rows) with key fields only
    sample = []
    for row in data[:5]:
        sample.append({
            'date':      row.get('date', '')[:10],
            'adjClose':  round(row.get('adjClose', 0), 4) if row.get('adjClose') else None,
            'adjVolume': row.get('adjVolume'),
        })

    return {
        'rows':       rows,
        'first_date': first_date,
        'last_date':  last_date,
        'sample':     sample,
        'error':      None,
    }


def determine_sample_window(meta: dict) -> tuple[str, str]:
    """
    Given metadata, return a sensible sample window:
    - Use the first 10 days of available data (start_date to start_date + ~14 calendar days)
    - If tiingo_start is None, default to 1998-01-01 to 1998-01-31 (safe early date)
    """
    start_str = meta.get('tiingo_start') or '1998-01-01'
    # Trim to just the date part (Tiingo returns ISO 8601 with timezone)
    start_str = start_str[:10]

    try:
        start_dt = datetime.strptime(start_str, '%Y-%m-%d')
        # Advance 30 calendar days — covers ~20 trading days, enough for a meaningful sample
        end_dt = start_dt + timedelta(days=30)
        end_str = end_dt.strftime('%Y-%m-%d')
    except ValueError:
        end_str = '1998-02-28'

    return start_str, end_str


# ---------------------------------------------------------------------------
# RATE CAPACITY ANALYSIS
# ---------------------------------------------------------------------------

def print_rate_capacity_analysis():
    minutes_with_sleep = (TOTAL_CALLS * SLEEP_BETWEEN_CALLS) / 60
    hours_at_limit     = TOTAL_CALLS / RATE_LIMIT_PER_HOUR

    print()
    print('=' * 72)
    print('  TIINGO FREE TIER RATE CAPACITY ANALYSIS')
    print('=' * 72)
    print(f'  Full historical universe (fja05680/sp500):  {FULL_UNIVERSE_TICKERS} tickers')
    print(f'  API calls per ticker:                        {CALLS_PER_TICKER} (metadata + price)')
    print(f'  Total API calls required:                    {TOTAL_CALLS}')
    print(f'  Free tier limit:                             {RATE_LIMIT_PER_HOUR} requests/hr')
    print()
    print(f'  Scenario A — hitting rate limit perfectly:   {hours_at_limit:.2f} hours')
    print(f'  Scenario B — with {SLEEP_BETWEEN_CALLS:.1f}s sleep between calls:   '
          f'{minutes_with_sleep:.0f} minutes (~{minutes_with_sleep/60:.1f} hours)')
    print(f'    (Scenario B stays at {3600/SLEEP_BETWEEN_CALLS:.0f} calls/hr — '
          f'well under the 500/hr limit)')
    print()
    print('  RECOMMENDATION: Run with --sleep 3 (default). This completes in ~48 min')
    print('  and keeps you safely under the free tier limit. Do not reduce below 2s.')
    print('=' * 72)
    print()


# ---------------------------------------------------------------------------
# MAIN PROBE LOOP
# ---------------------------------------------------------------------------

def run_probe(token: str, output_dir: str = 'results', sleep_secs: float = SLEEP_BETWEEN_CALLS) -> dict:
    print()
    print('=' * 72)
    print('  TIINGO DELISTED TICKER COVERAGE PROBE')
    print(f'  Token: {token[:8]}...{token[-4:]}  (masked)')
    print(f'  Targets: {len(DELISTED_TARGETS)} tickers')
    print(f'  Sleep between calls: {sleep_secs}s')
    print(f'  Date: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 72)

    results = {}

    for i, (ticker, description) in enumerate(DELISTED_TARGETS.items(), 1):
        print(f'\n  [{i:02d}/{len(DELISTED_TARGETS)}] {ticker:<8} — {description}')

        # --- Step 1: Metadata probe ---
        print(f'    Metadata...', end=' ', flush=True)
        meta = probe_metadata(ticker, token, sleep_secs=sleep_secs)

        if not meta['exists']:
            print(f'NOT IN TIINGO INDEX  ({meta["error"]})')
            results[ticker] = {
                'description':   description,
                'exists':        False,
                'meta_error':    meta['error'],
                'tiingo_start':  None,
                'tiingo_end':    None,
                'name':          None,
                'price_rows':    0,
                'price_start':   None,
                'price_end':     None,
                'price_sample':  [],
                'price_error':   None,
                'verdict':       'NO_DATA',
            }
            continue

        print(f'FOUND  name="{meta["name"]}"  '
              f'range={meta["tiingo_start"][:10] if meta["tiingo_start"] else "?"} '
              f'to {meta["tiingo_end"][:10] if meta["tiingo_end"] else "?"}')

        # --- Step 2: Price sample probe ---
        sample_start, sample_end = determine_sample_window(meta)
        print(f'    Price sample [{sample_start} -> {sample_end}]...', end=' ', flush=True)
        price = probe_price_sample(ticker, token, sample_start, sample_end, sleep_secs=sleep_secs)

        if price['error']:
            print(f'ERROR  ({price["error"]})')
        elif price['rows'] == 0:
            print(f'EMPTY (ticker in index but no prices in window)')
        else:
            print(f'{price["rows"]} rows  first={price["first_date"]}  last={price["last_date"]}')
            for row in price['sample']:
                print(f'      {row["date"]}  adjClose={row["adjClose"]}  vol={row["adjVolume"]}')

        verdict = 'NO_DATA'
        if meta['exists'] and price['rows'] > 0:
            verdict = 'HAS_DATA'
        elif meta['exists'] and price['rows'] == 0:
            verdict = 'INDEX_ONLY_NO_PRICES'

        results[ticker] = {
            'description':   description,
            'exists':        meta['exists'],
            'meta_error':    meta['error'],
            'tiingo_start':  meta.get('tiingo_start'),
            'tiingo_end':    meta.get('tiingo_end'),
            'name':          meta.get('name'),
            'price_rows':    price['rows'],
            'price_start':   price.get('first_date'),
            'price_end':     price.get('last_date'),
            'price_sample':  price.get('sample', []),
            'price_error':   price.get('error'),
            'verdict':       verdict,
        }

    return results


# ---------------------------------------------------------------------------
# RESULTS SUMMARY
# ---------------------------------------------------------------------------

def print_summary(results: dict):
    has_data     = [t for t, r in results.items() if r['verdict'] == 'HAS_DATA']
    index_only   = [t for t, r in results.items() if r['verdict'] == 'INDEX_ONLY_NO_PRICES']
    no_data      = [t for t, r in results.items() if r['verdict'] == 'NO_DATA']

    print()
    print('=' * 72)
    print('  SUMMARY')
    print('=' * 72)
    print(f'  Total tickers probed: {len(results)}')
    print(f'  Has price data:       {len(has_data)}  {has_data}')
    print(f'  In index, no prices:  {len(index_only)}  {index_only}')
    print(f'  Not in Tiingo at all: {len(no_data)}  {no_data}')
    print()

    if has_data:
        print('  TICKERS WITH DATA (potential survivorship bias fix):')
        print(f'  {"TICKER":<8} {"NAME":<40} {"TIINGO RANGE":<30}')
        print(f'  {"-"*8} {"-"*40} {"-"*30}')
        for t in has_data:
            r = results[t]
            name  = (r['name'] or '')[:40]
            start = (r['tiingo_start'] or '?')[:10]
            end   = (r['tiingo_end']   or '?')[:10]
            print(f'  {t:<8} {name:<40} {start} to {end}')
        print()

    if no_data:
        print('  TICKERS WITH NO DATA — these require Norgate Data or OTC/pink-sheet sources:')
        for t in no_data:
            print(f'    {t:<8} — {results[t]["description"]}')
        print()

    # Implication for Exp #40 survivorship bias fix
    print('  IMPLICATION FOR SURVIVORSHIP BIAS:')
    if has_data:
        print(f'  Tiingo provides data for {len(has_data)}/{len(results)} critical delisted tickers.')
        print('  This may partially close the bias gap identified in Exp #40 without Norgate Data.')
        print('  NEXT STEP: Run full universe download (475 tickers) to quantify how many')
        print('  of the 475 historical S&P 500 members Tiingo covers vs Stooq/yfinance.')
    else:
        print('  Tiingo has NO data for these critical bankruptcy/delisting events.')
        print('  Norgate Data remains the only reliable solution for point-in-time S&P 500 membership.')
    print('=' * 72)


def save_results(results: dict, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, 'tiingo_delisted_coverage.json')
    payload = {
        'run_timestamp':    datetime.now().isoformat(),
        'tickers_probed':   len(results),
        'has_data_count':   sum(1 for r in results.values() if r['verdict'] == 'HAS_DATA'),
        'no_data_count':    sum(1 for r in results.values() if r['verdict'] == 'NO_DATA'),
        'index_only_count': sum(1 for r in results.values() if r['verdict'] == 'INDEX_ONLY_NO_PRICES'),
        'results':          results,
        'rate_analysis': {
            'full_universe_tickers': FULL_UNIVERSE_TICKERS,
            'calls_per_ticker':      CALLS_PER_TICKER,
            'total_calls':           TOTAL_CALLS,
            'rate_limit_per_hour':   RATE_LIMIT_PER_HOUR,
            'sleep_secs':            SLEEP_BETWEEN_CALLS,
            'estimated_minutes':     round((TOTAL_CALLS * SLEEP_BETWEEN_CALLS) / 60, 1),
            'estimated_hours_at_limit': round(TOTAL_CALLS / RATE_LIMIT_PER_HOUR, 2),
        },
    }
    with open(output_path, 'w') as f:
        json.dump(payload, f, indent=2)
    print(f'\n  Results saved to: {os.path.abspath(output_path)}')


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Test Tiingo API coverage for delisted S&P 500 stocks (survivorship bias probe)'
    )
    parser.add_argument(
        '--token', '-t',
        type=str,
        default=None,
        help='Tiingo API token. Overridden by TIINGO_TOKEN env var if set.'
    )
    parser.add_argument(
        '--sleep', '-s',
        type=float,
        default=SLEEP_BETWEEN_CALLS,
        help=f'Seconds to sleep between API calls (default: {SLEEP_BETWEEN_CALLS})'
    )
    parser.add_argument(
        '--output-dir', '-o',
        type=str,
        default='results',
        help='Directory to write tiingo_delisted_coverage.json (default: results/)'
    )
    parser.add_argument(
        '--rate-analysis', '-r',
        action='store_true',
        help='Print rate capacity analysis and exit (no API calls made)'
    )
    args = parser.parse_args()

    if args.rate_analysis:
        print_rate_capacity_analysis()
        return

    # Resolve token: env var > CLI arg > hardcoded fallback
    token = (
        os.environ.get('TIINGO_TOKEN')
        or args.token
        or TIINGO_API_KEY_FALLBACK
    )

    if token == TIINGO_API_KEY_FALLBACK:
        print('\n  [INFO] Using hardcoded token from omnicapital_v8_compass_tiingo.py')
        print('         Set TIINGO_TOKEN env var or --token to use a different token.')

    sleep_secs = args.sleep
    print_rate_capacity_analysis()

    results = run_probe(token, args.output_dir, sleep_secs=sleep_secs)
    print_summary(results)
    save_results(results, args.output_dir)


if __name__ == '__main__':
    main()
