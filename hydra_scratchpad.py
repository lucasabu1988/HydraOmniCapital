"""Append-only JSONL decision logger for the HYDRA autonomous agent.

One file per day: state_dir/agent_scratchpad/YYYY-MM-DD.jsonl
Entry types: briefing, tool_call, decision, trade, stop_event, alert, summary
"""

import os
import json
import logging
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS_PER_PHASE = 3


class HydraScratchpad:

    def __init__(self, state_dir='state'):
        self.state_dir = state_dir
        self._sp_dir = os.path.join(state_dir, 'agent_scratchpad')
        os.makedirs(self._sp_dir, exist_ok=True)
        self._tool_counts = defaultdict(lambda: defaultdict(int))

    def _today_path(self):
        today = datetime.now().strftime('%Y-%m-%d')
        return os.path.join(self._sp_dir, f'{today}.jsonl')

    def log(self, entry_type, data):
        entry = {
            'type': entry_type,
            'ts': datetime.now().isoformat(),
            'data': data,
        }
        path = self._today_path()
        with open(path, 'a') as f:
            f.write(json.dumps(entry, default=str) + '\n')
        logger.debug(f"Scratchpad: {entry_type} logged")

    def read_today(self):
        path = self._today_path()
        if not os.path.exists(path):
            return []
        entries = []
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries

    def check_tool_limit(self, tool_name, phase):
        self._tool_counts[tool_name][phase] += 1
        count = self._tool_counts[tool_name][phase]
        if count > MAX_TOOL_CALLS_PER_PHASE:
            logger.warning(f"Tool limit exceeded: {tool_name} called {count}x in {phase}")
            return False
        return True

    def has_trade_today(self, symbol, action):
        for entry in self.read_today():
            if entry['type'] == 'trade':
                d = entry.get('data', {})
                if d.get('symbol') == symbol and d.get('action') == action:
                    return True
        return False

    def count_round_trips_today(self):
        buys = set()
        sells = set()
        for entry in self.read_today():
            if entry['type'] == 'trade':
                d = entry.get('data', {})
                sym = d.get('symbol')
                if d.get('action') == 'BUY':
                    buys.add(sym)
                elif d.get('action') == 'SELL':
                    sells.add(sym)
        return len(buys & sells)

    def cleanup(self, max_age_days=90):
        cutoff = datetime.now() - timedelta(days=max_age_days)
        removed = 0
        for fname in os.listdir(self._sp_dir):
            if not fname.endswith('.jsonl'):
                continue
            try:
                date_str = fname.replace('.jsonl', '')
                file_date = datetime.strptime(date_str, '%Y-%m-%d')
                if file_date < cutoff:
                    os.remove(os.path.join(self._sp_dir, fname))
                    removed += 1
            except ValueError:
                continue
        if removed:
            logger.info(f"Scratchpad cleanup: removed {removed} files older than {max_age_days}d")

    def summarize_phase(self, phase_hint=''):
        entries = self.read_today()
        if not entries:
            return "No entries today."
        type_counts = defaultdict(int)
        highlights = []
        for e in entries:
            type_counts[e['type']] += 1
            if e['type'] in ('alert', 'stop_event', 'trade'):
                data = e.get('data', {})
                sym = data.get('symbol', '')
                msg = data.get('message', data.get('action', ''))
                highlights.append(f"  - [{e['type']}] {sym} {msg}")
        summary_parts = [f"Entries: {sum(type_counts.values())} ({', '.join(f'{v} {k}' for k, v in type_counts.items())})"]
        if highlights:
            summary_parts.append("Highlights:\n" + "\n".join(highlights[:10]))
        return "\n".join(summary_parts)
