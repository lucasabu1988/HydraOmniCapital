import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import omnicapital_live as live


def test_current_universe_symbols_have_sector_mapping():
    state_path = Path(__file__).resolve().parents[1] / 'state' / 'compass_state_latest.json'
    state = json.loads(state_path.read_text(encoding='utf-8'))
    universe = state.get('current_universe', [])

    missing = [symbol for symbol in universe if symbol not in live.SECTOR_MAP]

    assert missing == []
