from unittest.mock import patch
import logging

from compass.notifications import EmailNotifier, WhatsAppNotifier, TelegramNotifier


def test_email_notifier_logs_error_when_smtp_connection_fails(caplog):
    notifier = EmailNotifier(
        sender='bot@test.com',
        password='secret',
        recipients=['ops@test.com'],
    )

    with patch('compass.notifications.smtplib.SMTP', side_effect=OSError('smtp down')):
        with caplog.at_level(logging.ERROR):
            notifier._send_email('subject', '<p>body</p>')

    assert 'Failed to send email: smtp down' in caplog.text


def test_email_trade_alert_formats_symbol_shares_and_price():
    notifier = EmailNotifier(
        sender='bot@test.com',
        password='secret',
        recipients=['ops@test.com'],
    )
    captured = {}

    def fake_send(subject, body, priority='normal'):
        captured['subject'] = subject
        captured['body'] = body
        captured['priority'] = priority

    notifier._send_email = fake_send

    notifier.send_trade_alert('BUY', 'AAPL', 10, 150.0)

    assert captured['subject'] == 'COMPASS: BUY AAPL @ $150.00'
    assert 'New Position: AAPL' in captured['body']
    assert '<td>10.00</td>' in captured['body']
    assert '$150.00' in captured['body']
    assert '$1,500' in captured['body']
    assert captured['priority'] == 'normal'


def test_email_portfolio_stop_alert_includes_portfolio_value_and_drawdown():
    notifier = EmailNotifier(
        sender='bot@test.com',
        password='secret',
        recipients=['ops@test.com'],
    )
    captured = {}

    def fake_send(subject, body, priority='normal'):
        captured['subject'] = subject
        captured['body'] = body
        captured['priority'] = priority

    notifier._send_email = fake_send

    notifier.send_portfolio_stop_alert(88_000.0, -0.12, 100_000.0)

    assert captured['subject'] == 'COMPASS STOP LOSS: DD -12.0% | $88,000'
    assert 'PORTFOLIO STOP LOSS TRIGGERED' in captured['body']
    assert '$88,000' in captured['body']
    assert '$100,000' in captured['body']
    assert '-12.0%' in captured['body']
    assert captured['priority'] == 'high'


def test_email_regime_change_alert_mentions_direction_and_spy_context():
    notifier = EmailNotifier(
        sender='bot@test.com',
        password='secret',
        recipients=['ops@test.com'],
    )
    captured = {}

    def fake_send(subject, body, priority='normal'):
        captured['subject'] = subject
        captured['body'] = body
        captured['priority'] = priority

    notifier._send_email = fake_send

    notifier.send_regime_change_alert(False, 500.0, 505.0)

    assert captured['subject'] == 'COMPASS: Regime -> RISK_OFF'
    assert 'Regime Change: RISK_OFF' in captured['body']
    assert '$500.00' in captured['body']
    assert '$505.00' in captured['body']
    assert 'Max Positions:</b></td><td>2' in captured['body']
    assert captured['priority'] == 'normal'


def test_whatsapp_notifier_logs_error_when_request_fails(caplog):
    notifier = WhatsAppNotifier(phone='+573001234567', apikey='abc123')

    with patch('urllib.request.urlopen', side_effect=OSError('network down')):
        with caplog.at_level(logging.ERROR):
            notifier._send_message('hello world')

    assert 'WhatsApp send failed: network down' in caplog.text


def test_telegram_notifier_logs_error_when_request_fails(caplog):
    notifier = TelegramNotifier(bot_token='bad-token', chat_id='12345')

    with patch('urllib.request.urlopen', side_effect=ValueError('invalid bot token')):
        with caplog.at_level(logging.ERROR):
            notifier._send_message('hello world')

    assert 'Telegram send failed: invalid bot token' in caplog.text


def test_disabled_notifiers_do_not_make_network_calls():
    email = EmailNotifier()
    whatsapp = WhatsAppNotifier()
    telegram = TelegramNotifier()

    with patch('compass.notifications.smtplib.SMTP') as mock_smtp:
        with patch('urllib.request.urlopen') as mock_urlopen:
            email.send_trade_alert('BUY', 'AAPL', 10, 150.0)
            whatsapp.send_trade_alert('BUY', 'AAPL', 10, 150.0)
            telegram.send_trade_alert('BUY', 'AAPL', 10, 150.0)

    mock_smtp.assert_not_called()
    mock_urlopen.assert_not_called()
