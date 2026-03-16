import argparse
import json
import logging
import os
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import omnicapital_live as live
import omnicapital_v84_compass as backtest


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
)
logger = logging.getLogger(__name__)


class HistoricalPriceFeed:
    def __init__(self, price_data):
        self.price_data = price_data
        self.current_date = None

    def set_date(self, current_date):
        self.current_date = pd.Timestamp(current_date)

    def get_price(self, symbol):
        if self.current_date is None:
            return None
        df = self.price_data.get(symbol)
        if df is None or self.current_date not in df.index:
            return None
        return float(df.loc[self.current_date, 'Close'])

    def get_prices(self, symbols):
        return {
            symbol: price for symbol, price in
            ((symbol, self.get_price(symbol)) for symbol in symbols)
            if price is not None
        }

    def get_cache_age_seconds(self):
        return 0


def normalize_history(df):
    if df is None or len(df) == 0:
        return None
    frame = df.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = [col[0] for col in frame.columns]
    frame = frame[[col for col in ('Open', 'High', 'Low', 'Close', 'Volume') if col in frame.columns]]
    frame = frame.dropna(subset=['Close'])
    if hasattr(frame.index, 'tz') and frame.index.tz is not None:
        frame.index = frame.index.tz_localize(None)
    frame = frame.sort_index()
    return frame


def download_symbol_history(symbols, start_date, end_date):
    price_data = {}
    for idx, symbol in enumerate(symbols, start=1):
        try:
            logger.info(f"[{idx}/{len(symbols)}] Downloading {symbol}")
            df = yf.download(
                symbol,
                start=start_date.strftime('%Y-%m-%d'),
                end=end_date.strftime('%Y-%m-%d'),
                auto_adjust=False,
                progress=False,
            )
            frame = normalize_history(df)
            if frame is not None and len(frame) >= 30:
                price_data[symbol] = frame
        except Exception as err:
            logger.warning(f"Failed to download {symbol}: {err}")
    return price_data


def collect_all_dates(price_data, start_date, end_date):
    all_dates = set()
    for df in price_data.values():
        all_dates.update(
            ts for ts in df.index
            if start_date <= ts <= end_date
        )
    return sorted(all_dates)


def run_backtest_signal_replay(price_data, annual_universe, spy_data,
                               start_date, end_date, cash_yield_daily=None):
    all_dates = collect_all_dates(price_data, start_date, end_date)
    if not all_dates:
        raise RuntimeError("No trading dates available in requested backtest range")

    positions = {}
    cash = float(backtest.INITIAL_CAPITAL)
    peak_value = float(backtest.INITIAL_CAPITAL)
    crash_cooldown = 0
    portfolio_values = []
    events = []
    first_date = all_dates[0]

    for i, current_date in enumerate(all_dates):
        tradeable_symbols = backtest.get_tradeable_symbols(
            price_data, current_date, first_date, annual_universe
        )

        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and current_date in price_data[symbol].index:
                portfolio_value += pos['shares'] * float(price_data[symbol].loc[current_date, 'Close'])

        if portfolio_value > peak_value:
            peak_value = portfolio_value

        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0.0
        regime_score = backtest.compute_regime_score(spy_data, current_date)

        dd_leverage_val, crash_cooldown = backtest.compute_smooth_leverage(
            drawdown, portfolio_values, max(i - 1, 0), crash_cooldown
        )
        vol_leverage = backtest.compute_dynamic_leverage(spy_data, current_date)
        current_leverage = max(min(dd_leverage_val, vol_leverage), backtest.LEV_FLOOR)

        spy_trend = backtest.get_spy_trend_data(spy_data, current_date)
        if spy_trend is not None:
            spy_close_now, sma200_now = spy_trend
            max_positions = backtest.regime_score_to_positions(
                regime_score,
                spy_close=spy_close_now,
                sma200=sma200_now,
            )
        else:
            max_positions = backtest.regime_score_to_positions(regime_score)

        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            cash -= backtest.MARGIN_RATE / 252 * borrowed

        if cash > 0:
            if cash_yield_daily is not None and current_date in cash_yield_daily.index:
                daily_rate = cash_yield_daily.loc[current_date] / 100 / 252
            else:
                daily_rate = backtest.CASH_YIELD_RATE / 252
            cash += cash * daily_rate

        quality_symbols = backtest.compute_quality_filter(price_data, tradeable_symbols, current_date)
        current_scores = backtest.compute_momentum_scores(
            price_data, quality_symbols, current_date, all_dates, i
        )

        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if symbol not in price_data or current_date not in price_data[symbol].index:
                continue

            current_price = float(price_data[symbol].loc[current_date, 'Close'])
            exit_reason = None
            days_held = i - pos['entry_idx']
            total_days_held = i - pos['original_entry_idx']
            if days_held >= backtest.HOLD_DAYS:
                if backtest.should_renew_position(
                    symbol, pos, current_price, total_days_held, current_scores
                ):
                    pos['entry_idx'] = i
                else:
                    exit_reason = 'hold_expired'

            pos_return = (current_price - pos['entry_price']) / pos['entry_price']
            adaptive_stop = backtest.compute_adaptive_stop(pos.get('entry_daily_vol', 0.016))
            if pos_return <= adaptive_stop:
                exit_reason = 'position_stop'

            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            if pos['high_price'] > pos['entry_price'] * (1 + backtest.TRAILING_ACTIVATION):
                vol_ratio = pos.get('entry_vol', backtest.TRAILING_VOL_BASELINE) / backtest.TRAILING_VOL_BASELINE
                scaled_trailing = backtest.TRAILING_STOP_PCT * vol_ratio
                trailing_level = pos['high_price'] * (1 - scaled_trailing)
                if current_price <= trailing_level:
                    exit_reason = 'trailing_stop'

            if symbol not in tradeable_symbols:
                exit_reason = 'universe_rotation'

            if exit_reason is None and len(positions) > max_positions:
                pos_returns = {}
                for held_symbol, held_pos in positions.items():
                    if held_symbol in price_data and current_date in price_data[held_symbol].index:
                        held_price = float(price_data[held_symbol].loc[current_date, 'Close'])
                        pos_returns[held_symbol] = (held_price - held_pos['entry_price']) / held_pos['entry_price']
                if pos_returns:
                    worst_symbol = min(pos_returns, key=pos_returns.get)
                    if symbol == worst_symbol:
                        exit_reason = 'regime_reduce'

            if exit_reason:
                shares = pos['shares']
                proceeds = shares * current_price
                commission = shares * backtest.COMMISSION_PER_SHARE
                cash += proceeds - commission
                events.append({
                    'source': 'backtest',
                    'type': 'exit',
                    'date': current_date.strftime('%Y-%m-%d'),
                    'symbol': symbol,
                    'reason': exit_reason,
                    'entry_date': pos['entry_date'].strftime('%Y-%m-%d'),
                    'price': current_price,
                })
                del positions[symbol]

        needed = max_positions - len(positions)
        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= 5:
            available_scores = {
                symbol: score for symbol, score in current_scores.items()
                if symbol not in positions
            }
            if len(current_scores) >= backtest.MIN_MOMENTUM_STOCKS and len(available_scores) >= needed:
                ranked = sorted(available_scores.items(), key=lambda item: item[1], reverse=True)
                sector_filtered = backtest.filter_by_sector_concentration(ranked, positions)
                selected = sector_filtered[:needed]
                weights = backtest.compute_volatility_weights(price_data, selected, current_date)
                effective_capital = cash * current_leverage * 0.95

                for symbol in selected:
                    if symbol not in price_data or current_date not in price_data[symbol].index:
                        continue
                    entry_price = float(price_data[symbol].loc[current_date, 'Close'])
                    if entry_price <= 0:
                        continue
                    weight = weights.get(symbol, 1.0 / len(selected))
                    position_value = min(effective_capital * weight, cash * 0.40)
                    shares = position_value / entry_price
                    cost = shares * entry_price
                    commission = shares * backtest.COMMISSION_PER_SHARE
                    if cost + commission <= cash * 0.90:
                        entry_vol, entry_daily_vol = backtest.compute_entry_vol(price_data, symbol, current_date)
                        positions[symbol] = {
                            'entry_price': entry_price,
                            'shares': shares,
                            'entry_date': current_date,
                            'entry_idx': i,
                            'original_entry_idx': i,
                            'high_price': entry_price,
                            'entry_vol': entry_vol,
                            'entry_daily_vol': entry_daily_vol,
                            'sector': backtest.SECTOR_MAP.get(symbol, 'Unknown'),
                        }
                        cash -= cost + commission
                        events.append({
                            'source': 'backtest',
                            'type': 'entry',
                            'date': current_date.strftime('%Y-%m-%d'),
                            'symbol': symbol,
                            'reason': 'rotation_entry',
                            'price': entry_price,
                            'score': current_scores.get(symbol),
                        })

        portfolio_values.append({
            'date': current_date,
            'value': portfolio_value,
            'drawdown': drawdown,
        })

    final_value = portfolio_values[-1]['value'] if portfolio_values else backtest.INITIAL_CAPITAL
    return {
        'events': events,
        'final_value': final_value,
        'annual_universe': annual_universe,
    }


def build_live_replay_trader(feed):
    live._git_sync_available = False
    live._ml_available = False
    live._hydra_available = False
    live._overlay_available = False

    config = live.CONFIG.copy()
    config['BROKER_TYPE'] = 'PAPER'
    config['PAPER_INITIAL_CASH'] = backtest.INITIAL_CAPITAL
    config['COMMISSION_PER_SHARE'] = backtest.COMMISSION_PER_SHARE

    trader = live.COMPASSLive(config)
    trader.data_feed = feed
    trader.broker.set_price_feed(feed)
    trader.broker.connect()
    trader.broker.fill_delay = 0
    trader.save_state = lambda: None
    trader.ml = None
    trader.notifier = None
    trader._hydra_available = False
    trader._overlay_available = False
    return trader


def run_live_signal_replay(price_data, annual_universe, spy_data,
                           start_date, end_date):
    all_dates = collect_all_dates(price_data, start_date, end_date)
    if not all_dates:
        raise RuntimeError("No trading dates available in requested live replay range")

    feed = HistoricalPriceFeed(price_data)
    trader = build_live_replay_trader(feed)
    events = []

    for idx, current_date in enumerate(all_dates, start=1):
        feed.set_date(current_date)
        trader.trading_day_counter = idx
        trader.last_trading_date = current_date.date()
        trader.trades_today = []
        trader.current_universe = annual_universe.get(current_date.year, [])
        trader.universe_year = current_date.year
        trader._hist_cache = {
            symbol: df.loc[:current_date]
            for symbol, df in price_data.items()
            if current_date in df.index
        }
        trader._spy_hist = spy_data.loc[:current_date]
        trader.current_regime_score = live.compute_live_regime_score(trader._spy_hist)
        trader._block_new_entries = False
        trader._rotation_sells_today = False

        portfolio = trader.broker.get_portfolio()
        trader._pre_rotation_value = portfolio.total_value
        trader._pre_rotation_positions = list(trader.broker.positions.keys())
        trader._pre_rotation_positions_data = {
            symbol: {
                'shares': pos.shares,
                'avg_cost': pos.avg_cost,
                'entry_price': trader.position_meta.get(symbol, {}).get('entry_price', pos.avg_cost),
                'sector': trader.position_meta.get(symbol, {}).get('sector', live.SECTOR_MAP.get(symbol, 'Unknown')),
                'entry_day_index': trader.position_meta.get(symbol, {}).get('entry_day_index', trader.trading_day_counter),
                'entry_date': trader.position_meta.get(symbol, {}).get('entry_date'),
            }
            for symbol, pos in trader.broker.positions.items()
        }
        trader._pre_rotation_cash = trader.broker.cash

        trader.portfolio_values_history.append(portfolio.total_value)
        if len(trader.portfolio_values_history) > 30:
            trader.portfolio_values_history = trader.portfolio_values_history[-30:]

        tradeable = [
            symbol for symbol in trader.current_universe
            if symbol in trader._hist_cache and current_date in trader._hist_cache[symbol].index
        ]
        quality_symbols = live.compute_quality_filter(
            trader._hist_cache,
            tradeable,
            trader.config['QUALITY_VOL_MAX'],
            trader.config['QUALITY_VOL_LOOKBACK'],
            trader.config['QUALITY_MAX_SINGLE_DAY'],
        )
        trader._current_scores = live.compute_momentum_scores(
            trader._hist_cache,
            quality_symbols,
            trader.config['MOMENTUM_LOOKBACK'],
            trader.config['MOMENTUM_SKIP'],
        )

        prices = feed.get_prices(set(trader.current_universe) | set(trader.position_meta.keys()))
        trader.check_position_exits(prices, include_hold_expired=True)
        trader.open_new_positions(prices)

        for trade in trader.trades_today:
            events.append({
                'source': 'live',
                'type': 'entry' if trade['action'] == 'BUY' else 'exit',
                'date': current_date.strftime('%Y-%m-%d'),
                'symbol': trade['symbol'],
                'reason': trade.get('exit_reason', 'rotation_entry'),
                'price': trade.get('price'),
            })

    final_value = trader.broker.get_portfolio().total_value
    return {
        'events': events,
        'final_value': final_value,
        'trader': trader,
    }


def build_event_index(events, comparison_universe):
    indexed = {}
    for event in events:
        if event['symbol'] not in comparison_universe:
            continue
        key = (event['type'], event['date'], event['symbol'])
        indexed[key] = event
    return indexed


def compare_event_streams(backtest_events, live_events, comparison_universe):
    backtest_index = build_event_index(backtest_events, comparison_universe)
    live_index = build_event_index(live_events, comparison_universe)

    matched = []
    mismatched = []
    backtest_only = []
    live_only = []

    for key in sorted(set(backtest_index) | set(live_index)):
        back_event = backtest_index.get(key)
        live_event = live_index.get(key)
        if back_event and live_event:
            if back_event.get('reason') == live_event.get('reason'):
                matched.append({
                    'type': key[0],
                    'date': key[1],
                    'symbol': key[2],
                    'reason': back_event.get('reason'),
                })
            else:
                mismatched.append({
                    'type': key[0],
                    'date': key[1],
                    'symbol': key[2],
                    'backtest_reason': back_event.get('reason'),
                    'live_reason': live_event.get('reason'),
                })
        elif back_event:
            backtest_only.append(back_event)
        elif live_event:
            live_only.append(live_event)

    return {
        'matched': matched,
        'mismatched': mismatched,
        'backtest_only': backtest_only,
        'live_only': live_only,
    }


def write_report(markdown_path, json_path, args, summary):
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        '# Backtest Replay Validation',
        '',
        f"- Range: {args.start} -> {args.end}",
        f"- Generated at: {pd.Timestamp.utcnow().isoformat()}",
        f"- Comparison universe size: {summary['comparison_universe_size']}",
        '',
        '## Portfolio Outcomes',
        '',
        f"- Backtest final value: ${summary['backtest_final_value']:,.2f}",
        f"- Live replay final value: ${summary['live_final_value']:,.2f}",
        f"- Absolute difference: ${summary['portfolio_value_diff']:,.2f}",
        '',
        '## Signal Summary',
        '',
        f"- Matched signals: {summary['matched_count']}",
        f"- Mismatched signals: {summary['mismatched_count']}",
        f"- Backtest-only signals: {summary['backtest_only_count']}",
        f"- Live-only signals: {summary['live_only_count']}",
        '',
        '## Sample Mismatches',
        '',
    ]

    if summary['mismatched']:
        for event in summary['mismatched'][:25]:
            lines.append(
                f"- {event['date']} {event['type']} {event['symbol']}: "
                f"backtest={event['backtest_reason']} | live={event['live_reason']}"
            )
    else:
        lines.append('- None')

    lines.extend([
        '',
        '## Sample Backtest-Only Signals',
        '',
    ])
    if summary['backtest_only']:
        for event in summary['backtest_only'][:25]:
            lines.append(f"- {event['date']} {event['type']} {event['symbol']} ({event['reason']})")
    else:
        lines.append('- None')

    lines.extend([
        '',
        '## Sample Live-Only Signals',
        '',
    ])
    if summary['live_only']:
        for event in summary['live_only'][:25]:
            lines.append(f"- {event['date']} {event['type']} {event['symbol']} ({event['reason']})")
    else:
        lines.append('- None')

    markdown_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    json_path.write_text(json.dumps(summary, indent=2, default=str), encoding='utf-8')


def parse_args():
    parser = argparse.ArgumentParser(
        description='Validate live replay signals against COMPASS v8.4 backtest logic.',
    )
    parser.add_argument('--start', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument(
        '--output-prefix',
        default=None,
        help='Optional output path prefix (without extension). Defaults under reports/.',
    )
    return parser.parse_args()


def main():
    args = parse_args()
    start_date = pd.Timestamp(args.start)
    end_date = pd.Timestamp(args.end)
    if end_date <= start_date:
        raise SystemExit('End date must be after start date')

    buffer_start = start_date - pd.Timedelta(days=420)
    buffer_end = end_date + pd.Timedelta(days=5)

    broad_pool = list(dict.fromkeys(backtest.BROAD_POOL))
    price_data = download_symbol_history(broad_pool, buffer_start, buffer_end)
    if not price_data:
        raise SystemExit('Failed to download any historical price data')

    spy_map = download_symbol_history(['SPY'], buffer_start, buffer_end)
    spy_data = spy_map.get('SPY')
    if spy_data is None or len(spy_data) < 252:
        raise SystemExit('SPY history unavailable or insufficient for replay')

    cash_yield_daily = backtest.download_cash_yield()
    annual_universe = backtest.compute_annual_top40(price_data)

    backtest_result = run_backtest_signal_replay(
        price_data,
        annual_universe,
        spy_data,
        start_date,
        end_date,
        cash_yield_daily=cash_yield_daily,
    )
    live_result = run_live_signal_replay(
        price_data,
        annual_universe,
        spy_data,
        start_date,
        end_date,
    )

    comparison_universe = set(getattr(live, 'BROAD_POOL', []))
    comparison = compare_event_streams(
        backtest_result['events'],
        live_result['events'],
        comparison_universe,
    )

    summary = {
        'range': {
            'start': args.start,
            'end': args.end,
        },
        'comparison_universe_size': len(comparison_universe),
        'backtest_final_value': backtest_result['final_value'],
        'live_final_value': live_result['final_value'],
        'portfolio_value_diff': live_result['final_value'] - backtest_result['final_value'],
        'matched_count': len(comparison['matched']),
        'mismatched_count': len(comparison['mismatched']),
        'backtest_only_count': len(comparison['backtest_only']),
        'live_only_count': len(comparison['live_only']),
        'matched': comparison['matched'],
        'mismatched': comparison['mismatched'],
        'backtest_only': comparison['backtest_only'],
        'live_only': comparison['live_only'],
    }

    if args.output_prefix:
        output_prefix = Path(args.output_prefix)
    else:
        output_prefix = REPO_ROOT / 'reports' / f"backtest_replay_{args.start}_{args.end}"

    markdown_path = output_prefix.with_suffix('.md')
    json_path = output_prefix.with_suffix('.json')
    write_report(markdown_path, json_path, args, summary)

    logger.info(f"Replay report written to {markdown_path}")
    logger.info(f"Replay summary written to {json_path}")
    logger.info(
        "Matched=%s | Mismatched=%s | Backtest-only=%s | Live-only=%s",
        summary['matched_count'],
        summary['mismatched_count'],
        summary['backtest_only_count'],
        summary['live_only_count'],
    )


if __name__ == '__main__':
    main()
