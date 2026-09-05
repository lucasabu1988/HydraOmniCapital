"""
HYDRA Regime Detector (May 2026)

Lightweight market regime detection used to make the capital allocation
system (HydraCapitalManager) behave differently depending on market conditions.

This is part of the May 2026 improvements to make HYDRA more adaptive
during strong US equity bull markets (where the system previously lagged).

Regimes:
    - "neutral"              : Balanced / default behavior
    - "strong_us_momentum"   : Strong equity bull market (SPY above SMA200 + strong recent returns)
    - "risk_off"             : Weak / stressed equity market

Used by:
    - HydraCapitalManager (for dynamic recycling and EFA/Catalyst gates)
    - omnicapital_live.py (updated daily in update_regime())
"""

from typing import Literal

Regime = Literal["neutral", "strong_us_momentum", "risk_off"]


def detect_regime(
    spy_vs_sma200: bool,
    recent_spy_return_20d: float,
    vix: float = 20.0
) -> Regime:
    """
    Very lightweight regime detection.

    This is intentionally simple and conservative.
    More sophisticated versions can be built later using
    the ML layer or additional overlays.
    """
    # Strong US momentum regime (SPY ripping above SMA200 with good momentum)
    if spy_vs_sma200 and recent_spy_return_20d > 0.06:
        return "strong_us_momentum"

    # Risk-off regime
    if not spy_vs_sma200 or vix > 30:
        return "risk_off"

    return "neutral"


def get_regime_description(regime: Regime) -> str:
    descriptions = {
        "neutral": "Balanced conditions — default recycling behavior",
        "strong_us_momentum": "Strong equity bull market — favor COMPASS, reduce new Catalyst/EFA",
        "risk_off": "Defensive / weak equity market — preserve capital for Rattlesnake opportunities",
    }
    return descriptions.get(regime, "Unknown regime")