#!/usr/bin/env python3
"""
Generate Excel: Top 40 stocks by dollar volume per year (2000-2026)
from the hardcoded 113-stock BROAD_POOL.
"""

import os
import json
import numpy as np
import pandas as pd
import yfinance as yf

BROAD_POOL = [
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META', 'AVGO', 'ADBE', 'CRM', 'AMD',
    'INTC', 'CSCO', 'IBM', 'TXN', 'QCOM', 'ORCL', 'ACN', 'NOW', 'INTU',
    'AMAT', 'MU', 'LRCX', 'SNPS', 'CDNS', 'KLAC', 'MRVL',
    'BRK-B', 'JPM', 'V', 'MA', 'BAC', 'WFC', 'GS', 'MS', 'AXP', 'BLK',
    'SCHW', 'C', 'USB', 'PNC', 'TFC', 'CB', 'MMC', 'AIG',
    'UNH', 'JNJ', 'LLY', 'ABBV', 'MRK', 'PFE', 'TMO', 'ABT', 'DHR',
    'AMGN', 'BMY', 'MDT', 'ISRG', 'SYK', 'GILD', 'REGN', 'VRTX', 'BIIB',
    'AMZN', 'TSLA', 'WMT', 'HD', 'PG', 'COST', 'KO', 'PEP', 'NKE',
    'MCD', 'DIS', 'SBUX', 'TGT', 'LOW', 'CL', 'KMB', 'GIS', 'EL',
    'MO', 'PM',
    'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'OXY', 'MPC', 'PSX', 'VLO',
    'GE', 'CAT', 'BA', 'HON', 'UNP', 'RTX', 'LMT', 'DE', 'UPS', 'FDX',
    'MMM', 'GD', 'NOC', 'EMR',
    'NEE', 'DUK', 'SO', 'D', 'AEP',
    'VZ', 'T', 'TMUS', 'CMCSA',
]

SECTOR_MAP = {
    'AAPL': 'Technology', 'MSFT': 'Technology', 'NVDA': 'Technology', 'GOOGL': 'Technology',
    'META': 'Technology', 'AVGO': 'Technology', 'ADBE': 'Technology', 'CRM': 'Technology',
    'AMD': 'Technology', 'INTC': 'Technology', 'CSCO': 'Technology', 'IBM': 'Technology',
    'TXN': 'Technology', 'QCOM': 'Technology', 'ORCL': 'Technology', 'ACN': 'Technology',
    'NOW': 'Technology', 'INTU': 'Technology', 'AMAT': 'Technology', 'MU': 'Technology',
    'LRCX': 'Technology', 'SNPS': 'Technology', 'CDNS': 'Technology', 'KLAC': 'Technology',
    'MRVL': 'Technology',
    'BRK-B': 'Financials', 'JPM': 'Financials', 'V': 'Financials', 'MA': 'Financials',
    'BAC': 'Financials', 'WFC': 'Financials', 'GS': 'Financials', 'MS': 'Financials',
    'AXP': 'Financials', 'BLK': 'Financials', 'SCHW': 'Financials', 'C': 'Financials',
    'USB': 'Financials', 'PNC': 'Financials', 'TFC': 'Financials', 'CB': 'Financials',
    'MMC': 'Financials', 'AIG': 'Financials',
    'UNH': 'Healthcare', 'JNJ': 'Healthcare', 'LLY': 'Healthcare', 'ABBV': 'Healthcare',
    'MRK': 'Healthcare', 'PFE': 'Healthcare', 'TMO': 'Healthcare', 'ABT': 'Healthcare',
    'DHR': 'Healthcare', 'AMGN': 'Healthcare', 'BMY': 'Healthcare', 'MDT': 'Healthcare',
    'ISRG': 'Healthcare', 'SYK': 'Healthcare', 'GILD': 'Healthcare', 'REGN': 'Healthcare',
    'VRTX': 'Healthcare', 'BIIB': 'Healthcare',
    'AMZN': 'Consumer', 'TSLA': 'Consumer', 'WMT': 'Consumer', 'HD': 'Consumer',
    'PG': 'Consumer', 'COST': 'Consumer', 'KO': 'Consumer', 'PEP': 'Consumer',
    'NKE': 'Consumer', 'MCD': 'Consumer', 'DIS': 'Consumer', 'SBUX': 'Consumer',
    'TGT': 'Consumer', 'LOW': 'Consumer', 'CL': 'Consumer', 'KMB': 'Consumer',
    'GIS': 'Consumer', 'EL': 'Consumer', 'MO': 'Consumer', 'PM': 'Consumer',
    'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy', 'SLB': 'Energy',
    'EOG': 'Energy', 'OXY': 'Energy', 'MPC': 'Energy', 'PSX': 'Energy', 'VLO': 'Energy',
    'GE': 'Industrials', 'CAT': 'Industrials', 'BA': 'Industrials', 'HON': 'Industrials',
    'UNP': 'Industrials', 'RTX': 'Industrials', 'LMT': 'Industrials', 'DE': 'Industrials',
    'UPS': 'Industrials', 'FDX': 'Industrials', 'MMM': 'Industrials', 'GD': 'Industrials',
    'NOC': 'Industrials', 'EMR': 'Industrials',
    'NEE': 'Utilities', 'DUK': 'Utilities', 'SO': 'Utilities', 'D': 'Utilities', 'AEP': 'Utilities',
    'VZ': 'Telecom', 'T': 'Telecom', 'TMUS': 'Telecom', 'CMCSA': 'Telecom',
}

TOP_N = 40


def main():
    print("=" * 70)
    print("Generating Universe Excel: Top 40 by Dollar Volume (2000-2026)")
    print("=" * 70)

    # Download all data (1999-2026 for prior-year ranking)
    print(f"\nDownloading data for {len(BROAD_POOL)} stocks...")

    price_data = {}
    for i, symbol in enumerate(BROAD_POOL):
        cache_csv = f'data_cache/{symbol}_1999-01-01_2027-01-01.csv'
        if os.path.exists(cache_csv):
            df = pd.read_csv(cache_csv, index_col=0, parse_dates=True)
            if len(df) >= 20:
                price_data[symbol] = df
            continue

        try:
            df = yf.download(symbol, start='1999-01-01', end='2027-01-01', progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            if len(df) >= 20:
                price_data[symbol] = df
                os.makedirs('data_cache', exist_ok=True)
                df.to_csv(cache_csv)
                print(f"  [{i+1}/{len(BROAD_POOL)}] {symbol}: {len(df)} days")
        except Exception as e:
            print(f"  [{i+1}/{len(BROAD_POOL)}] {symbol}: FAILED ({e})")

    print(f"\n{len(price_data)} stocks with data")

    # Compute top-40 for each year
    years = list(range(2000, 2027))
    year_results = {}

    for year in years:
        start = f'{year - 1}-01-01'
        end = f'{year}-01-01'

        scores = {}
        for symbol, df in price_data.items():
            mask = (df.index >= start) & (df.index < end)
            window = df.loc[mask]
            if len(window) < 20:
                continue
            dollar_vol = (window['Close'] * window['Volume']).mean()
            scores[symbol] = dollar_vol

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_40 = ranked[:TOP_N]

        year_results[year] = []
        for rank, (symbol, dv) in enumerate(top_40, 1):
            sector = SECTOR_MAP.get(symbol, 'Unknown')
            year_results[year].append({
                'Rank': rank,
                'Ticker': symbol,
                'Sector': sector,
                'Avg Daily $ Volume': dv,
            })

        print(f"  {year}: {len(scores)} stocks with data -> Top {len(top_40)} selected")

    # Build Excel
    output_file = 'backtests/compass_universe_2000_2026.xlsx'
    print(f"\nWriting Excel to {output_file}...")

    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        # === Summary sheet: ticker presence across years ===
        all_tickers = set()
        for year_data in year_results.values():
            for entry in year_data:
                all_tickers.add(entry['Ticker'])
        all_tickers = sorted(all_tickers)

        summary_rows = []
        for ticker in all_tickers:
            row = {'Ticker': ticker, 'Sector': SECTOR_MAP.get(ticker, 'Unknown')}
            appearances = 0
            for year in years:
                in_year = any(e['Ticker'] == ticker for e in year_results[year])
                row[str(year)] = 'X' if in_year else ''
                if in_year:
                    appearances += 1
            row['Years in Top-40'] = appearances
            summary_rows.append(row)

        summary_df = pd.DataFrame(summary_rows)
        summary_df = summary_df.sort_values('Years in Top-40', ascending=False)
        summary_df.to_excel(writer, sheet_name='Summary', index=False)

        # === One sheet per year ===
        for year in years:
            df = pd.DataFrame(year_results[year])
            df['Avg Daily $ Volume'] = df['Avg Daily $ Volume'].apply(lambda x: f"${x:,.0f}")
            df.to_excel(writer, sheet_name=str(year), index=False)

        # === Sector breakdown sheet ===
        sector_rows = []
        for year in years:
            sector_counts = {}
            for entry in year_results[year]:
                s = entry['Sector']
                sector_counts[s] = sector_counts.get(s, 0) + 1
            row = {'Year': year}
            row.update(sector_counts)
            sector_rows.append(row)
        sector_df = pd.DataFrame(sector_rows).fillna(0)
        for c in sector_df.columns:
            if c != 'Year':
                sector_df[c] = sector_df[c].astype(int)
        sector_df.to_excel(writer, sheet_name='Sectors', index=False)

        # === Turnover sheet ===
        turnover_rows = []
        for i, year in enumerate(years):
            curr = set(e['Ticker'] for e in year_results[year])
            if i > 0:
                prev = set(e['Ticker'] for e in year_results[years[i-1]])
                added = curr - prev
                removed = prev - curr
                overlap = curr & prev
                turnover_rows.append({
                    'Year': year,
                    'Overlap': len(overlap),
                    'Added': len(added),
                    'Removed': len(removed),
                    'Turnover %': f"{len(added) / TOP_N * 100:.0f}%",
                    'Added Tickers': ', '.join(sorted(added)),
                    'Removed Tickers': ', '.join(sorted(removed)),
                })
        turnover_df = pd.DataFrame(turnover_rows)
        turnover_df.to_excel(writer, sheet_name='Turnover', index=False)

    print(f"\nDone! Saved to {output_file}")
    print(f"  Sheets: Summary + {len(years)} yearly + Sectors + Turnover")


if __name__ == '__main__':
    main()
