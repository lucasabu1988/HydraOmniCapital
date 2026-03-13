"""
Download historical stock data from Investing.com using Selenium + Chrome profile.
Uses the user's logged-in Chrome session to access paid subscription features.

IMPORTANT: Close Chrome before running this script!

Usage:
    python scripts/investing_com_downloader.py
    python scripts/investing_com_downloader.py --limit 20
    python scripts/investing_com_downloader.py --tickers WBA,CBS,K
"""
import os
import sys
import json
import time
import glob
import logging
import argparse
import re
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MERGE_REPORT = os.path.join(BASE_DIR, 'data_sources', 'merge_report.json')
OUTPUT_DIR = os.path.join(BASE_DIR, 'data_sources', 'investing_com')
STATE_FILE = os.path.join(BASE_DIR, 'data_sources', 'investing_com_state.json')
DOWNLOAD_DIR = os.path.join(BASE_DIR, 'data_sources', 'investing_com_downloads')

# Investing.com URL slugs for known tickers (ticker -> slug)
# These map S&P 500 tickers to Investing.com URL paths
KNOWN_SLUGS = {
    'WBA': 'walgreen-co',
    'CBS': 'cbs-corp',
    'K': 'kellogg',
    'IPG': 'interpublic-group',
    'JWN': 'nordstrom',
    'X': 'united-states-steel',
    'CELG': 'celgene-corp',
    'CTXS': 'citrix-systems',
    'ATVI': 'activision-blizzard',
    'TWTR': 'twitter-inc',
    'PKI': 'perkinelmer',
    'BCR': 'c.r.-bard',
    'AVP': 'avon-products',
    'BIG': 'big-lots',
    'MYL': 'mylan-inc',
    'JCP': 'j.c.-penney',
    'RRD': 'rr-donnelley-and-sons',
    'NOVL': 'novell',
    'LSI': 'lsi-logic',
    'MDP': 'meredith-corp',
    'SIAL': 'sigma-aldrich',
    'MON': 'monsanto-co',
    'RAI': 'reynolds-american',
    'WFM': 'whole-foods-market',
    'TIF': 'tiffany-and-co',
    'FL': 'foot-locker',
    'PDCO': 'patterson-cos',
    'BRCM': 'broadcom-corp',
    'FLIR': 'flir-systems',
    'MXIM': 'maxim-integrated-products',
    'LLTC': 'linear-technology',
    'STJ': 'st-jude-medical',
    'BNI': 'burlington-northern',
    'WYE': 'wyeth',
    'XTO': 'xto-energy',
    'DTV': 'directv',
    'SWY': 'safeway-inc',
    'PCP': 'precision-castparts',
    'GGP': 'general-growth',
    'HNZ': 'h.j.-heinz',
    'BXLT': 'baxalta',
    'COV': 'covidien-plc',
    'PLL': 'pall-corp',
    'MFE': 'mcafee',
    'SNI': 'scripps-networks',
    'MJN': 'mead-johnson',
    'ETFC': 'e-trade-financial',
    'CERN': 'cerner-corp',
    'HSP': 'hospira',
    'PBCT': 'peoples-united-financial',
    'RHT': 'red-hat',
    'XLNX': 'xilinx',
    'NLSN': 'nielsen-holdings',
    'SYMC': 'symantec',
    'GAS': 'nicor-inc',
    'RDC': 'rowan-cos',
    'MWV': 'meadwestvaco',
    'ABC': 'amerisourcebergen',
    'XL': 'xl-group',
    'IGT': 'intl-game-technology',
    'BDK': 'black-and-decker',
    'CTX': 'centex-corp',
    'LXK': 'lexmark-intl',
    'FDO': 'family-dollar',
    'WWY': 'wrigley-(wm.)-jr.',
    'APOL': 'apollo-education',
    'ROH': 'rohm-and-haas',
    'BMET': 'biomet',
    'NVLS': 'novellus-systems',
    'TRB': 'tribune',
    'DJ': 'dow-jones-and-co',
    'TXU': 'txu-corp',
    'OMX': 'officemax',
    'PGN': 'progress-energy',
    'HSH': 'hillshire-brands',
    'BRL': 'barr-pharmaceuticals',
    'VIAB': 'viacom-b',
    'ADS': 'alliance-data-systems',
    'CBH': 'commerce-bancshares',
    'VAR': 'varian-medical',
    'DISH': 'dish-network',
    'RAD': 'rite-aid',
    'PARA': 'paramount-global',
    'RE': 'everest-re-group',
    'BT': 'bt-group',
    'AT': 'alltel-corp',
    'NXTL': 'nextel-communications',
    'FRX': 'forest-labs',
    'ARNC': 'arconic-inc',
    'DFS': 'discover-financial',
    'HES': 'hess-corp',
    'MRO': 'marathon-oil',
    'JNPR': 'juniper-networks',
    'CHK': 'chesapeake-energy',
    'ENDP': 'endo-intl',
    'NCR': 'ncr-corp',
    'BLL': 'ball-corp',
    'GENZ': 'genzyme',
    'AGN': 'allergan',
    'WLP': 'wellpoint',
    'CVH': 'coventry-health',
    'PETM': 'petsmart',
    'NYX': 'nyse-euronext',
    'HCP': 'hcp-inc',
    'LO': 'lorillard-inc',
    'DNB': 'dun-and-bradstreet',
    'EDS': 'electronic-data-systems',
}


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {'completed': [], 'failed': [], 'not_found': []}


def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def get_chrome_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    # Kill any leftover Chrome lock files
    user_data_dir = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'Google', 'Chrome', 'User Data')
    lock_file = os.path.join(user_data_dir, 'SingletonLock')
    if os.path.exists(lock_file):
        try:
            os.remove(lock_file)
        except Exception:
            pass

    chrome_options = Options()
    chrome_options.add_argument(f'--user-data-dir={user_data_dir}')
    chrome_options.add_argument('--profile-directory=Default')
    chrome_options.add_argument('--no-first-run')
    chrome_options.add_argument('--no-default-browser-check')
    chrome_options.add_argument('--remote-debugging-port=9222')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')

    # Set download directory
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    prefs = {
        'download.default_directory': DOWNLOAD_DIR,
        'download.prompt_for_download': False,
        'download.directory_upgrade': True,
    }
    chrome_options.add_experimental_option('prefs', prefs)

    try:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except Exception:
        # Fallback: try without webdriver_manager
        driver = webdriver.Chrome(options=chrome_options)

    return driver


def search_ticker_slug(driver, ticker):
    """Search for a ticker on Investing.com and return the historical data URL slug."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    if ticker in KNOWN_SLUGS:
        return KNOWN_SLUGS[ticker]

    # Search on Investing.com
    driver.get(f'https://www.investing.com/search/?q={ticker}&tab=quotes')
    time.sleep(3)

    try:
        # Find the first equity result
        results = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/equities/"]')
        for r in results:
            href = r.get_attribute('href')
            if '/equities/' in href and 'historical' not in href:
                slug = href.split('/equities/')[-1].rstrip('/')
                logger.info(f'  Found slug for {ticker}: {slug}')
                return slug
    except Exception:
        pass

    return None


def download_historical_data(driver, ticker, slug):
    """Navigate to historical data page and download CSV."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    url = f'https://www.investing.com/equities/{slug}-historical-data'
    driver.get(url)
    time.sleep(3)

    try:
        # Close any popup/modal
        try:
            close_btns = driver.find_elements(By.CSS_SELECTOR, 'button[class*="close"], .popupCloseIcon')
            for btn in close_btns:
                try:
                    btn.click()
                    time.sleep(0.5)
                except Exception:
                    pass
        except Exception:
            pass

        # Change date range to maximum (from 2000)
        try:
            date_picker = driver.find_element(By.CSS_SELECTOR, '[class*="DatePickerWrapper"], [data-test="historicalDatePicker"]')
            date_picker.click()
            time.sleep(1)

            # Set start date to 01/01/2000
            start_input = driver.find_elements(By.CSS_SELECTOR, 'input[type="text"]')
            if len(start_input) >= 2:
                start_input[0].clear()
                start_input[0].send_keys('01/01/2000')
                time.sleep(0.5)

            # Click Apply
            apply_btns = driver.find_elements(By.CSS_SELECTOR, 'button')
            for btn in apply_btns:
                if 'Apply' in btn.text or 'apply' in btn.text.lower():
                    btn.click()
                    time.sleep(3)
                    break
        except Exception as e:
            logger.warning(f'  Could not set date range: {e}')

        # Click Download button
        download_btns = driver.find_elements(By.CSS_SELECTOR, '[class*="download"], [data-test="download"]')
        if not download_btns:
            # Try text-based search
            all_btns = driver.find_elements(By.TAG_NAME, 'div')
            for btn in all_btns:
                try:
                    if btn.text.strip() == 'Download':
                        download_btns = [btn]
                        break
                except Exception:
                    pass

        if download_btns:
            download_btns[0].click()
            time.sleep(5)  # Wait for download

            # Find the downloaded file
            csv_files = glob.glob(os.path.join(DOWNLOAD_DIR, '*.csv'))
            if csv_files:
                latest = max(csv_files, key=os.path.getctime)
                return latest

        logger.warning(f'  No download button found for {ticker}')
        return None

    except Exception as e:
        logger.error(f'  Error downloading {ticker}: {e}')
        return None


def process_csv(csv_path, ticker):
    """Convert Investing.com CSV to parquet."""
    try:
        df = pd.read_csv(csv_path)

        # Investing.com CSV format: Date, Price, Open, High, Low, Vol., Change %
        col_map = {
            'Date': 'date', 'Price': 'Close', 'Open': 'Open',
            'High': 'High', 'Low': 'Low', 'Vol.': 'Volume',
        }
        df = df.rename(columns=col_map)

        # Parse date
        df['date'] = pd.to_datetime(df['date'], format='mixed')
        df = df.set_index('date').sort_index()

        # Parse volume (e.g., "177.79M" -> 177790000)
        if 'Volume' in df.columns:
            def parse_vol(v):
                if pd.isna(v) or v == '-':
                    return 0
                v = str(v).replace(',', '')
                if v.endswith('M'):
                    return float(v[:-1]) * 1_000_000
                if v.endswith('K'):
                    return float(v[:-1]) * 1_000
                if v.endswith('B'):
                    return float(v[:-1]) * 1_000_000_000
                try:
                    return float(v)
                except ValueError:
                    return 0
            df['Volume'] = df['Volume'].apply(parse_vol)

        # Keep standard columns
        keep = [c for c in ['Open', 'High', 'Low', 'Close', 'Volume'] if c in df.columns]
        df = df[keep].dropna(subset=['Close'])

        # Convert string prices to float (remove commas)
        for col in ['Open', 'High', 'Low', 'Close']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce')

        # Quality filter
        returns = df['Close'].pct_change().abs()
        mask = returns <= 0.80
        mask.iloc[0] = True
        df = df[mask]

        if len(df) < 10:
            return None

        out_path = os.path.join(OUTPUT_DIR, f'{ticker}.parquet')
        df.to_parquet(out_path)
        return len(df)

    except Exception as e:
        logger.error(f'  Error processing CSV for {ticker}: {e}')
        return None


def main():
    parser = argparse.ArgumentParser(description='Download from Investing.com')
    parser.add_argument('--limit', type=int, default=50, help='Max tickers to process')
    parser.add_argument('--tickers', type=str, default=None, help='Comma-separated tickers')
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    state = load_state()
    done = set(state['completed'] + state['failed'] + state['not_found'])

    if args.tickers:
        targets = [t.strip() for t in args.tickers.split(',')]
    else:
        # Load from merge report
        with open(MERGE_REPORT) as f:
            report = json.load(f)
        targets = report['still_missing_tickers']

    todo = [t for t in targets if t not in done][:args.limit]
    logger.info(f'Targets: {len(targets)}, Done: {len(done)}, To process: {len(todo)}')

    if not todo:
        logger.info('Nothing to do!')
        return

    logger.info('Launching Chrome with your profile...')
    logger.info('MAKE SURE CHROME IS CLOSED FIRST!')

    try:
        driver = get_chrome_driver()
    except Exception as e:
        logger.error(f'Failed to launch Chrome: {e}')
        logger.error('Make sure Chrome is closed and try again.')
        return

    try:
        for i, ticker in enumerate(todo):
            logger.info(f'[{i+1}/{len(todo)}] {ticker}...')

            slug = search_ticker_slug(driver, ticker)
            if not slug:
                state['not_found'].append(ticker)
                save_state(state)
                logger.info(f'  Not found on Investing.com')
                continue

            csv_path = download_historical_data(driver, ticker, slug)
            if csv_path:
                rows = process_csv(csv_path, ticker)
                if rows:
                    state['completed'].append(ticker)
                    logger.info(f'  OK: {rows} rows saved')
                else:
                    state['failed'].append(ticker)
                    logger.info(f'  Failed: could not process CSV')

                # Clean up downloaded CSV
                try:
                    os.remove(csv_path)
                except Exception:
                    pass
            else:
                state['failed'].append(ticker)
                logger.info(f'  Failed: no CSV downloaded')

            save_state(state)
            time.sleep(2)

    finally:
        driver.quit()

    logger.info(f'\n=== FINAL ===')
    logger.info(f'Completed: {len(state["completed"])}')
    logger.info(f'Failed: {len(state["failed"])}')
    logger.info(f'Not found: {len(state["not_found"])}')


if __name__ == '__main__':
    main()
