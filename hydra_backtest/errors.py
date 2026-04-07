"""Exception hierarchy for hydra_backtest package.

All errors raised by this package should inherit from HydraBacktestError.
Fail-loud philosophy: no try/except: pass anywhere. Offline analysis has
no reason to swallow errors.
"""


class HydraBacktestError(Exception):
    """Base class for all errors raised by the hydra_backtest package."""


class HydraDataError(HydraBacktestError):
    """Raised when input data is missing, corrupt, or inconsistent."""


class HydraBacktestValidationError(HydraBacktestError):
    """Raised when a smoke test or invariant check fails."""


class HydraBacktestLookaheadError(HydraBacktestValidationError):
    """Raised when lookahead is detected in a decision trace."""
