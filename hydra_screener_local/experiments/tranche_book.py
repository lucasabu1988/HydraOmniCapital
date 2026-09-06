"""Shim: the executable tranche book moved to core/tranche_book.py (production must not import from
experiments/). Lab code and the review tests keep importing `tranche_book` from here."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.tranche_book import *  # noqa: F401,F403
from core.tranche_book import Trade, Tranche, TrancheBook, run_book  # noqa: F401
