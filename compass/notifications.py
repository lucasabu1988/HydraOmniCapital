"""
OmniCapital v8.2 COMPASS - Email Notifications Module
======================================================
Sends email alerts for trades, stop losses, regime changes,
daily summaries, and system errors.
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)


class EmailNotifier:
    """Email notification system for COMPASS live trading"""

    def __init__(self, smtp_server: str = 'smtp.gmail.com',
                 smtp_port: int = 587,
                 sender: str = '',
                 password: str = '',
                 recipients: List[str] = None,
                 **kwargs):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.sender = sender
        self.password = password
        self.recipients = recipients or []
        self._enabled = bool(sender and password and self.recipients)

        if self._enabled:
            logger.info(f"EmailNotifier configured: {sender} -> {self.recipients}")
        else:
            logger.warning("EmailNotifier not configured (missing credentials)")

    def _send_email(self, subject: str, body: str, priority: str = 'normal'):
        """Send an email. Priority: 'normal', 'high'"""
        if not self._enabled:
            logger.debug(f"Email skipped (not configured): {subject}")
            return

        try:
            msg = MIMEMultipart()
            msg['From'] = self.sender
            msg['To'] = ', '.join(self.recipients)
            msg['Subject'] = subject

            if priority == 'high':
                msg['X-Priority'] = '1'
                msg['X-MSMail-Priority'] = 'High'

            msg.attach(MIMEText(body, 'html'))

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender, self.password)
                server.send_message(msg)

            logger.info(f"Email sent: {subject}")

        except Exception as e:
            logger.error(f"Failed to send email: {e}")

    # ------------------------------------------------------------------
    # Trade alerts
    # ------------------------------------------------------------------

    def send_trade_alert(self, action: str, symbol: str, shares: float,
                         price: float, exit_reason: Optional[str] = None,
                         pnl: Optional[float] = None):
        """Send alert on trade entry or exit"""
        if action == 'BUY':
            subject = f"COMPASS: BUY {symbol} @ ${price:.2f}"
            color = '#28a745'
            body = f"""
            <h2 style="color:{color}">New Position: {symbol}</h2>
            <table style="font-size:14px;">
                <tr><td><b>Action:</b></td><td>BUY</td></tr>
                <tr><td><b>Symbol:</b></td><td>{symbol}</td></tr>
                <tr><td><b>Shares:</b></td><td>{shares:.2f}</td></tr>
                <tr><td><b>Price:</b></td><td>${price:.2f}</td></tr>
                <tr><td><b>Value:</b></td><td>${shares * price:,.0f}</td></tr>
                <tr><td><b>Time:</b></td><td>{datetime.now().strftime('%Y-%m-%d %H:%M ET')}</td></tr>
            </table>
            """
        else:
            pnl_str = f"${pnl:+,.0f}" if pnl is not None else "N/A"
            pnl_color = '#28a745' if pnl and pnl > 0 else '#dc3545'
            reason = exit_reason or 'manual'
            subject = f"COMPASS: SELL {symbol} [{reason}] PnL {pnl_str}"
            body = f"""
            <h2 style="color:#dc3545">Position Closed: {symbol}</h2>
            <table style="font-size:14px;">
                <tr><td><b>Action:</b></td><td>SELL</td></tr>
                <tr><td><b>Symbol:</b></td><td>{symbol}</td></tr>
                <tr><td><b>Shares:</b></td><td>{shares:.2f}</td></tr>
                <tr><td><b>Price:</b></td><td>${price:.2f}</td></tr>
                <tr><td><b>Exit Reason:</b></td><td>{reason}</td></tr>
                <tr><td><b>P&L:</b></td><td style="color:{pnl_color}"><b>{pnl_str}</b></td></tr>
                <tr><td><b>Time:</b></td><td>{datetime.now().strftime('%Y-%m-%d %H:%M ET')}</td></tr>
            </table>
            """

        self._send_email(subject, body)

    # ------------------------------------------------------------------
    # Portfolio stop loss
    # ------------------------------------------------------------------

    def send_portfolio_stop_alert(self, portfolio_value: float,
                                  drawdown: float, peak_value: float):
        """URGENT alert when portfolio stop loss triggers"""
        subject = f"COMPASS STOP LOSS: DD {drawdown:.1%} | ${portfolio_value:,.0f}"
        body = f"""
        <h1 style="color:#dc3545">PORTFOLIO STOP LOSS TRIGGERED</h1>
        <table style="font-size:16px;">
            <tr><td><b>Portfolio Value:</b></td><td>${portfolio_value:,.0f}</td></tr>
            <tr><td><b>Peak Value:</b></td><td>${peak_value:,.0f}</td></tr>
            <tr><td><b>Drawdown:</b></td><td style="color:#dc3545"><b>{drawdown:.1%}</b></td></tr>
            <tr><td><b>Time:</b></td><td>{datetime.now().strftime('%Y-%m-%d %H:%M ET')}</td></tr>
        </table>
        <hr>
        <p>All positions have been closed. System entering Protection Mode Stage 1 (0.3x leverage).</p>
        <p>Recovery timeline:</p>
        <ul>
            <li>Stage 1 (63 trading days): 0.3x leverage, 2 positions max</li>
            <li>Stage 2 (126 trading days): 1.0x leverage, 3 positions max</li>
            <li>Full recovery: normal vol-targeting leverage</li>
        </ul>
        <p><i>Recovery requires market in RISK_ON regime (SPY > SMA200).</i></p>
        """
        self._send_email(subject, body, priority='high')

    # ------------------------------------------------------------------
    # Regime change
    # ------------------------------------------------------------------

    def send_regime_change_alert(self, is_risk_on: bool,
                                 spy_price: float, sma_value: float):
        """Alert on regime change"""
        regime = "RISK_ON" if is_risk_on else "RISK_OFF"
        color = '#28a745' if is_risk_on else '#ffc107'
        positions = "5" if is_risk_on else "2"

        subject = f"COMPASS: Regime -> {regime}"
        body = f"""
        <h2 style="color:{color}">Regime Change: {regime}</h2>
        <table style="font-size:14px;">
            <tr><td><b>SPY Price:</b></td><td>${spy_price:.2f}</td></tr>
            <tr><td><b>SMA(200):</b></td><td>${sma_value:.2f}</td></tr>
            <tr><td><b>Max Positions:</b></td><td>{positions}</td></tr>
            <tr><td><b>Leverage:</b></td><td>{'Vol targeting' if is_risk_on else '1.0x fixed'}</td></tr>
            <tr><td><b>Time:</b></td><td>{datetime.now().strftime('%Y-%m-%d %H:%M ET')}</td></tr>
        </table>
        """
        self._send_email(subject, body)

    # ------------------------------------------------------------------
    # Daily summary
    # ------------------------------------------------------------------

    def send_daily_summary(self, portfolio_value: float, num_positions: int,
                           drawdown: float, trades_today: List[Dict],
                           is_risk_on: bool, leverage: float):
        """End-of-day summary email"""
        regime = "RISK_ON" if is_risk_on else "RISK_OFF"
        today = datetime.now().strftime('%Y-%m-%d')

        # Build trades table
        trades_html = ""
        if trades_today:
            trades_html = "<h3>Today's Trades</h3><table border='1' cellpadding='5' style='border-collapse:collapse;'>"
            trades_html += "<tr><th>Action</th><th>Symbol</th><th>Reason</th><th>P&L</th></tr>"
            for t in trades_today:
                pnl = t.get('pnl', 0)
                pnl_str = f"${pnl:+,.0f}" if pnl else "-"
                color = '#28a745' if t.get('action') == 'BUY' else '#dc3545'
                reason = t.get('exit_reason', '-')
                trades_html += f"<tr><td style='color:{color}'>{t.get('action','')}</td>"
                trades_html += f"<td>{t.get('symbol','')}</td><td>{reason}</td><td>{pnl_str}</td></tr>"
            trades_html += "</table>"
        else:
            trades_html = "<p>No trades executed today.</p>"

        total_pnl = sum(t.get('pnl', 0) for t in trades_today if t.get('action') == 'SELL')

        subject = f"COMPASS Daily: ${portfolio_value:,.0f} | {regime} | {len(trades_today)} trades"
        body = f"""
        <h2>COMPASS v8.2 Daily Summary - {today}</h2>
        <table style="font-size:14px;">
            <tr><td><b>Portfolio Value:</b></td><td>${portfolio_value:,.0f}</td></tr>
            <tr><td><b>Drawdown:</b></td><td>{drawdown:.1%}</td></tr>
            <tr><td><b>Positions:</b></td><td>{num_positions}</td></tr>
            <tr><td><b>Regime:</b></td><td>{regime}</td></tr>
            <tr><td><b>Leverage:</b></td><td>{leverage:.2f}x</td></tr>
            <tr><td><b>Day's P&L:</b></td><td>${total_pnl:+,.0f}</td></tr>
        </table>
        <hr>
        {trades_html}
        """
        self._send_email(subject, body)

    # ------------------------------------------------------------------
    # Recovery stage
    # ------------------------------------------------------------------

    def send_recovery_stage_alert(self, stage: int, portfolio_value: float):
        """Alert on recovery stage transition"""
        if stage == 0:
            title = "FULL RECOVERY"
            desc = "System returning to normal vol-targeting operation."
            color = '#28a745'
        elif stage == 2:
            title = "RECOVERY Stage 2"
            desc = "Advancing to 1.0x leverage, 3 positions max."
            color = '#ffc107'
        else:
            title = f"RECOVERY Stage {stage}"
            desc = "Recovery in progress."
            color = '#ffc107'

        subject = f"COMPASS: {title} | ${portfolio_value:,.0f}"
        body = f"""
        <h2 style="color:{color}">{title}</h2>
        <p>{desc}</p>
        <table style="font-size:14px;">
            <tr><td><b>Portfolio Value:</b></td><td>${portfolio_value:,.0f}</td></tr>
            <tr><td><b>Time:</b></td><td>{datetime.now().strftime('%Y-%m-%d %H:%M ET')}</td></tr>
        </table>
        """
        self._send_email(subject, body)

    # ------------------------------------------------------------------
    # Error alert
    # ------------------------------------------------------------------

    def send_error_alert(self, error_message: str, traceback_str: str = ''):
        """Alert on system errors"""
        subject = f"COMPASS ERROR: {error_message[:80]}"
        body = f"""
        <h2 style="color:#dc3545">System Error</h2>
        <p><b>Error:</b> {error_message}</p>
        <p><b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}</p>
        {'<pre>' + traceback_str + '</pre>' if traceback_str else ''}
        """
        self._send_email(subject, body, priority='high')

    # ------------------------------------------------------------------
    # Test
    # ------------------------------------------------------------------

    def send_test_email(self):
        """Send a test email to verify configuration"""
        subject = "COMPASS: Test Email"
        body = f"""
        <h2 style="color:#28a745">Email Configuration OK</h2>
        <p>COMPASS v8.2 email notifications are working correctly.</p>
        <p>Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        """
        self._send_email(subject, body)
        return True


class WhatsAppNotifier:
    """WhatsApp notification system via CallMeBot API.

    Setup (1 minute):
      1. Add +34 644 52 74 88 to contacts
      2. Send "I allow callmebot to send me messages" via WhatsApp
      3. You'll receive your API key
      4. Configure: WhatsAppNotifier(phone='+573001234567', apikey='123456')
    """

    def __init__(self, phone: str = '', apikey: str = '', **kwargs):
        self.phone = phone.replace('+', '').replace(' ', '').replace('-', '')
        self.apikey = apikey
        self._enabled = bool(self.phone and self.apikey)

        if self._enabled:
            logger.info(f"WhatsAppNotifier configured: +{self.phone}")
        else:
            logger.warning("WhatsAppNotifier not configured (missing phone or apikey)")

    def _send_message(self, text: str):
        """Send a WhatsApp message via CallMeBot. Never raises."""
        if not self._enabled:
            logger.debug(f"WhatsApp skipped (not configured)")
            return

        import urllib.request
        import urllib.parse

        url = (f"https://api.callmebot.com/whatsapp.php"
               f"?phone={self.phone}"
               f"&text={urllib.parse.quote(text)}"
               f"&apikey={self.apikey}")

        try:
            req = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(req, timeout=15) as resp:
                status = resp.status
            if status == 200:
                logger.info(f"WhatsApp sent: {text[:60]}...")
            else:
                logger.warning(f"WhatsApp API returned {status}")
        except Exception as e:
            logger.error(f"WhatsApp send failed: {e}")

    # ------------------------------------------------------------------
    # Trade alerts (same interface as EmailNotifier)
    # ------------------------------------------------------------------

    def send_trade_alert(self, action: str, symbol: str, shares: float,
                         price: float, exit_reason: Optional[str] = None,
                         pnl: Optional[float] = None):
        if action == 'BUY':
            text = (f"COMPASS BUY\n"
                    f"{symbol} | {shares:.1f} shares @ ${price:.2f}\n"
                    f"Value: ${shares * price:,.0f}\n"
                    f"{datetime.now().strftime('%H:%M ET')}")
        else:
            pnl_str = f"${pnl:+,.0f}" if pnl is not None else "N/A"
            reason = exit_reason or 'manual'
            text = (f"COMPASS SELL [{reason}]\n"
                    f"{symbol} @ ${price:.2f}\n"
                    f"P&L: {pnl_str}\n"
                    f"{datetime.now().strftime('%H:%M ET')}")
        self._send_message(text)

    def send_portfolio_stop_alert(self, portfolio_value: float,
                                  drawdown: float, peak_value: float):
        text = (f"PORTFOLIO STOP LOSS\n"
                f"DD: {drawdown:.1%} | ${portfolio_value:,.0f}\n"
                f"Peak: ${peak_value:,.0f}\n"
                f"Protection Mode activated\n"
                f"{datetime.now().strftime('%H:%M ET')}")
        self._send_message(text)

    def send_regime_change_alert(self, is_risk_on: bool,
                                 spy_price: float, sma_value: float):
        regime = "RISK_ON" if is_risk_on else "RISK_OFF"
        n_pos = 5 if is_risk_on else 2
        text = (f"REGIME -> {regime}\n"
                f"SPY: ${spy_price:.2f} | SMA200: ${sma_value:.2f}\n"
                f"Max positions: {n_pos}\n"
                f"{datetime.now().strftime('%H:%M ET')}")
        self._send_message(text)

    def send_daily_summary(self, portfolio_value: float, num_positions: int,
                           drawdown: float, trades_today: List[Dict],
                           is_risk_on: bool, leverage: float):
        regime = "RISK_ON" if is_risk_on else "RISK_OFF"
        n_trades = len(trades_today)
        total_pnl = sum(t.get('pnl', 0) for t in trades_today if t.get('action') == 'SELL')
        text = (f"COMPASS DAILY\n"
                f"${portfolio_value:,.0f} | DD: {drawdown:.1%}\n"
                f"{num_positions} pos | {regime} | {leverage:.2f}x\n"
                f"Trades: {n_trades} | P&L: ${total_pnl:+,.0f}\n"
                f"{datetime.now().strftime('%Y-%m-%d')}")
        self._send_message(text)

    def send_recovery_stage_alert(self, stage: int, portfolio_value: float):
        if stage == 0:
            title = "FULL RECOVERY"
        else:
            title = f"RECOVERY Stage {stage}"
        text = (f"{title}\n"
                f"Portfolio: ${portfolio_value:,.0f}\n"
                f"{datetime.now().strftime('%H:%M ET')}")
        self._send_message(text)

    def send_error_alert(self, error_message: str, traceback_str: str = ''):
        text = (f"COMPASS ERROR\n"
                f"{error_message[:200]}\n"
                f"{datetime.now().strftime('%H:%M ET')}")
        self._send_message(text)

    def send_test_message(self):
        """Send a test message to verify configuration"""
        text = (f"COMPASS v8.2 WhatsApp OK\n"
                f"Notifications active\n"
                f"{datetime.now().strftime('%Y-%m-%d %H:%M')}")
        self._send_message(text)
        return True

    def send_rotation_alert(self, cycle_num: int, closed_positions: list,
                            new_positions: list, compass_return: float,
                            spy_return: float, alpha: float):
        """Alert on 5-day rotation with cycle summary"""
        status = "WIN" if alpha >= 0 else "LOSS"
        text = (f"ROTATION #{cycle_num} {status}\n"
                f"COMPASS: {compass_return:+.2f}% | S&P: {spy_return:+.2f}%\n"
                f"Alpha: {alpha:+.2f}pp\n"
                f"OUT: {', '.join(closed_positions)}\n"
                f"IN: {', '.join(new_positions)}\n"
                f"{datetime.now().strftime('%H:%M ET')}")
        self._send_message(text)


class TelegramNotifier:
    """Telegram notification system via Bot API.

    Setup (30 seconds):
      1. Message @BotFather on Telegram, send /newbot, follow prompts
      2. Copy the bot token (e.g. 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11)
      3. Start a chat with your new bot (send /start)
      4. Get your chat_id: visit https://api.telegram.org/bot<TOKEN>/getUpdates
      5. Configure: TelegramNotifier(bot_token='...', chat_id='...')
    """

    def __init__(self, bot_token: str = '', chat_id: str = '', **kwargs):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._enabled = bool(self.bot_token and self.chat_id)

        if self._enabled:
            logger.info(f"TelegramNotifier configured: chat_id={self.chat_id}")
        else:
            logger.warning("TelegramNotifier not configured (missing bot_token or chat_id)")

    def _send_message(self, text: str):
        """Send a Telegram message via Bot API. Never raises."""
        if not self._enabled:
            logger.debug("Telegram skipped (not configured)")
            return

        import urllib.request
        import urllib.parse
        import json as _json

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = _json.dumps({
            'chat_id': self.chat_id,
            'text': text,
            'parse_mode': 'HTML',
        }).encode('utf-8')

        try:
            req = urllib.request.Request(url, data=payload, method='POST',
                                         headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                status = resp.status
            if status == 200:
                logger.info(f"Telegram sent: {text[:60]}...")
            else:
                logger.warning(f"Telegram API returned {status}")
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

    def send_trade_alert(self, action: str, symbol: str, shares: float,
                         price: float, exit_reason: Optional[str] = None,
                         pnl: Optional[float] = None):
        if action == 'BUY':
            text = (f"<b>HYDRA BUY</b>\n"
                    f"{symbol} | {shares:.0f} shares @ ${price:.2f}\n"
                    f"Value: ${shares * price:,.0f}\n"
                    f"{datetime.now().strftime('%H:%M ET')}")
        else:
            pnl_str = f"${pnl:+,.0f}" if pnl is not None else "N/A"
            reason = exit_reason or 'manual'
            text = (f"<b>HYDRA SELL</b> [{reason}]\n"
                    f"{symbol} @ ${price:.2f}\n"
                    f"P&L: {pnl_str}\n"
                    f"{datetime.now().strftime('%H:%M ET')}")
        self._send_message(text)

    def send_portfolio_stop_alert(self, portfolio_value: float,
                                  drawdown: float, peak_value: float):
        text = (f"<b>PORTFOLIO STOP LOSS</b>\n"
                f"DD: {drawdown:.1%} | ${portfolio_value:,.0f}\n"
                f"Peak: ${peak_value:,.0f}\n"
                f"Protection Mode activated\n"
                f"{datetime.now().strftime('%H:%M ET')}")
        self._send_message(text)

    def send_regime_change_alert(self, is_risk_on: bool,
                                 spy_price: float, sma_value: float):
        regime = "RISK_ON" if is_risk_on else "RISK_OFF"
        emoji = "🟢" if is_risk_on else "🟡"
        n_pos = 5 if is_risk_on else 2
        text = (f"{emoji} <b>REGIME → {regime}</b>\n"
                f"SPY: ${spy_price:.2f} | SMA200: ${sma_value:.2f}\n"
                f"Max positions: {n_pos}\n"
                f"{datetime.now().strftime('%H:%M ET')}")
        self._send_message(text)

    def send_daily_summary(self, portfolio_value: float, num_positions: int,
                           drawdown: float, trades_today: List[Dict],
                           is_risk_on: bool, leverage: float):
        regime = "RISK_ON" if is_risk_on else "RISK_OFF"
        n_trades = len(trades_today)
        total_pnl = sum(t.get('pnl', 0) for t in trades_today if t.get('action') == 'SELL')
        text = (f"<b>HYDRA DAILY</b>\n"
                f"${portfolio_value:,.0f} | DD: {drawdown:.1%}\n"
                f"{num_positions} pos | {regime} | {leverage:.2f}x\n"
                f"Trades: {n_trades} | P&L: ${total_pnl:+,.0f}\n"
                f"{datetime.now().strftime('%Y-%m-%d')}")
        self._send_message(text)

    def send_recovery_stage_alert(self, stage: int, portfolio_value: float):
        if stage == 0:
            title = "FULL RECOVERY"
        else:
            title = f"RECOVERY Stage {stage}"
        text = (f"<b>{title}</b>\n"
                f"Portfolio: ${portfolio_value:,.0f}\n"
                f"{datetime.now().strftime('%H:%M ET')}")
        self._send_message(text)

    def send_error_alert(self, error_message: str, traceback_str: str = ''):
        text = (f"<b>HYDRA ERROR</b>\n"
                f"{error_message[:200]}\n"
                f"{datetime.now().strftime('%H:%M ET')}")
        self._send_message(text)

    def send_test_message(self):
        text = (f"<b>HYDRA v8.4 Telegram OK</b>\n"
                f"Notifications active\n"
                f"{datetime.now().strftime('%Y-%m-%d %H:%M')}")
        self._send_message(text)
        return True

    def send_rotation_alert(self, cycle_num: int, closed_positions: list,
                            new_positions: list, compass_return: float,
                            spy_return: float, alpha: float):
        status = "✅ WIN" if alpha >= 0 else "❌ LOSS"
        text = (f"<b>ROTATION #{cycle_num}</b> {status}\n"
                f"COMPASS: {compass_return:+.2f}% | S&P: {spy_return:+.2f}%\n"
                f"Alpha: {alpha:+.2f}pp\n"
                f"OUT: {', '.join(closed_positions)}\n"
                f"IN: {', '.join(new_positions)}\n"
                f"{datetime.now().strftime('%H:%M ET')}")
        self._send_message(text)


class TelegramCommandHandler:
    """Polls Telegram getUpdates for operator commands.

    Supported commands:
      /status    — agent heartbeat + phase info
      /positions — current portfolio positions
      /capital   — capital allocation (COMPASS/Rattlesnake/EFA)
      /stop      — activate kill switch (halt all trading)
      /resume    — deactivate kill switch
    """

    def __init__(self, bot_token, chat_id, engine=None, state_dir='state', agent=None):
        self.bot_token = bot_token
        self.chat_id = str(chat_id)
        self.engine = engine
        self.state_dir = state_dir
        self.agent = agent  # HydraAgent ref for /ask command
        self._last_update_id = 0
        self._notifier = TelegramNotifier(bot_token=bot_token, chat_id=chat_id)

    def poll(self):
        import urllib.request
        import json as _json

        url = (f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
               f"?offset={self._last_update_id + 1}&timeout=1")
        try:
            req = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = _json.loads(resp.read().decode())
        except Exception as e:
            logger.debug(f"Telegram poll error: {e}")
            return

        if not data.get('ok'):
            return

        for update in data.get('result', []):
            self._last_update_id = update['update_id']
            msg = update.get('message', {})
            # Only accept commands from the authorized chat
            if str(msg.get('chat', {}).get('id', '')) != self.chat_id:
                continue
            text = msg.get('text', '').strip()
            if text.startswith('/'):
                self._handle_command(text)

    def _handle_command(self, text):
        cmd = text.split()[0].lower().split('@')[0]  # strip @botname
        handlers = {
            '/status': self._cmd_status,
            '/positions': self._cmd_positions,
            '/capital': self._cmd_capital,
            '/stop': self._cmd_stop,
            '/resume': self._cmd_resume,
            '/help': self._cmd_help,
        }
        if cmd == '/ask':
            question = text[len(text.split()[0]):].strip()
            try:
                self._cmd_ask(question)
            except Exception as e:
                self._notifier._send_message(f"Ask error: {e}")
            return
        handler = handlers.get(cmd, self._cmd_unknown)
        try:
            handler()
        except Exception as e:
            self._notifier._send_message(f"Command error: {e}")

    def _cmd_status(self):
        import json as _json
        hb_path = os.path.join(self.state_dir, 'agent_heartbeat.json')
        if os.path.exists(hb_path):
            with open(hb_path) as f:
                hb = _json.load(f)
            phases = ', '.join(hb.get('phase', [])) or 'none'
            usage = hb.get('token_usage', {})
            total_in = sum(v.get('input_tokens', 0) for v in usage.values())
            total_out = sum(v.get('output_tokens', 0) for v in usage.values())
            msg = (f"<b>HYDRA Status</b>\n"
                   f"Last heartbeat: {hb.get('ts', '?')}\n"
                   f"Phases today: {phases}\n"
                   f"Kill switch: {'ON' if hb.get('kill_switch') else 'OFF'}\n"
                   f"Tokens: {total_in:,} in / {total_out:,} out")
        else:
            msg = "<b>HYDRA Status</b>\nNo heartbeat found — agent may be offline"
        self._notifier._send_message(msg)

    def _cmd_positions(self):
        if not self.engine:
            self._notifier._send_message("Engine not available")
            return
        positions = self.engine.broker.positions
        if not positions:
            self._notifier._send_message("No open positions")
            return
        lines = ["<b>Positions</b>"]
        meta = getattr(self.engine, 'position_meta', {})
        for sym, pos in positions.items():
            shares = getattr(pos, 'shares', 0)
            avg = getattr(pos, 'avg_cost', 0)
            sector = meta.get(sym, {}).get('sector', '?')
            lines.append(f"  {sym}: {shares:.0f} sh @ ${avg:.2f} [{sector}]")
        cash = self.engine.broker.cash
        lines.append(f"\nCash: ${cash:,.2f}")
        self._notifier._send_message('\n'.join(lines))

    def _cmd_capital(self):
        if not self.engine:
            self._notifier._send_message("Engine not available")
            return
        cap = getattr(self.engine, 'capital_manager', None)
        if not cap:
            self._notifier._send_message("Capital manager not initialized")
            return
        status = cap.get_status()
        msg = (f"<b>Capital Allocation</b>\n"
               f"COMPASS: ${status.get('compass_budget', 0):,.0f}\n"
               f"Rattlesnake: ${status.get('rattlesnake_budget', 0):,.0f}\n"
               f"EFA: ${status.get('efa_value', 0):,.0f}\n"
               f"Recycling: {'ON' if status.get('recycling_active') else 'OFF'}")
        self._notifier._send_message(msg)

    def _cmd_stop(self):
        stop_path = os.path.join(self.state_dir, 'STOP_TRADING')
        with open(stop_path, 'w') as f:
            f.write(datetime.now().isoformat())
        self._notifier._send_message("Kill switch ACTIVATED. Trading halted.")

    def _cmd_resume(self):
        stop_path = os.path.join(self.state_dir, 'STOP_TRADING')
        if os.path.exists(stop_path):
            os.remove(stop_path)
            self._notifier._send_message("Kill switch DEACTIVATED. Trading resumed.")
        else:
            self._notifier._send_message("Kill switch was not active.")

    def _cmd_ask(self, question):
        if not question:
            self._notifier._send_message("Usage: /ask &lt;your question&gt;\nExample: /ask why did we skip NVDA today?")
            return
        if not self.agent:
            self._notifier._send_message("Agent not available — /ask requires the HYDRA agent to be running.")
            return

        self._notifier._send_message("Thinking...")

        try:
            response = self.agent._call_claude(
                'OPERATOR_QUERY',
                f"The operator is asking you a question via Telegram. "
                f"Answer concisely (max 3-4 short paragraphs). "
                f"Use plain text, no HTML tags.\n\n"
                f"Question: {question}",
            )
        except Exception as e:
            self._notifier._send_message(f"Claude API error: {e}")
            return

        if not response:
            self._notifier._send_message("No response from Claude.")
            return

        # Telegram limit is 4096 chars — chunk if needed
        MAX_LEN = 4000
        response = response.strip()
        if len(response) <= MAX_LEN:
            self._notifier._send_message(response)
        else:
            chunks = [response[i:i + MAX_LEN] for i in range(0, len(response), MAX_LEN)]
            for chunk in chunks:
                self._notifier._send_message(chunk)

    def _cmd_help(self):
        self._notifier._send_message(
            "<b>HYDRA Commands</b>\n"
            "/status — agent heartbeat\n"
            "/positions — open positions\n"
            "/capital — capital allocation\n"
            "/ask &lt;question&gt; — ask HYDRA anything\n"
            "/stop — halt all trading\n"
            "/resume — resume trading\n"
            "/help — this message"
        )

    def _cmd_unknown(self):
        self._notifier._send_message("Unknown command. Send /help for available commands.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Notification module loaded successfully.")
    print("Available: EmailNotifier, WhatsAppNotifier, TelegramNotifier, TelegramCommandHandler")
