"""
OmniCapital v8.2 COMPASS - Email Notifications Module
======================================================
Sends email alerts for trades, stop losses, regime changes,
daily summaries, and system errors.
"""

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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("EmailNotifier module loaded successfully.")
    print("To test, create instance with SMTP credentials and call send_test_email().")
