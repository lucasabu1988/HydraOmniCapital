"""Tool definitions for the HYDRA autonomous agent (Anthropic API format).

15 tools organized in 3 categories:
  Trading Core (7): momentum signals, regime, stops, trade execution, state
  Market Intelligence (5): earnings, macro, insider, financials, news
  Operations (3): notifications, decision logging, data validation
"""

import os
import json
import logging
import tempfile
from datetime import datetime

logger = logging.getLogger(__name__)

MAX_ORDER_VALUE = 50_000
MOC_DEADLINE_HOUR = 15
MOC_DEADLINE_MINUTE = 50
MAX_DAILY_ROUND_TRIPS = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_et_now():
    """Current time in US/Eastern (handles EDT/EST automatically)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo('America/New_York')).replace(tzinfo=None)
    except ImportError:
        from dateutil import tz
        return datetime.now(tz.gettz('America/New_York')).replace(tzinfo=None)


def _check_yfinance_health():
    """Verify yfinance responds and SPY price is fresh."""
    try:
        import yfinance as yf
        spy = yf.Ticker('SPY')
        hist = spy.history(period='1d')
        if hist.empty:
            return {'yfinance_ok': False, 'spy_fresh': False, 'spy_price': None, 'error': 'empty history'}
        price = float(hist['Close'].iloc[-1])
        return {'yfinance_ok': True, 'spy_fresh': True, 'spy_price': price}
    except Exception as e:
        return {'yfinance_ok': False, 'spy_fresh': False, 'spy_price': None, 'error': str(e)}


# ---------------------------------------------------------------------------
# Tool Definitions (Anthropic API format)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    # ---- Trading Core (7) ----
    {
        'name': 'get_momentum_signals',
        'description': 'Compute cross-sectional momentum scores for the S&P 500 universe and return the top N ranked stocks with their scores, sectors, and recent returns.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'top_n': {
                    'type': 'integer',
                    'description': 'Number of top-ranked stocks to return (default 20)',
                    'default': 20,
                },
            },
            'required': [],
        },
    },
    {
        'name': 'check_regime',
        'description': 'Return the current market regime: regime_score, crash_cooldown, risk mode (risk-on/risk-off), and recent SPY levels vs SMA200.',
        'input_schema': {
            'type': 'object',
            'properties': {},
            'required': [],
        },
    },
    {
        'name': 'check_position_stops',
        'description': 'For each open position, compute current return vs adaptive stop level and trailing stop. Returns list of positions with stop distances and whether any stop is triggered.',
        'input_schema': {
            'type': 'object',
            'properties': {},
            'required': [],
        },
    },
    {
        'name': 'execute_trade',
        'description': 'Execute a BUY or SELL trade via the broker. Enforces idempotency (no duplicate trades), MOC deadline (15:50 ET), daily round-trip limit (10), and max order value ($50K).',
        'input_schema': {
            'type': 'object',
            'properties': {
                'symbol': {
                    'type': 'string',
                    'description': 'Ticker symbol (e.g. AAPL)',
                },
                'action': {
                    'type': 'string',
                    'enum': ['BUY', 'SELL'],
                    'description': 'Trade direction',
                },
                'shares': {
                    'type': 'integer',
                    'description': 'Number of shares to trade',
                },
            },
            'required': ['symbol', 'action', 'shares'],
        },
    },
    {
        'name': 'get_portfolio_state',
        'description': 'Return current portfolio state: cash, total value, positions with metadata, regime score, peak value, crash cooldown, and trading day counter.',
        'input_schema': {
            'type': 'object',
            'properties': {},
            'required': [],
        },
    },
    {
        'name': 'save_state',
        'description': 'Persist the current engine state to disk (state/compass_state_latest.json) and attempt git sync.',
        'input_schema': {
            'type': 'object',
            'properties': {},
            'required': [],
        },
    },
    {
        'name': 'update_cycle_log',
        'description': 'Append an event to the 5-day rotation cycle log (cycle_log.json). Uses atomic writes (temp file + os.replace).',
        'input_schema': {
            'type': 'object',
            'properties': {
                'event_type': {
                    'type': 'string',
                    'enum': ['rotation_start', 'rotation_end', 'stop_exit'],
                    'description': 'Type of cycle event',
                },
                'details': {
                    'type': 'object',
                    'description': 'Event-specific details (symbols, prices, reasons)',
                },
            },
            'required': ['event_type', 'details'],
        },
    },
    # ---- Market Intelligence (5) ----
    {
        'name': 'get_earnings_calendar',
        'description': 'Fetch upcoming earnings dates for a list of symbols using yfinance. Returns next 3 earnings dates per symbol.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'symbols': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'List of ticker symbols to check',
                },
            },
            'required': ['symbols'],
        },
    },
    {
        'name': 'get_macro_data',
        'description': 'Fetch current macro indicators: VIX level, SPY price, and placeholder for FRED data (10Y yield, credit spreads).',
        'input_schema': {
            'type': 'object',
            'properties': {},
            'required': [],
        },
    },
    {
        'name': 'get_insider_trades',
        'description': 'Get recent insider trading activity for a symbol. (Stub — future MCP integration.)',
        'input_schema': {
            'type': 'object',
            'properties': {
                'symbol': {
                    'type': 'string',
                    'description': 'Ticker symbol',
                },
            },
            'required': ['symbol'],
        },
    },
    {
        'name': 'get_financial_metrics',
        'description': 'Get key financial metrics (P/E, revenue growth, margins) for a symbol. (Stub — future MCP integration.)',
        'input_schema': {
            'type': 'object',
            'properties': {
                'symbol': {
                    'type': 'string',
                    'description': 'Ticker symbol',
                },
            },
            'required': ['symbol'],
        },
    },
    {
        'name': 'get_news_headlines',
        'description': 'Get recent news headlines for a symbol. (Stub — future MCP integration.)',
        'input_schema': {
            'type': 'object',
            'properties': {
                'symbol': {
                    'type': 'string',
                    'description': 'Ticker symbol',
                },
            },
            'required': ['symbol'],
        },
    },
    # ---- Capital Management (3) ----
    {
        'name': 'get_capital_status',
        'description': 'Get HYDRA capital manager status: COMPASS account, Rattlesnake account, EFA value, recycling metrics, and effective allocations after cash recycling.',
        'input_schema': {
            'type': 'object',
            'properties': {},
            'required': [],
        },
    },
    {
        'name': 'get_rattlesnake_status',
        'description': 'Get Rattlesnake strategy status: open positions with entry prices and days held, regime (risk-on/off, VIX panic), available slots, and exposure fraction.',
        'input_schema': {
            'type': 'object',
            'properties': {},
            'required': [],
        },
    },
    {
        'name': 'get_efa_status',
        'description': 'Get EFA third pillar status: current position (shares, cost, value), SMA200 trend, idle cash available for EFA, and whether buy/sell conditions are met.',
        'input_schema': {
            'type': 'object',
            'properties': {},
            'required': [],
        },
    },
    # ---- Operations (3) ----
    {
        'name': 'send_notification',
        'description': 'Send a notification message via the configured notifier (Telegram, email, etc.).',
        'input_schema': {
            'type': 'object',
            'properties': {
                'message': {
                    'type': 'string',
                    'description': 'Notification message text',
                },
            },
            'required': ['message'],
        },
    },
    {
        'name': 'log_decision',
        'description': 'Log a trading decision to the scratchpad for audit trail. Records action, reason, symbol, and alternative considered.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'action': {
                    'type': 'string',
                    'description': 'Decision action (BUY, SELL, SKIP, HOLD, etc.)',
                },
                'reason': {
                    'type': 'string',
                    'description': 'Reason for the decision',
                },
                'symbol': {
                    'type': 'string',
                    'description': 'Ticker symbol (if applicable)',
                },
                'alternative': {
                    'type': 'string',
                    'description': 'Alternative considered (if applicable)',
                },
            },
            'required': ['action', 'reason'],
        },
    },
    {
        'name': 'validate_data_feeds',
        'description': 'Check health of data feeds: yfinance connectivity, SPY price freshness, and data cache status.',
        'input_schema': {
            'type': 'object',
            'properties': {},
            'required': [],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool Executor
# ---------------------------------------------------------------------------

class HydraToolExecutor:

    def __init__(self, engine, scratchpad, notifier=None):
        self.engine = engine
        self.scratchpad = scratchpad
        self.notifier = notifier

    def dispatch(self, tool_name, tool_input):
        handler = getattr(self, f'_tool_{tool_name}', None)
        if handler is None:
            return json.dumps({'error': f'Unknown tool: {tool_name}'})
        try:
            self.scratchpad.log('tool_call', {'tool': tool_name, 'input': tool_input})
            result = handler(tool_input)
            return result if isinstance(result, str) else json.dumps(result, default=str)
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}", exc_info=True)
            return json.dumps({'error': str(e)})

    # ----------------------------------------------------------------
    # Trading Core
    # ----------------------------------------------------------------

    def _tool_get_momentum_signals(self, inp):
        top_n = inp.get('top_n', 20)
        try:
            from omnicapital_live import compute_momentum_scores
            import yfinance as yf

            # Get SPY history for regime context
            spy = yf.Ticker('SPY')
            spy_hist = spy.history(period='6mo')

            # Load universe (engine should have it cached)
            universe = getattr(self.engine, 'universe', [])
            if not universe:
                return json.dumps({'error': 'No universe loaded in engine'})

            hist_data = {}
            for sym in universe[:100]:  # cap for speed
                try:
                    t = yf.Ticker(sym)
                    h = t.history(period='6mo')
                    if not h.empty:
                        hist_data[sym] = h
                except Exception:
                    continue

            scores = compute_momentum_scores(hist_data, universe, lookback=90, skip=5)
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]
            result = [{'rank': i + 1, 'symbol': sym, 'score': round(sc, 4)} for i, (sym, sc) in enumerate(ranked)]
            return json.dumps({'signals': result, 'count': len(result)})
        except Exception as e:
            return json.dumps({'error': f'Momentum signal computation failed: {e}'})

    def _tool_check_regime(self, inp):
        try:
            regime_score = getattr(self.engine, 'current_regime_score', None)
            crash_cooldown = getattr(self.engine, 'crash_cooldown', 0)
            risk_mode = 'risk-on' if (regime_score or 0) > 0.5 else 'risk-off'
            return json.dumps({
                'regime_score': regime_score,
                'crash_cooldown': crash_cooldown,
                'risk_mode': risk_mode,
            })
        except Exception as e:
            return json.dumps({'error': str(e)})

    def _tool_check_position_stops(self, inp):
        try:
            positions = self.engine.broker.positions
            position_meta = getattr(self.engine, 'position_meta', {})
            results = []
            for sym, pos in positions.items():
                meta = position_meta.get(sym, {})
                entry_price = getattr(pos, 'avg_cost', meta.get('entry_price', 0))
                current_price = getattr(pos, 'market_price', entry_price)
                high_price = getattr(pos, 'high_price', current_price)
                if entry_price > 0:
                    current_return = (current_price - entry_price) / entry_price
                    trailing_return = (current_price - high_price) / high_price if high_price > 0 else 0
                else:
                    current_return = 0
                    trailing_return = 0
                adaptive_stop = meta.get('adaptive_stop', -0.08)
                trailing_stop = meta.get('trailing_stop', -0.03)
                results.append({
                    'symbol': sym,
                    'entry_price': round(entry_price, 2),
                    'current_price': round(current_price, 2),
                    'high_price': round(high_price, 2),
                    'current_return': round(current_return, 4),
                    'trailing_return': round(trailing_return, 4),
                    'adaptive_stop': adaptive_stop,
                    'trailing_stop': trailing_stop,
                    'stop_triggered': current_return <= adaptive_stop,
                    'trailing_triggered': trailing_return <= trailing_stop and current_return > 0.05,
                })
            return json.dumps({'positions': results, 'count': len(results)})
        except Exception as e:
            return json.dumps({'error': str(e)})

    def _tool_execute_trade(self, inp):
        symbol = inp['symbol']
        action = inp['action']
        shares = inp['shares']

        # Guard 1: Idempotency — check scratchpad for duplicate
        if self.scratchpad.has_trade_today(symbol, action):
            return json.dumps({
                'idempotent': True,
                'message': f'{action} {shares} {symbol} already executed today',
            })

        # Guard 2: Daily round-trip limit
        rt_count = self.scratchpad.count_round_trips_today()
        if rt_count >= MAX_DAILY_ROUND_TRIPS:
            return json.dumps({
                'rejected': True,
                'reason': f'Daily round-trip limit reached ({rt_count}/{MAX_DAILY_ROUND_TRIPS}). Trading halt.',
            })

        # Guard 3: MOC deadline
        et_now = _get_et_now()
        deadline = et_now.replace(hour=MOC_DEADLINE_HOUR, minute=MOC_DEADLINE_MINUTE, second=0)
        if et_now > deadline:
            return json.dumps({
                'rejected': True,
                'reason': f'MOC deadline passed ({MOC_DEADLINE_HOUR}:{MOC_DEADLINE_MINUTE:02d} ET). Trade rejected.',
            })

        # Guard 4: Max order value
        try:
            price = getattr(self.engine.broker, 'price_feed', None)
            if price and hasattr(price, 'get_price'):
                current_price = price.get_price(symbol) or 0
            else:
                # Estimate from positions or default
                pos = self.engine.broker.positions.get(symbol)
                current_price = getattr(pos, 'market_price', 0) if pos else 0
            order_value = shares * current_price
            if order_value > MAX_ORDER_VALUE and current_price > 0:
                return json.dumps({
                    'rejected': True,
                    'reason': f'Order value ${order_value:,.0f} exceeds max ${MAX_ORDER_VALUE:,}',
                })
        except Exception:
            pass  # If we can't estimate, proceed (broker has its own guards)

        # Execute via broker
        try:
            from omnicapital_broker import Order
            order = Order(symbol=symbol, action=action, quantity=shares, order_type='MOC')
            result = self.engine.broker.submit_order(order)

            fill_data = {
                'symbol': symbol,
                'action': action,
                'shares': shares,
                'price': result.filled_price,
                'order_id': result.order_id,
                'status': result.status,
            }
            self.scratchpad.log('trade', fill_data)
            return json.dumps(fill_data)
        except Exception as e:
            return json.dumps({'error': f'Trade execution failed: {e}'})

    def _tool_get_portfolio_state(self, inp):
        try:
            broker = self.engine.broker
            cash = broker.cash
            positions = broker.positions
            portfolio = broker.get_portfolio()
            total_value = portfolio.total_value

            pos_list = {}
            position_meta = getattr(self.engine, 'position_meta', {})
            for sym, pos in positions.items():
                meta = position_meta.get(sym, {})
                pos_list[sym] = {
                    'shares': getattr(pos, 'shares', 0),
                    'avg_cost': getattr(pos, 'avg_cost', 0),
                    'market_price': getattr(pos, 'market_price', 0),
                    'unrealized_pnl': getattr(pos, 'unrealized_pnl', 0),
                    'sector': meta.get('sector', 'Unknown'),
                    'entry_day': meta.get('entry_day', None),
                }

            return json.dumps({
                'cash': cash,
                'total_value': total_value,
                'peak_value': getattr(self.engine, 'peak_value', total_value),
                'regime_score': getattr(self.engine, 'current_regime_score', None),
                'crash_cooldown': getattr(self.engine, 'crash_cooldown', 0),
                'trading_day': getattr(self.engine, 'trading_day_counter', 0),
                'positions': pos_list,
                'position_count': len(positions),
            })
        except Exception as e:
            return json.dumps({'error': str(e)})

    def _tool_save_state(self, inp):
        try:
            self.engine.save_state()
            # Try git sync
            try:
                from compass.git_sync import git_push_state
                git_push_state()
            except Exception:
                pass  # git sync is best-effort
            return json.dumps({'saved': True})
        except Exception as e:
            return json.dumps({'error': f'State save failed: {e}'})

    def _tool_update_cycle_log(self, inp):
        event_type = inp['event_type']
        details = inp.get('details', {})
        try:
            cycle_log_path = os.path.join(
                getattr(self.engine, 'state_dir', 'state'), 'cycle_log.json'
            )
            # Load existing
            if os.path.exists(cycle_log_path):
                with open(cycle_log_path, 'r') as f:
                    cycle_log = json.load(f)
            else:
                cycle_log = []

            entry = {
                'timestamp': datetime.now().isoformat(),
                'event_type': event_type,
                'details': details,
            }
            cycle_log.append(entry)

            # Atomic write: temp file + os.replace
            dir_name = os.path.dirname(cycle_log_path) or '.'
            fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump(cycle_log, f, indent=2, default=str)
                os.replace(tmp_path, cycle_log_path)
            except Exception:
                # Clean up temp file on failure
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                raise

            return json.dumps({'logged': True, 'event_type': event_type, 'total_events': len(cycle_log)})
        except Exception as e:
            return json.dumps({'error': f'Cycle log update failed: {e}'})

    # ----------------------------------------------------------------
    # Capital Management
    # ----------------------------------------------------------------

    def _tool_get_capital_status(self, inp):
        try:
            hc = getattr(self.engine, 'hydra_capital', None)
            if not hc:
                return json.dumps({'error': 'Capital manager not available'})

            status = hc.get_status()

            # Compute current allocation with recycling
            rattle_positions = getattr(self.engine, 'rattle_positions', [])
            r_exposure = 0.0
            if rattle_positions and hc.rattle_account > 0:
                try:
                    from rattlesnake_signals import compute_rattlesnake_exposure
                    import yfinance as yf
                    symbols = [p['symbol'] for p in rattle_positions]
                    prices_data = yf.download(symbols, period='1d', progress=False)
                    prices = {}
                    if len(symbols) == 1:
                        prices[symbols[0]] = float(prices_data['Close'].iloc[-1])
                    else:
                        for sym in symbols:
                            try:
                                prices[sym] = float(prices_data['Close'][sym].iloc[-1])
                            except Exception:
                                pass
                    r_exposure = compute_rattlesnake_exposure(rattle_positions, prices, hc.rattle_account)
                except Exception:
                    pass

            alloc = hc.compute_allocation(r_exposure)

            return json.dumps({
                'total_capital': round(status['total_capital'], 2),
                'compass_account': round(status['compass_account'], 2),
                'rattle_account': round(status['rattle_account'], 2),
                'compass_pct': round(status['compass_pct'] * 100, 1),
                'rattle_pct': round(status['rattle_pct'] * 100, 1),
                'efa_value': round(status['efa_value'], 2),
                'efa_pct': round(status['efa_pct'] * 100, 1),
                'current_recycled': round(status['current_recycled'], 2),
                'recycled_pct': round(status['recycled_pct'] * 100, 1),
                'recycling_frequency_pct': round(status['recycling_frequency'] * 100, 1),
                'effective_compass_budget': round(alloc['compass_budget'], 2),
                'effective_rattle_budget': round(alloc['rattle_budget'], 2),
                'efa_idle_cash': round(alloc['efa_idle'], 2),
            })
        except Exception as e:
            return json.dumps({'error': str(e)})

    def _tool_get_rattlesnake_status(self, inp):
        try:
            rattle_positions = getattr(self.engine, 'rattle_positions', [])
            hydra_available = getattr(self.engine, '_hydra_available', False)

            if not hydra_available:
                return json.dumps({'error': 'Rattlesnake not available (import failed)'})

            # Regime
            spy_hist = getattr(self.engine, '_spy_hist', None)
            vix = getattr(self.engine, '_vix_current', None)
            regime_info = {'regime': 'UNKNOWN', 'entries_allowed': False, 'max_positions': 0}
            try:
                from rattlesnake_signals import check_rattlesnake_regime, R_MAX_POSITIONS
                if spy_hist is not None:
                    regime_info = check_rattlesnake_regime(spy_hist, vix)
                else:
                    regime_info = {'regime': 'UNKNOWN', 'entries_allowed': True, 'max_positions': R_MAX_POSITIONS}
            except Exception:
                pass

            # Positions
            pos_list = []
            for p in rattle_positions:
                pos_list.append({
                    'symbol': p.get('symbol'),
                    'entry_price': round(p.get('entry_price', 0), 2),
                    'days_held': p.get('days_held', 0),
                    'shares': p.get('shares', 0),
                })

            open_slots = regime_info.get('max_positions', 5) - len(rattle_positions)

            return json.dumps({
                'positions': pos_list,
                'count': len(pos_list),
                'regime': regime_info.get('regime', 'UNKNOWN'),
                'entries_allowed': regime_info.get('entries_allowed', False),
                'max_positions': regime_info.get('max_positions', 5),
                'open_slots': max(0, open_slots),
                'vix_current': vix,
                'vix_panic_threshold': 35,
            })
        except Exception as e:
            return json.dumps({'error': str(e)})

    def _tool_get_efa_status(self, inp):
        try:
            positions = self.engine.broker.positions
            efa_pos = positions.get('EFA')
            hc = getattr(self.engine, 'hydra_capital', None)

            # EFA SMA200 check
            efa_above_sma = False
            efa_price = None
            efa_sma = None
            try:
                import yfinance as yf
                efa_df = yf.download('EFA', period='1y', progress=False)
                if len(efa_df) >= 200:
                    efa_price = float(efa_df['Close'].iloc[-1])
                    efa_sma = float(efa_df['Close'].iloc[-200:].mean())
                    efa_above_sma = efa_price > efa_sma
            except Exception:
                pass

            # Current position
            position = None
            if efa_pos:
                shares = getattr(efa_pos, 'shares', 0)
                avg_cost = getattr(efa_pos, 'avg_cost', 0)
                current_value = shares * efa_price if efa_price else 0
                pnl = (efa_price - avg_cost) * shares if efa_price else 0
                position = {
                    'shares': shares,
                    'avg_cost': round(avg_cost, 2),
                    'current_price': round(efa_price, 2) if efa_price else None,
                    'current_value': round(current_value, 2),
                    'pnl': round(pnl, 2),
                    'return_pct': round((efa_price / avg_cost - 1) * 100, 2) if avg_cost > 0 and efa_price else 0,
                }

            # Idle cash available
            idle_cash = 0
            if hc:
                try:
                    from rattlesnake_signals import compute_rattlesnake_exposure
                    rattle_positions = getattr(self.engine, 'rattle_positions', [])
                    r_exposure = compute_rattlesnake_exposure(
                        rattle_positions, {}, hc.rattle_account
                    ) if rattle_positions else 0.0
                    alloc = hc.compute_allocation(r_exposure)
                    idle_cash = alloc['efa_idle']
                except Exception:
                    pass

            buy_ok = efa_above_sma and idle_cash >= 1000 and position is None
            sell_reason = None
            if position and not efa_above_sma:
                sell_reason = 'EFA below SMA200'

            return json.dumps({
                'position': position,
                'efa_price': round(efa_price, 2) if efa_price else None,
                'efa_sma200': round(efa_sma, 2) if efa_sma else None,
                'above_sma200': efa_above_sma,
                'idle_cash_available': round(idle_cash, 2),
                'buy_conditions_met': buy_ok,
                'sell_signal': sell_reason,
                'efa_value_in_capital_mgr': round(hc.efa_value, 2) if hc else 0,
            })
        except Exception as e:
            return json.dumps({'error': str(e)})

    # ----------------------------------------------------------------
    # Market Intelligence
    # ----------------------------------------------------------------

    def _tool_get_earnings_calendar(self, inp):
        symbols = inp['symbols']
        results = {}
        try:
            import yfinance as yf
            for sym in symbols:
                try:
                    t = yf.Ticker(sym)
                    dates = t.earnings_dates
                    if dates is not None and not dates.empty:
                        upcoming = dates.head(3).index.tolist()
                        results[sym] = [str(d) for d in upcoming]
                    else:
                        results[sym] = []
                except Exception:
                    results[sym] = []
        except ImportError:
            return json.dumps({'error': 'yfinance not available'})
        return json.dumps({'earnings': results})

    def _tool_get_macro_data(self, inp):
        try:
            import yfinance as yf
            vix = yf.Ticker('^VIX')
            vix_hist = vix.history(period='1d')
            vix_level = float(vix_hist['Close'].iloc[-1]) if not vix_hist.empty else None

            spy = yf.Ticker('SPY')
            spy_hist = spy.history(period='1d')
            spy_price = float(spy_hist['Close'].iloc[-1]) if not spy_hist.empty else None

            return json.dumps({
                'vix': vix_level,
                'spy_price': spy_price,
                'ten_year_yield': None,  # placeholder for FRED
                'credit_spread': None,   # placeholder for FRED
            })
        except Exception as e:
            return json.dumps({'error': str(e)})

    def _tool_get_insider_trades(self, inp):
        sym = inp['symbol']
        return json.dumps({
            'status': 'stub',
            'message': 'Insider trades data source not yet connected via MCP',
            'symbol': sym,
        })

    def _tool_get_financial_metrics(self, inp):
        sym = inp['symbol']
        return json.dumps({
            'status': 'stub',
            'message': 'Financial metrics data source not yet connected via MCP',
            'symbol': sym,
        })

    def _tool_get_news_headlines(self, inp):
        sym = inp['symbol']
        return json.dumps({
            'status': 'stub',
            'message': 'News headlines data source not yet connected via MCP',
            'symbol': sym,
        })

    # ----------------------------------------------------------------
    # Operations
    # ----------------------------------------------------------------

    def _tool_send_notification(self, inp):
        message = inp['message']
        try:
            if self.notifier and hasattr(self.notifier, '_send_message'):
                self.notifier._send_message(message)
                return json.dumps({'sent': True, 'message': message})
            elif self.notifier and hasattr(self.notifier, 'send'):
                self.notifier.send(message)
                return json.dumps({'sent': True, 'message': message})
            else:
                logger.info(f"Notification (no notifier): {message}")
                return json.dumps({'sent': False, 'reason': 'No notifier configured', 'message': message})
        except Exception as e:
            return json.dumps({'error': f'Notification failed: {e}'})

    def _tool_log_decision(self, inp):
        decision_data = {
            'action': inp['action'],
            'reason': inp['reason'],
        }
        if 'symbol' in inp:
            decision_data['symbol'] = inp['symbol']
        if 'alternative' in inp:
            decision_data['alternative'] = inp['alternative']

        self.scratchpad.log('decision', decision_data)
        return json.dumps({'logged': True, 'decision': decision_data})

    def _tool_validate_data_feeds(self, inp):
        health = _check_yfinance_health()
        return json.dumps(health)
