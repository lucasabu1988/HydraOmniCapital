import pytest
from hydra_prompts import build_system_prompt, PHASES


def test_phases_defined():
    assert 'PRE_MARKET_BRIEFING' in PHASES
    assert 'INTRADAY_MONITOR' in PHASES
    assert 'PRE_CLOSE_DECISION' in PHASES
    assert 'POST_CLOSE_SUMMARY' in PHASES


def test_build_prompt_contains_soul():
    prompt = build_system_prompt(
        phase='PRE_MARKET_BRIEFING',
        portfolio_state={'cash': 50000, 'positions': {}, 'regime_score': 0.7},
        scratchpad_summary='No entries today.',
    )
    assert 'HYDRA Agent' in prompt
    assert 'LOCKED' in prompt


def test_build_prompt_contains_phase():
    prompt = build_system_prompt(
        phase='PRE_CLOSE_DECISION',
        portfolio_state={'cash': 50000, 'positions': {}, 'regime_score': 0.7},
        scratchpad_summary='1 briefing.',
    )
    assert 'PRE_CLOSE_DECISION' in prompt


def test_build_prompt_contains_decision_rules():
    prompt = build_system_prompt(
        phase='PRE_CLOSE_DECISION',
        portfolio_state={'cash': 50000, 'positions': {}, 'regime_score': 0.7},
        scratchpad_summary='',
    )
    assert 'NEVER modify momentum' in prompt
    assert 'Stops are non-negotiable' in prompt


def test_build_prompt_pre_market_instructions():
    prompt = build_system_prompt(
        phase='PRE_MARKET_BRIEFING',
        portfolio_state={'cash': 50000, 'positions': {'AAPL': {}}, 'regime_score': 0.7},
        scratchpad_summary='',
    )
    assert 'validate_data_feeds' in prompt.lower() or 'data feed' in prompt.lower()


def test_build_prompt_pre_close_instructions():
    prompt = build_system_prompt(
        phase='PRE_CLOSE_DECISION',
        portfolio_state={'cash': 50000, 'positions': {}, 'regime_score': 0.7},
        scratchpad_summary='',
    )
    assert 'momentum' in prompt.lower()
    assert '15:30' in prompt or '15:50' in prompt
