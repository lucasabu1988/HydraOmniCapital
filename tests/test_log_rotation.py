"""Tests for log rotation with RotatingFileHandler."""

import logging
import os
import tempfile

from logging.handlers import RotatingFileHandler


def test_rotating_file_handler_creates_backup():
    """Write > maxBytes to a tiny RotatingFileHandler and verify rotation."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = os.path.join(tmp, 'test.log')

        handler = RotatingFileHandler(
            log_path, maxBytes=1000, backupCount=5
        )
        handler.setFormatter(logging.Formatter('%(message)s'))

        test_logger = logging.getLogger('test_rotation')
        test_logger.setLevel(logging.INFO)
        test_logger.addHandler(handler)

        # Write ~5000 bytes (each line ~100 chars)
        for i in range(50):
            test_logger.info('x' * 95 + str(i).zfill(4))

        handler.close()
        test_logger.removeHandler(handler)

        # Verify main log exists
        assert os.path.exists(log_path), "Main log file should exist"

        # Verify at least one backup was created
        backup_path = log_path + '.1'
        assert os.path.exists(backup_path), (
            f"Backup file {backup_path} should exist after rotation"
        )

        # Main log should be <= maxBytes (1000)
        assert os.path.getsize(log_path) <= 1000, (
            "Main log should not exceed maxBytes after rotation"
        )


def test_omnicapital_live_uses_rotating_handler():
    """Verify omnicapital_live.py imports RotatingFileHandler."""
    import importlib.util
    spec = importlib.util.find_spec('logging.handlers')
    assert spec is not None

    # Check the source file for RotatingFileHandler usage
    src_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), 'omnicapital_live.py'
    )
    with open(src_path, 'r', encoding='utf-8') as f:
        content = f.read()

    assert 'RotatingFileHandler' in content, (
        "omnicapital_live.py should use RotatingFileHandler"
    )
    assert 'maxBytes' in content, (
        "omnicapital_live.py should configure maxBytes for rotation"
    )
    assert 'backupCount' in content, (
        "omnicapital_live.py should configure backupCount for rotation"
    )
