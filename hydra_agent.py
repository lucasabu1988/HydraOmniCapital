"""HYDRA autonomous agent — scheduling loop + Claude API orchestration.

Main entry point for the HYDRA Worker service. Runs a daily schedule:
  PRE_MARKET_BRIEFING  — 06:30 ET
  INTRADAY_MONITOR     — 10:00-15:25 ET (every 15 min, pure Python)
  PRE_CLOSE_DECISION   — 15:30 ET
  POST_CLOSE_SUMMARY   — 16:15 ET
"""

import os
import json
import time
import logging
from datetime import datetime, date

import anthropic

from hydra_scratchpad import HydraScratchpad
from hydra_tools import HydraToolExecutor, TOOL_DEFINITIONS, _get_et_now
from hydra_prompts import build_system_prompt

logger = logging.getLogger(__name__)

AGENT_MODEL = 'claude-sonnet-4-20250514'
MAX_AGENT_TURNS = 20

SCHEDULE = [
    {
        'phase': 'PRE_MARKET_BRIEFING',
        'hour': 6,
        'minute': 30,
    },
    {
        'phase': 'INTRADAY_MONITOR',
        'hour': 10,
        'minute': 0,
        'repeat_minutes': 15,
        'end_hour': 15,
        'end_minute': 25,
    },
    {
        'phase': 'PRE_CLOSE_DECISION',
        'hour': 15,
        'minute': 30,
    },
    {
        'phase': 'POST_CLOSE_SUMMARY',
        'hour': 16,
        'minute': 15,
    },
]

# US market holidays (month, day) — fixed-date holidays
_FIXED_HOLIDAYS = {
    (1, 1),    # New Year's Day
    (6, 19),   # Juneteenth
    (7, 4),    # Independence Day
    (12, 25),  # Christmas Day
}


class HydraAgent:

    def __init__(self, state_dir=None):
        self.state_dir = state_dir or os.environ.get('STATE_DIR', 'state')
        os.makedirs(self.state_dir, exist_ok=True)

        self._configure_git_auth()

        self.scratchpad = HydraScratchpad(state_dir=self.state_dir)
        self.scratchpad.cleanup(max_age_days=90)

        self.engine = None
        self._init_engine()

        self.notifier = self._init_notifier()

        self.tools = HydraToolExecutor(
            engine=self.engine,
            scratchpad=self.scratchpad,
            notifier=self.notifier,
        )

        self.client = anthropic.Anthropic(
            api_key=os.environ.get('ANTHROPIC_API_KEY'),
        )

        self.cmd_handler = self._init_cmd_handler()

        self._phases_run_today = {}
        self._last_intraday_run = None
        self._token_usage = {}  # {phase: {input_tokens, output_tokens, api_calls}}

    def _init_cmd_handler(self):
        try:
            bot_token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
            chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
            if bot_token and chat_id:
                from compass.notifications import TelegramCommandHandler
                return TelegramCommandHandler(
                    bot_token=bot_token, chat_id=chat_id,
                    engine=self.engine, state_dir=self.state_dir,
                )
        except Exception as e:
            logger.debug(f"Telegram command handler not available: {e}")
        return None

    def _configure_git_auth(self):
        """Configure git remote with token auth for Render (enables state push)."""
        git_token = os.environ.get('GIT_TOKEN', '')
        if not git_token:
            return
        try:
            import subprocess
            # Set remote URL with token for push access
            url = f'https://x-access-token:{git_token}@github.com/lucasabu1988/NuevoProyecto.git'
            subprocess.run(['git', 'remote', 'set-url', 'origin', url],
                           capture_output=True, timeout=10)
            logger.info("Git auth configured for state sync")
        except Exception as e:
            logger.debug(f"Git auth setup failed (non-critical): {e}")

    def _init_engine(self):
        from omnicapital_live import COMPASSLive, CONFIG
        config = dict(CONFIG)
        broker_type = os.environ.get('BROKER_TYPE')
        if broker_type:
            config['BROKER_TYPE'] = broker_type
        self.engine = COMPASSLive(config=config)
        try:
            self.engine.load_state()
        except Exception as e:
            logger.warning(f"Could not load engine state: {e}")

    def _init_notifier(self):
        # Try Telegram first, then WhatsApp fallback
        try:
            bot_token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
            chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
            if bot_token and chat_id:
                from compass.notifications import TelegramNotifier
                return TelegramNotifier(bot_token=bot_token, chat_id=chat_id)
        except Exception as e:
            logger.debug(f"Telegram not available: {e}")
        try:
            phone = os.environ.get('WHATSAPP_PHONE', '')
            apikey = os.environ.get('WHATSAPP_API_KEY', '')
            if phone and apikey:
                from compass.notifications import WhatsAppNotifier
                return WhatsAppNotifier(phone=phone, apikey=apikey)
        except Exception as e:
            logger.debug(f"WhatsApp not available: {e}")
        return None

    def _check_kill_switch(self):
        stop_file = os.path.join(self.state_dir, 'STOP_TRADING')
        return os.path.exists(stop_file)

    def _is_trading_day(self):
        now = _get_et_now()
        # Weekend check
        if now.weekday() >= 5:
            return False
        # Holiday check
        if (now.month, now.day) in _FIXED_HOLIDAYS:
            return False
        # Floating holidays
        if self._is_floating_holiday(now):
            return False
        return True

    @staticmethod
    def _get_market_holidays(year):
        holidays = set()
        # Fixed holidays
        for month, day in _FIXED_HOLIDAYS:
            holidays.add(date(year, month, day))
        # MLK Day — 3rd Monday of January
        holidays.add(_nth_weekday(year, 1, 0, 3))
        # Presidents Day — 3rd Monday of February
        holidays.add(_nth_weekday(year, 2, 0, 3))
        # Memorial Day — last Monday of May
        holidays.add(_last_weekday(year, 5, 0))
        # Labor Day — 1st Monday of September
        holidays.add(_nth_weekday(year, 9, 0, 1))
        # Thanksgiving — 4th Thursday of November
        holidays.add(_nth_weekday(year, 11, 3, 4))
        return holidays

    def _is_floating_holiday(self, now):
        try:
            holidays = self._get_market_holidays(now.year)
            today = now.date() if hasattr(now, 'date') else date(now.year, now.month, now.day)
            return today in holidays
        except Exception:
            return False

    def _check_daily_loss_halt(self):
        try:
            history = getattr(self.engine, 'portfolio_values_history', [])
            if not history:
                return False
            last_value = history[-1]
            portfolio = self.engine.broker.get_portfolio()
            current_value = portfolio.total_value
            if last_value <= 0:
                return False
            daily_return = (current_value - last_value) / last_value
            if daily_return <= -0.03:
                logger.warning(f"Daily loss halt triggered: {daily_return:.2%}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error checking daily loss: {e}")
            return False

    def _execute_immediate_stop(self, symbol):
        try:
            pos = self.engine.broker.positions.get(symbol)
            if pos is None:
                logger.warning(f"Stop: position {symbol} not found")
                return
            shares = getattr(pos, 'shares', 0)
            if shares <= 0:
                return
            from omnicapital_broker import Order
            order = Order(symbol=symbol, action='SELL', quantity=shares, order_type='MOC')
            result = self.engine.broker.submit_order(order)
            self.scratchpad.log('stop_event', {
                'symbol': symbol,
                'shares': shares,
                'action': 'SELL',
                'reason': 'adaptive_stop_triggered',
                'order_id': getattr(result, 'order_id', None),
                'status': getattr(result, 'status', None),
            })
            try:
                self.engine.save_state()
            except Exception:
                pass
            logger.info(f"Stop executed: SELL {shares} {symbol}")
        except Exception as e:
            logger.error(f"Stop execution failed for {symbol}: {e}")

    def _check_and_execute_stops(self, stop_results):
        escalations = []
        for result in stop_results:
            if result.get('stop_triggered'):
                symbol = result['symbol']
                self._execute_immediate_stop(symbol)
                escalations.append(result)
        return escalations

    def _detect_partial_rotation(self):
        entries = self.scratchpad.read_today()
        sells = 0
        buys = 0
        for entry in entries:
            if entry['type'] == 'trade':
                data = entry.get('data', {})
                action = data.get('action', '')
                if action == 'SELL':
                    sells += 1
                elif action == 'BUY':
                    buys += 1
        partial = sells > 0 and buys == 0
        return {'sells': sells, 'buys': buys, 'partial': partial}

    def _get_portfolio_state_dict(self):
        try:
            broker = self.engine.broker
            positions = broker.positions
            position_meta = getattr(self.engine, 'position_meta', {})
            pos_dict = {}
            for sym, pos in positions.items():
                meta = position_meta.get(sym, {})
                pos_dict[sym] = {
                    'shares': getattr(pos, 'shares', 0),
                    'avg_cost': getattr(pos, 'avg_cost', 0),
                    'sector': meta.get('sector', 'Unknown'),
                }
            return {
                'cash': broker.cash,
                'total_value': broker.get_portfolio().total_value,
                'positions': pos_dict,
                'regime_score': getattr(self.engine, 'current_regime_score', None),
                'crash_cooldown': getattr(self.engine, 'crash_cooldown', 0),
                'trading_day': getattr(self.engine, 'trading_day_counter', 0),
            }
        except Exception as e:
            logger.error(f"Error building portfolio state: {e}")
            return {'error': str(e)}

    def _call_claude(self, phase, user_message):
        portfolio_state = self._get_portfolio_state_dict()
        scratchpad_summary = self.scratchpad.summarize_phase(phase)
        et_now = _get_et_now()
        et_time = et_now.strftime('%Y-%m-%d %H:%M ET')

        system_prompt = build_system_prompt(
            phase=phase,
            portfolio_state=portfolio_state,
            scratchpad_summary=scratchpad_summary,
            et_time=et_time,
        )

        messages = [{'role': 'user', 'content': user_message}]

        for turn in range(MAX_AGENT_TURNS):
            response = None
            for attempt in range(3):
                try:
                    response = self.client.messages.create(
                        model=AGENT_MODEL,
                        max_tokens=4096,
                        system=system_prompt,
                        tools=TOOL_DEFINITIONS,
                        messages=messages,
                    )
                    break
                except Exception as e:
                    logger.error(f"Claude API error (turn {turn}, attempt {attempt+1}/3): {e}")
                    if attempt < 2:
                        time.sleep(2 ** attempt)  # 1s, 2s backoff
            if response is None:
                logger.error(f"Claude API failed after 3 attempts, aborting phase {phase}")
                break

            # Track token usage
            if hasattr(response, 'usage'):
                usage = self._token_usage.setdefault(phase, {'input_tokens': 0, 'output_tokens': 0, 'api_calls': 0})
                usage['input_tokens'] += getattr(response.usage, 'input_tokens', 0)
                usage['output_tokens'] += getattr(response.usage, 'output_tokens', 0)
                usage['api_calls'] += 1

            # Process response content
            assistant_content = response.content
            messages.append({'role': 'assistant', 'content': assistant_content})

            # Check for tool use
            tool_calls = [block for block in assistant_content if block.type == 'tool_use']
            if not tool_calls:
                # No tool calls — conversation complete
                break

            # Dispatch tool calls
            tool_results = []
            for tc in tool_calls:
                tool_name = tc.name
                tool_input = tc.input

                if not self.scratchpad.check_tool_limit(tool_name, phase):
                    result_content = json.dumps({
                        'error': f'Tool limit exceeded for {tool_name} in {phase}',
                    })
                else:
                    result_content = self.tools.dispatch(tool_name, tool_input)

                tool_results.append({
                    'type': 'tool_result',
                    'tool_use_id': tc.id,
                    'content': result_content,
                })

            messages.append({'role': 'user', 'content': tool_results})

            # Check stop reason
            if response.stop_reason == 'end_turn':
                break

        # Log token usage for this phase
        usage = self._token_usage.get(phase, {})
        if usage:
            logger.info(f"API usage [{phase}]: {usage.get('input_tokens', 0)} in / {usage.get('output_tokens', 0)} out / {usage.get('api_calls', 0)} calls")
            self.scratchpad.log('api_usage', {
                'phase': phase,
                'input_tokens': usage.get('input_tokens', 0),
                'output_tokens': usage.get('output_tokens', 0),
                'api_calls': usage.get('api_calls', 0),
            })

        # Extract final text response
        final_text = ''
        for block in assistant_content:
            if hasattr(block, 'text'):
                final_text += block.text
        return final_text

    # ---------------------------------------------------------------
    # Phase runners
    # ---------------------------------------------------------------

    def run_pre_market(self):
        logger.info("=== PRE_MARKET_BRIEFING ===")
        self.scratchpad.log('briefing', {'phase': 'PRE_MARKET_BRIEFING', 'start': datetime.now().isoformat()})

        # Detect partial rotation from previous session
        rotation_status = self._detect_partial_rotation()
        if rotation_status['partial']:
            logger.warning(f"Partial rotation detected: {rotation_status}")

        user_msg = "Begin pre-market briefing. Load portfolio state, validate data feeds, check earnings calendar, and send morning summary."
        if rotation_status['partial']:
            user_msg += f"\n\nALERT: Partial rotation detected from previous session — {rotation_status['sells']} sells, {rotation_status['buys']} buys. Investigate and complete rotation if needed."

        result = self._call_claude('PRE_MARKET_BRIEFING', user_msg)
        logger.info(f"Pre-market complete: {result[:200]}")
        return result

    def run_intraday_check(self):
        logger.debug("--- INTRADAY_MONITOR (Python) ---")

        # Pure Python — no Claude call unless anomaly
        try:
            stop_data = self.tools.dispatch('check_position_stops', {})
            stop_results = json.loads(stop_data).get('positions', [])
        except Exception as e:
            logger.error(f"Intraday stop check failed: {e}")
            return

        # Execute stops immediately
        escalations = self._check_and_execute_stops(stop_results)

        # Check daily loss halt
        loss_halt = self._check_daily_loss_halt()

        # Escalate to Claude only on anomaly
        if escalations or loss_halt:
            anomaly_msg = "INTRADAY ANOMALY ESCALATION:\n"
            if escalations:
                anomaly_msg += f"Stops triggered: {json.dumps(escalations, default=str)}\n"
            if loss_halt:
                anomaly_msg += "Daily loss halt triggered (>3% drawdown). Halt all entries.\n"
            self.scratchpad.log('alert', {'phase': 'INTRADAY_MONITOR', 'escalations': len(escalations), 'loss_halt': loss_halt})
            result = self._call_claude('INTRADAY_MONITOR', anomaly_msg)
            logger.info(f"Intraday escalation handled: {result[:200]}")
            return result

        return None

    def run_pre_close(self):
        logger.info("=== PRE_CLOSE_DECISION ===")
        self.scratchpad.log('briefing', {'phase': 'PRE_CLOSE_DECISION', 'start': datetime.now().isoformat()})

        user_msg = "Execute pre-close decision workflow. Load momentum signals, check regime, review stops, identify exits and entries, execute trades by 15:50 ET, save state, and send summary."
        result = self._call_claude('PRE_CLOSE_DECISION', user_msg)
        logger.info(f"Pre-close complete: {result[:200]}")
        return result

    def run_post_close(self):
        logger.info("=== POST_CLOSE_SUMMARY ===")
        self.scratchpad.log('briefing', {'phase': 'POST_CLOSE_SUMMARY', 'start': datetime.now().isoformat()})

        user_msg = "Compile post-close daily summary. Review all decisions, calculate P&L, update cycle log, and send end-of-day report."
        result = self._call_claude('POST_CLOSE_SUMMARY', user_msg)

        # Log summary
        self.scratchpad.log('summary', {'phase': 'POST_CLOSE_SUMMARY', 'result': result[:500]})
        logger.info(f"Post-close complete: {result[:200]}")
        return result

    # ---------------------------------------------------------------
    # Schedule management
    # ---------------------------------------------------------------

    def _run_schedule(self, now):
        today_key = now.strftime('%Y-%m-%d')

        # Reset daily tracking if new day
        if not hasattr(self, '_current_day') or self._current_day != today_key:
            self._current_day = today_key
            self._phases_run_today = {}
            self._last_intraday_run = None

        for entry in SCHEDULE:
            phase = entry['phase']
            sched_hour = entry['hour']
            sched_minute = entry['minute']

            if phase == 'INTRADAY_MONITOR':
                # Repeating phase
                end_hour = entry.get('end_hour', 15)
                end_minute = entry.get('end_minute', 25)
                repeat_minutes = entry.get('repeat_minutes', 15)

                # Check if within intraday window
                start_time = sched_hour * 60 + sched_minute
                end_time = end_hour * 60 + end_minute
                now_time = now.hour * 60 + now.minute

                if start_time <= now_time <= end_time:
                    # Check if enough time since last run
                    if self._last_intraday_run is None:
                        should_run = True
                    else:
                        elapsed = (now - self._last_intraday_run).total_seconds() / 60
                        should_run = elapsed >= repeat_minutes
                    if should_run:
                        try:
                            self.run_intraday_check()
                        except Exception as e:
                            logger.error(f"Intraday check failed: {e}")
                        self._last_intraday_run = now
            else:
                # One-time phase — 5-minute window
                if phase in self._phases_run_today:
                    continue
                now_minutes = now.hour * 60 + now.minute
                sched_minutes = sched_hour * 60 + sched_minute
                if sched_minutes <= now_minutes <= sched_minutes + 5:
                    try:
                        if phase == 'PRE_MARKET_BRIEFING':
                            self.run_pre_market()
                        elif phase == 'PRE_CLOSE_DECISION':
                            self.run_pre_close()
                        elif phase == 'POST_CLOSE_SUMMARY':
                            self.run_post_close()
                    except Exception as e:
                        logger.error(f"Phase {phase} failed: {e}")
                    self._phases_run_today[phase] = now.isoformat()

    def _write_heartbeat(self, now):
        heartbeat = {
            'ts': now.isoformat(),
            'phase': list(self._phases_run_today.keys()),
            'token_usage': self._token_usage,
            'kill_switch': self._check_kill_switch(),
        }
        path = os.path.join(self.state_dir, 'agent_heartbeat.json')
        try:
            with open(path, 'w') as f:
                json.dump(heartbeat, f, indent=2, default=str)
        except Exception:
            pass

    def run(self):
        logger.info("HYDRA Agent starting...")
        while True:
            try:
                if self._check_kill_switch():
                    logger.warning("Kill switch active — halting")
                    time.sleep(60)
                    continue

                if not self._is_trading_day():
                    logger.debug("Not a trading day — sleeping 5 min")
                    time.sleep(300)
                    continue

                now = _get_et_now()
                self._run_schedule(now)

                # Write heartbeat
                self._write_heartbeat(now)

                # Poll Telegram commands
                if self.cmd_handler:
                    try:
                        self.cmd_handler.poll()
                    except Exception as e:
                        logger.debug(f"Telegram poll error: {e}")

            except KeyboardInterrupt:
                logger.info("HYDRA Agent stopped by user")
                break
            except Exception as e:
                logger.error(f"Main loop error: {e}", exc_info=True)

            time.sleep(30)


# ---------------------------------------------------------------------------
# Helpers for floating holiday calculation
# ---------------------------------------------------------------------------

def _nth_weekday(year, month, weekday, n):
    """Return the nth occurrence of a weekday in a month (1-indexed)."""
    d = date(year, month, 1)
    count = 0
    while True:
        if d.weekday() == weekday:
            count += 1
            if count == n:
                return d
        d = d.replace(day=d.day + 1)


def _last_weekday(year, month, weekday):
    """Return the last occurrence of a weekday in a month."""
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    d = next_month.replace(day=next_month.day - 1) if next_month.day > 1 else date(year, month, 28)
    # Go to last day of month
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    d = date(year, month, last_day)
    while d.weekday() != weekday:
        d = d.replace(day=d.day - 1)
    return d


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                os.path.join('logs', f'hydra_agent_{datetime.now().strftime("%Y%m%d")}.log'),
                encoding='utf-8',
            ),
        ],
    )
    os.makedirs('logs', exist_ok=True)

    agent = HydraAgent()
    agent.run()


if __name__ == '__main__':
    main()
