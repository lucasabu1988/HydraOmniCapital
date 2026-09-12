"""TASK-433: the cache check refuses, and it refuses for the RIGHT reason.

Nine independent substitutions, one per way a cached book can fail to be the book asked for:

    (i)    different costs                     [costs]
    (ii)   a window shifted, same length       [calendar]
    (iii)  a window truncated                  [calendar]
    (iv)   different input bytes               [data:<name>]
    (v)    content altered after the fact      [result] / [self_sha256]
    (vi)   a book moved into another's slot    [artifact]          <- silent until 2026-09-12
    (vii)  a request that asks for other inputs[data:<name>]       <- silent until 2026-09-12
    (viii) a window nobody declared            [calendar]          <- silent until 2026-09-12
    (ix)   an identity block declared empty    [costs] / [data] ...<- silent until 2026-09-12

Each asserts on the reason string, not on the fact that something was raised: a test that passes
because a different check fired would certify a validator that cannot tell one cause from
another, which is the whole property being bought here. Every case therefore also asserts
`msg.count("CACHE REJECTED [") == 1`, so a rejection names one cause and not a list.

(vi)-(ix) were each ACCEPTED by the shipped validator and were measured against the real
manifests in `_lab_scratch/accredited/` before they were fixed; the numbers those measurements
produced (wealth 3.439693 where Russell is 2.431955, a 604-mark base accredited as the anchor)
are quoted in the tests that now refuse them, so the tests say what they are worth.

What is NOT bought here, said once: `self_sha256` is an unkeyed digest of the manifest computed
by the public `seal()`, so it detects an accidental edit and drift and nothing else. Re-pricing a
manifest 35/10 -> 20/8, moving `config.v9_effective` to agree and re-running `seal()` was
accepted when it was measured, and no test below claims otherwise.

No engine, no network, no real cache: the books are `np.cumprod(1+r)` on a business-day grid and
the "panel" is a few-KB pickle in tmp_path. The 264 MB caches are never opened, and nothing here
writes outside tmp_path.

Auto-discovered by run_all_tests.py (pytest-routed: no __main__ block)."""
from __future__ import annotations

import json
import os
import shutil
import sys

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.dirname(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import provenance as PV  # noqa: E402


def _book(n: int = 300, seed: int = 433, first: str = "2010-06-28") -> pd.Series:
    rng = np.random.default_rng(seed)
    r = 0.0016 + 0.01 * rng.standard_normal(n)
    idx = pd.bdate_range(first, periods=n * 5)[::5]
    return pd.Series(np.cumprod(1 + r), index=idx)


def _panel_file(tmp_path, payload=1.0) -> str:
    """A few-KB stand-in for `price_close`. The real one is 264 MB and must not be touched."""
    p = tmp_path / "close.pkl"
    pd.to_pickle(pd.DataFrame({"AAA": [payload] * 8, "BBB": [2.0] * 8},
                              index=pd.bdate_range("2010-06-28", periods=8)), p)
    return str(p)


def _request(tmp_path, *, stock_bp=35.0, etf_bp=10.0, label="stress", calendar=None,
             panel_path=None, data=None) -> dict:
    """A COMPLETE request: every block `provenance.IDENTITY_BLOCKS` names, with its required keys.

    Complete on purpose. An incomplete request is now a refusal, so a helper that quietly left a
    block out would make every test below pass for the wrong reason - the identity tests assert
    that exact refusal and have to build the incompleteness themselves, in the open.
    """
    req = dict(
        code=PV.code_identity(),
        config=dict(v9_effective_sha256="cfg-a", lab_config_sha256="lab-a",
                    algo_version="v9", step_bars=5),
        costs=dict(stock_bp_per_side=float(stock_bp), etf_bp_per_side=float(etf_bp),
                   scenario_label=label),
        data=data if data is not None else PV.data_identity(
            dict(price_close=panel_path or _panel_file(tmp_path), membership=None)),
        sectors=dict(requested_mode="fixed"),
        units=dict(irx=dict(on_disk="annual_percent", consumed="annual_decimal", divisor=100.0)),
        period=dict(declared="research+validation", holdout_sha256="holdout-a"),
        protocol=dict(board_task="TASK-433", verdict_rule_sha256="rule-a"),
    )
    if calendar is not None:
        req["calendar"] = dict(calendar)
    else:
        req[PV.ANCHOR_DECLARATION] = "fixture book: it defines its own grid"
    return req


def _accredited(tmp_path, name="russell_stress.pkl", book=None, **kw):
    """A book with a manifest that verifies - the starting point of every substitution below."""
    book = _book() if book is None else book
    path = str(tmp_path / name)
    pd.to_pickle(book, path)
    req = _request(tmp_path, **kw)
    PV.write_manifest(book, path, req)
    return path, book, req


def _repoison(path, manifest):
    """Re-seal an edited manifest, so the substitution is not caught by `self_sha256` instead."""
    with open(PV.manifest_path(path), "w", encoding="utf-8") as fh:
        json.dump(PV.seal(manifest), fh, indent=2, default=str)


def _one_rejection(msg: str) -> None:
    assert msg.count("CACHE REJECTED [") == 1, f"more than one cause named:\n{msg}"


# --------------------------------------------------------------------- the accredited path

def test_accredit_round_trip(tmp_path):
    """The control: without it every test below could pass on a validator that rejects always."""
    path, book, req = _accredited(tmp_path)
    got, man = PV.accredit(path, req)
    assert list(got.index) == list(book.index) and float(got.iloc[-1]) == float(book.iloc[-1])
    acc = man["_accreditation"]
    for field in ("self_sha256", "result", "artifact", "code", "costs", "config", "data",
                  "sectors", "units", "period", "protocol"):
        assert field in acc["compared"], f"{field} was not compared"
    # the fields nothing asked about are NAMED, with the reason, not silently skipped
    assert "universe" in acc["uncompared"] and "universe" in acc["uncompared_why"]
    assert "price_close" in acc["uncompared_why"]["universe"]
    assert "calendar" in acc["uncompared"]
    assert "defines" in acc["uncompared_why"]["calendar"].lower()


def test_a_book_with_no_manifest_is_unaccredited_not_rejected(tmp_path):
    """'We never recorded this' is a different statement from 'this is the wrong book'.

    All eight books already on disk are in the first case; the tag has to distinguish them or the
    classification of the existing artifacts collapses into the rejection path.
    """
    path = str(tmp_path / "engine_book_russell.pkl")
    pd.to_pickle(_book(), path)
    with pytest.raises(PV.CacheRejected) as e:
        PV.accredit(path, _request(tmp_path))
    msg = str(e.value)
    assert e.value.tag == PV.UNACCREDITED and e.value.field == "manifest"
    assert "CACHE UNACCREDITED [manifest]" in msg
    assert "engine_book_russell.pkl.manifest.json" in msg
    assert "never consumed as a cache hit" in msg and "the old file is preserved" in msg
    assert "CACHE REJECTED" not in msg          # a missing record is not a mismatch
    assert os.path.exists(path)                  # nothing was deleted or repaired


# ------------------------------------------------------------ (i) DIFFERENT COSTS

def test_rejects_a_book_priced_at_different_costs(tmp_path):
    """The field the whole task exists for: 35/10 asked for as 20/8.

    Nothing else differs. The pair is recorded per sleeve and never as the 14.0 bp blend
    `run_russell_prereg` computes, which 20/8 and 15/13 would share.
    """
    path, _book_, _ = _accredited(tmp_path, stock_bp=35.0, etf_bp=10.0, label="stress")
    req = _request(tmp_path, stock_bp=20.0, etf_bp=8.0, label="conservative",
                   panel_path=_panel_file(tmp_path))
    with pytest.raises(PV.CacheRejected) as e:
        PV.accredit(path, req)
    msg = str(e.value)
    assert e.value.field == "costs" and "CACHE REJECTED [costs]" in msg
    assert "stored stock_bp=35.0 etf_bp=10.0" in msg
    assert "requested stock_bp=20.0 etf_bp=8.0" in msg
    assert "priced at costs other than the ones asked for" in msg
    assert "this file is not deleted" in msg
    _one_rejection(msg)


def test_a_cost_difference_of_one_basis_point_is_still_a_rejection(tmp_path):
    """Exact numeric equality, no tolerance: both sides come from a table of round numbers, so a
    tolerance could only ever admit a typo."""
    path, _b, _ = _accredited(tmp_path, stock_bp=35.0, etf_bp=10.0)
    with pytest.raises(PV.CacheRejected) as e:
        PV.accredit(path, _request(tmp_path, stock_bp=35.0, etf_bp=11.0))
    assert e.value.field == "costs"


# ------------------------------------------------------------ (ii) SHIFTED DATES

def test_rejects_a_window_shifted_forward_with_the_same_number_of_marks(tmp_path):
    """The attack that was accepted SILENTLY last cycle.

    A poisoned base moved the evaluated window to 2014-2026 and still received a clean holdout
    stamp. Book and manifest are poisoned together and re-sealed, so this lands on the
    calendar-vs-REQUEST comparison and not on the result-integrity one - which is the comparison
    `os.path.exists` cannot make at all.
    """
    path, book, _ = _accredited(tmp_path, name="russell_base.pkl")
    shifted = pd.Series(book.values, index=pd.bdate_range("2014-01-02", periods=len(book) * 5)[::5])
    pd.to_pickle(shifted, path)
    man = PV.read_manifest(path)
    man["calendar"] = PV.calendar_block(shifted)
    man["result"] = PV.result_block(shifted)
    _repoison(path, man)

    want = PV.calendar_block(book)               # the original 2010-06-28 grid
    with pytest.raises(PV.CacheRejected) as e:
        PV.accredit(path, _request(tmp_path, calendar=want))
    msg = str(e.value)
    assert e.value.field == "calendar" and "CACHE REJECTED [calendar]" in msg
    assert "Same length, different dates" in msg
    assert f"stored window {str(shifted.index[0].date())}..{str(shifted.index[-1].date())}" in msg
    assert f"requested {want['first']}..{want['last']}" in msg
    assert f"(n={len(book)}" in msg               # same length on both sides: that IS the point
    _one_rejection(msg)


# ------------------------------------------------------------ (iii) TRUNCATED WINDOW

def test_rejects_a_truncated_book_and_names_the_partition_it_stops_in(tmp_path):
    """Short is a different diagnosis from shifted, and the partition is what makes it matter.

    A truncated book is not merely short: it silently converts a research+validation experiment
    into a research-only one, which is the failure mode TASK-432's holdout was built to mark.
    """
    path, book, _ = _accredited(tmp_path, name="russell_base.pkl")
    cut = book.iloc[:120]
    pd.to_pickle(cut, path)
    man = PV.read_manifest(path)
    man["calendar"] = PV.calendar_block(cut)
    man["result"] = PV.result_block(cut)
    _repoison(path, man)

    want = PV.calendar_block(book)
    with pytest.raises(PV.CacheRejected) as e:
        PV.accredit(path, _request(tmp_path, calendar=want))
    msg = str(e.value)
    assert e.value.field == "calendar" and "CACHE REJECTED [calendar]" in msg
    assert f"stored n={len(cut)} marks" in msg and f"requested n={len(book)} marks" in msg
    assert f"is {len(book) - len(cut)} marks short" in msg
    assert "stops inside 'research'" in msg       # from holdout.partition_of, not from a literal
    assert "Same length, different dates" not in msg   # the two calendar failures stay distinct
    _one_rejection(msg)


# ------------------------------------------------------------ (iv) DIFFERENT DATA

def test_rejects_when_an_input_file_changed_under_the_book(tmp_path):
    """Stored manifest against the CURRENT bytes on disk - the comparison existence cannot make.

    The manifest is left untouched here: what moves is the world. The real caches have not been
    rewritten since 10:28 on 2026-09-11, but nothing on disk proves that and nothing would have
    noticed if they had.
    """
    panel = _panel_file(tmp_path, payload=1.0)
    path, _b, req = _accredited(tmp_path, name="russell_conservative.pkl", panel_path=panel)
    before = PV.read_manifest(path)["data"]["price_close"]["sha256"]

    pd.to_pickle(pd.DataFrame({"AAA": [9.0] * 8, "BBB": [2.0] * 8},
                              index=pd.bdate_range("2010-06-28", periods=8)), panel)
    PV._DIGEST_MEMO.clear()                       # the memo is (size, mtime_ns)-keyed, not a cache of truth

    with pytest.raises(PV.CacheRejected) as e:
        PV.accredit(path, req)
    msg = str(e.value)
    assert e.value.field == "data:price_close", "the logical name must be inside the tag"
    assert "CACHE REJECTED [data:price_close]" in msg
    assert f"stored sha256 {before[:12]}" in msg
    assert f"current sha256 {PV.sha256_bytes(panel)[:12]}" in msg
    assert "The panel changed under the book." in msg
    _one_rejection(msg)


def test_a_membership_swap_reads_as_membership_and_not_as_data(tmp_path):
    """Two inputs moving are two diagnoses; a bare `[data]` tag would make them one."""
    mem = tmp_path / "membership.pkl"
    pd.to_pickle(pd.DataFrame({"AAA": [True] * 4}, index=pd.bdate_range("2010-06-28", periods=4)), mem)
    book = _book()
    path = str(tmp_path / "russell_stress.pkl")
    pd.to_pickle(book, path)
    req = dict(_request(tmp_path), data=PV.data_identity(dict(
        price_close=_panel_file(tmp_path), membership=str(mem))))
    PV.write_manifest(book, path, req)

    pd.to_pickle(pd.DataFrame({"AAA": [False] * 4}, index=pd.bdate_range("2010-06-28", periods=4)), mem)
    PV._DIGEST_MEMO.clear()
    with pytest.raises(PV.CacheRejected) as e:
        PV.accredit(path, req)
    assert e.value.field == "data:membership"
    _one_rejection(str(e.value))


# ------------------------------------------------------------ (v) ALTERED CONTENT

def test_rejects_a_book_edited_after_its_manifest_was_written(tmp_path):
    """The field with no analogue today, and the reason a manifest is a seal and not a label.

    Same index, same length, same dtype, same everything the other twelve comparisons look at -
    only the values moved. The load-bearing assertion is that NO other tag fires: if any of them
    did, they would be masking a silent content edit rather than catching it.
    """
    path, book, req = _accredited(tmp_path, name="sp500_stress.pkl")
    stored = PV.read_manifest(path)["result"]
    edited = book * 1.01
    pd.to_pickle(edited, path)

    with pytest.raises(PV.CacheRejected) as e:
        PV.accredit(path, req)
    msg = str(e.value)
    assert e.value.field == "result" and "CACHE REJECTED [result]" in msg
    assert f"manifest records result sha256 {stored['sha256'][:12]}" in msg
    assert f"the file on disk hashes to {PV.book_sha256(edited)[:12]}" in msg
    assert f"({len(book)} marks, wealth {stored['wealth']})" in msg
    assert "modified after its manifest was written" in msg
    _one_rejection(msg)
    for other in ("[costs]", "[calendar]", "[data:", "[code]", "[units]", "[self_sha256]"):
        assert other not in msg, f"{other} masked the content edit"


def test_editing_the_manifest_to_match_a_poisoned_book_fails_at_the_seal(tmp_path):
    """The other half of (v): the two defences close on each other.

    Editing the book fails at `result`; editing the manifest to agree with it fails here; doing
    both requires reproducing a canonical digest only the writer produces.
    """
    path, book, req = _accredited(tmp_path)
    man = PV.read_manifest(path)
    man["costs"]["stock_bp_per_side"] = 20.0      # edited, NOT re-sealed
    with open(PV.manifest_path(path), "w", encoding="utf-8") as fh:
        json.dump(man, fh, indent=2, default=str)
    with pytest.raises(PV.CacheRejected) as e:
        PV.accredit(path, req)
    msg = str(e.value)
    assert e.value.field == "self_sha256" and "does not verify" in msg
    assert "edited after it was written" in msg
    _one_rejection(msg)


# ------------------------------------------------------------ the rest of the surface

def test_rejects_a_different_unit_contract_and_names_the_key(tmp_path):
    """Nothing in a float64 series distinguishes 0.0151 from 1.51; the declaration is the check."""
    path, _b, req = _accredited(tmp_path)
    bad = dict(req)
    bad["units"] = dict(irx=dict(on_disk="annual_decimal", consumed="annual_decimal", divisor=1.0))
    with pytest.raises(PV.CacheRejected) as e:
        PV.accredit(path, bad)
    msg = str(e.value)
    assert e.value.field == "units" and "annual_percent" in msg and "annual_decimal" in msg
    assert "different unit contract" in msg
    _one_rejection(msg)


def test_rejects_a_book_produced_by_different_code_and_names_the_modules(tmp_path):
    path, _b, req = _accredited(tmp_path)
    man = PV.read_manifest(path)
    man["code"]["modules"]["experiments/metrics.py"] = "0" * 64
    man["code"]["modules_combined"] = PV.sha256_json(man["code"]["modules"])
    _repoison(path, man)
    with pytest.raises(PV.CacheRejected) as e:
        PV.accredit(path, req)
    msg = str(e.value)
    assert e.value.field == "code" and "experiments/metrics.py" in msg
    assert "produced by different code" in msg
    _one_rejection(msg)


def test_a_pandas_patch_bump_is_degraded_and_a_major_bump_is_refused(tmp_path):
    """The one tolerance in the table, and it is a tolerance on a RECORD, not on a decision.

    Refusing on a patch bump would invalidate every book on a routine upgrade; a major bump is
    refused because pandas majors have moved dtype and groupby semantics under this code before.
    """
    path, _b, req = _accredited(tmp_path)
    man = PV.read_manifest(path)
    real = man["code"]["deps"]["pandas"]
    major, rest = real.split(".", 1)
    man["code"]["deps"]["pandas"] = f"{major}.{rest.split('.')[0]}.999"
    _repoison(path, man)
    _book_out, got = PV.accredit(path, req)
    assert got["_accreditation"]["degraded"], "a patch drift must be recorded, not swallowed"
    assert "CACHE DEGRADED [code.deps]" in got["_accreditation"]["degraded"][0]

    man["code"]["deps"]["pandas"] = f"{int(major) + 1}.0.0"
    _repoison(path, man)
    with pytest.raises(PV.CacheRejected) as e:
        PV.accredit(path, req)
    assert e.value.field == "code.deps" and "major version change" in str(e.value)


def test_config_and_period_and_protocol_each_name_their_own_field(tmp_path):
    """One substitution per block, so no block is riding on another's check."""
    path, _b, req = _accredited(tmp_path)
    for block, key, value in (("config", "v9_effective_sha256", "cfg-b"),
                              ("period", "declared", "research"),
                              ("protocol", "board_task", "TASK-999")):
        bad = {k: (dict(v) if isinstance(v, dict) else v) for k, v in req.items()}
        bad[block][key] = value
        with pytest.raises(PV.CacheRejected) as e:
            PV.accredit(path, bad)
        assert e.value.field == f"{block}.{key}", f"{block} was caught by {e.value.field}"
        _one_rejection(str(e.value))


def test_explain_all_prints_every_mismatch_and_still_refuses(tmp_path, capsys):
    path, _b, req = _accredited(tmp_path)
    bad = {k: (dict(v) if isinstance(v, dict) else v) for k, v in req.items()}
    bad["costs"]["stock_bp_per_side"] = 20.0
    bad["units"] = dict(irx="annual_decimal")
    with pytest.raises(PV.CacheRejected):
        PV.accredit(path, bad, explain_all=True)
    printed = capsys.readouterr().out
    assert "[costs]" in printed and "[units]" in printed


# ------------------------------------------------------------ the books that came before

def test_classify_historical_describes_without_inventing(tmp_path):
    """No fabricated retrospective metadata, and a filename no validator can mistake for a seal."""
    path = str(tmp_path / "engine_book_russell.pkl")
    book = _book()
    pd.to_pickle(book, path)
    rec = PV.classify_historical(path, evidence=[dict(kind="artifact", path="x.json",
                                                      supports="config", does_not_support="the book")])
    assert rec["cls"] == PV.HISTORICAL
    assert os.path.exists(PV.provenance_path(path))
    assert not os.path.exists(PV.manifest_path(path)), "a classification is not an accreditation"
    assert PV.classify(path) == PV.HISTORICAL
    # everything under `observed` is recomputed now, from the artifact
    assert rec["observed"]["n"] == len(book)
    assert rec["observed"]["sha256"] == PV.book_sha256(book)
    assert rec["observed"]["calendar_sha256"] == PV.calendar_sha256(book.index)
    # and the limits are stated, not implied
    assert "CORROBORATION" in rec["corroboration"] and "NOT proof of provenance" in rec["corroboration"]
    assert "result.sha256" in rec["absent"] and "code.modules" in rec["absent"]
    assert "no proof to be had" in rec["corroboration"]
    # a sidecar does NOT make the book consumable
    with pytest.raises(PV.CacheRejected) as e:
        PV.accredit(path, _request(tmp_path))
    assert e.value.tag == PV.UNACCREDITED


def test_a_sidecar_next_to_a_real_manifest_never_upgrades_it(tmp_path):
    path, _b, req = _accredited(tmp_path)
    PV.classify_historical(path)
    assert PV.classify(path) == PV.ACCREDITED         # the manifest still decides
    PV.accredit(path, req)                            # and the sidecar changes nothing


# ------------------------------------------------------------ the primitives

def test_code_identity_records_what_was_imported_not_only_what_was_listed():
    """The enumerated list is a claim; the sweep is a measurement. Both, and kept apart."""
    code = PV.code_identity(enumerated=("experiments/provenance.py",))
    assert "experiments/provenance.py" in code["modules"]
    # provenance imports holdout, so the sweep must find it even though the list did not
    assert "experiments/holdout.py" in code["unenumerated"]
    assert code["swept"]["experiments/holdout.py"] == PV.sha256_lf(
        os.path.join(PV.ROOT, "experiments", "holdout.py"))
    # the combined digest covers the LIST only, so it does not move with an unrelated import
    assert code["modules_combined"] == PV.sha256_json(code["modules"])
    assert "experiments/holdout.py" not in code["modules"]


def test_a_swept_module_both_runs_loaded_is_still_compared(tmp_path):
    """Recorded is not the same as ignored: a shared unlisted module that moved is a rejection."""
    path, _b, req = _accredited(tmp_path)
    man = PV.read_manifest(path)
    loaded = sorted(man["code"]["swept"])
    assert loaded, "nothing unlisted was loaded; the sweep has nothing to prove"
    man["code"]["swept"][loaded[0]] = "0" * 64
    _repoison(path, man)
    with pytest.raises(PV.CacheRejected) as e:
        PV.accredit(path, req)
    assert e.value.field == "code.swept" and loaded[0] in str(e.value)
    _one_rejection(str(e.value))


def test_source_digests_ignore_line_endings_and_content_digests_do_not(tmp_path):
    lf, crlf = tmp_path / "a.py", tmp_path / "b.py"
    lf.write_bytes(b"x = 1\ny = 2\n")
    crlf.write_bytes(b"x = 1\r\ny = 2\r\n")
    assert PV.sha256_lf(str(lf)) == PV.sha256_lf(str(crlf))
    assert PV.sha256_bytes(str(lf)) != PV.sha256_bytes(str(crlf))


def test_book_hash_moves_on_a_value_change_and_on_an_index_change():
    b = _book(n=50)
    assert PV.book_sha256(b) == PV.book_sha256(b.copy())
    assert PV.book_sha256(b) != PV.book_sha256(b * 1.0000001)
    shifted = pd.Series(b.values, index=b.index + pd.Timedelta(days=1))
    assert PV.book_sha256(b) != PV.book_sha256(shifted)


def test_a_null_input_is_recorded_and_not_omitted(tmp_path):
    """An absent key would let a panel swap look like a shorter manifest, not a different one."""
    rec = PV.data_identity(dict(price_close=_panel_file(tmp_path), membership=None))
    assert set(rec) == {"price_close", "membership"} and rec["membership"] is None


# ============================================================ THE FOUR SILENT ACCEPTANCES
# Each of the four below was ACCEPTED by the shipped validator on 2026-09-12, measured against
# the real manifests in `_lab_scratch/accredited/`. The numbers those measurements produced are
# quoted in the test that now refuses the case, so each test says what it is worth.


# ------------------------------------------------------------ (vi) A BOOK IN ANOTHER'S SLOT

def test_a_book_moved_into_another_books_slot_is_refused_by_name(tmp_path):
    """The critical one. `artifact` was in `NEVER_COMPARED`, and it is the field a swap MOVES.

    Measured on the real books: `sp500_base.pkl` and its manifest copied into the `russell_base`
    slot, asked the Russell question, returned the S&P book - wealth 3.439693 where Russell is
    2.431955 - for all four cost pairs in both directions. Every published TASK-433 delta is
    Russell-minus-S&P, so the rename inverted the entire economic content of the table.
    """
    panel = _panel_file(tmp_path)
    sp, sp_book, req = _accredited(tmp_path, name="sp500_base.pkl", panel_path=panel,
                                   book=_book(seed=1))
    rus = str(tmp_path / "russell_base.pkl")
    shutil.copyfile(sp, rus)
    shutil.copyfile(PV.manifest_path(sp), PV.manifest_path(rus))

    with pytest.raises(PV.CacheRejected) as e:
        PV.accredit(rus, req)
    msg = str(e.value)
    assert e.value.field == "artifact" and "CACHE REJECTED [artifact]" in msg
    assert "the manifest was written for sp500_base.pkl" in msg
    assert "it is being consumed from russell_base.pkl" in msg
    assert "moved into another book's slot is not that book" in msg
    assert "This file is not deleted." in msg
    _one_rejection(msg)
    assert os.path.exists(sp) and os.path.exists(rus)      # nothing deleted or repaired


def test_the_same_name_in_another_directory_is_degraded_and_not_refused(tmp_path):
    """Only the BASENAME is identity: it is the slot. A directory is not.

    A relocation - a restored backup, a fixture tree, a copy under review - moves no number, and
    refusing it would make the check a nuisance that gets turned off rather than a defence. It is
    recorded instead, so the accreditation still says the book was read somewhere else.
    """
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    path, book, req = _accredited(a, name="russell_stress.pkl")
    moved = str(b / "russell_stress.pkl")
    shutil.copyfile(path, moved)
    shutil.copyfile(PV.manifest_path(path), PV.manifest_path(moved))

    got, man = PV.accredit(moved, req, echo=False)
    assert float(got.iloc[-1]) == float(book.iloc[-1])
    acc = man["_accreditation"]
    assert "artifact" in acc["compared"]
    assert any("CACHE DEGRADED [artifact]" in d and "relocation moves no number" in d
               for d in acc["degraded"]), acc["degraded"]


# ------------------------------------------------------------ (vii) THE REQUEST'S OWN `data`

def test_a_panel_swap_is_refused_on_the_input_bytes_even_when_the_file_name_agrees(tmp_path):
    """The substantive half of the swap refusal, and what makes `data - a different panel` true.

    `_check_data` used to re-hash only the files the STORED manifest named: it answered "have
    these inputs moved since" and never "are these the inputs I asked for", so the request's own
    `data` block was never read by any check. `accredit_433.data_answers` was one caller's local
    guard around its own produce() path; `grep -c data_answers cost_stress.py` was 0, and
    cost_stress is the path that PUBLISHES the table.

    Here the file name agrees exactly, so `artifact` cannot fire and the refusal has to come from
    the bytes.
    """
    sp_dir, rus_dir = tmp_path / "sp", tmp_path / "rus"
    sp_dir.mkdir()
    rus_dir.mkdir()
    sp_panel = _panel_file(sp_dir, payload=3.0)
    rus_panel = _panel_file(rus_dir, payload=7.0)
    book = _book()
    path = str(tmp_path / "russell_base.pkl")
    pd.to_pickle(book, path)
    PV.write_manifest(book, path, _request(tmp_path, panel_path=sp_panel))

    with pytest.raises(PV.CacheRejected) as e:
        PV.accredit(path, _request(tmp_path, panel_path=rus_panel))
    msg = str(e.value)
    assert e.value.field == "data:price_close", "the logical name must be inside the tag"
    assert "CACHE REJECTED [data:price_close]" in msg
    assert "the manifest was written over" in msg and PV.sha256_bytes(sp_panel)[:12] in msg
    assert "the request asks for" in msg and PV.sha256_bytes(rus_panel)[:12] in msg
    assert "a file name is not a panel" in msg
    # and it is NOT the drift check wearing the same tag: both files are exactly as written
    assert "The panel changed under the book." not in msg
    _one_rejection(msg)


def test_an_input_the_request_leaves_out_is_a_mismatch_and_not_a_shorter_manifest(tmp_path):
    """The union, not the intersection. `membership` is the input the two panels differ on.

    The real manifests make this concrete: the Russell block names `membership` and `coverage`
    and leaves `sp500_pit_payload` null; the S&P block does the reverse. Comparing only the names
    both sides happen to carry would let exactly that pair of swaps through.
    """
    mem = tmp_path / "membership.pkl"
    pd.to_pickle(pd.DataFrame({"AAA": [True] * 4},
                              index=pd.bdate_range("2010-06-28", periods=4)), mem)
    panel = _panel_file(tmp_path)
    book = _book()
    path = str(tmp_path / "russell_base.pkl")
    pd.to_pickle(book, path)
    PV.write_manifest(book, path, _request(tmp_path, data=PV.data_identity(
        dict(price_close=panel, membership=str(mem)))))

    asked = _request(tmp_path, data=PV.data_identity(dict(price_close=panel)))
    with pytest.raises(PV.CacheRejected) as e:
        PV.accredit(path, asked)
    msg = str(e.value)
    assert e.value.field == "data:membership"
    assert "the request asks for no such input (null)" in msg
    assert PV.sha256_bytes(str(mem))[:12] in msg
    _one_rejection(msg)


# ------------------------------------------------------------ (viii) AN UNDECLARED WINDOW

def test_a_request_that_declares_neither_a_grid_nor_an_anchor_is_refused(tmp_path):
    """`ALWAYS_CHECKED` did not name `calendar`, and `accredit` skipped any field absent from the
    request, so the caller that said nothing about the window got no window check at all."""
    path, _b, req = _accredited(tmp_path, name="russell_base.pkl")
    bare = {k: v for k, v in req.items() if k != PV.ANCHOR_DECLARATION}
    assert "calendar" not in bare, "the fixture must not be declaring a grid"

    with pytest.raises(PV.CacheRejected) as e:
        PV.accredit(path, bare)
    msg = str(e.value)
    assert e.value.field == "calendar" and "CACHE REJECTED [calendar]" in msg
    assert "declares neither a mark grid nor 'calendar_anchor'" in msg
    assert "2014-2026 is not the book that answers for 2010-2026" in msg
    _one_rejection(msg)


def test_the_604_mark_anchor_is_refused_undeclared_and_never_reads_as_compared(tmp_path):
    """Verbatim the attack this module's docstring opens by claiming to fix.

    `cost_stress.run()` passes `calendar=None` for the FIRST book of a run, so a 604-mark
    2014..2026 base with a valid manifest was accredited, became the anchor, set `start_date` for
    the S&P drive, and the run published `fully_accredited=True` with a clean holdout stamp over
    the poisoned window.

    Three statements, all load-bearing. Undeclared is REFUSED. Declared-as-anchor is accepted but
    recorded as UNCOMPARED with a `CACHE DEGRADED [calendar]` line - never as compared, because
    nothing compared it, and this module does not claim to constrain a window nothing anchors.
    An anchored request that DOES carry a grid refuses it on the marks.
    """
    full = _book(n=814, first="2010-06-28")
    poisoned = full.iloc[-604:]
    path = str(tmp_path / "russell_base.pkl")
    pd.to_pickle(poisoned, path)
    PV.write_manifest(poisoned, path, _request(tmp_path))

    bare = {k: v for k, v in _request(tmp_path).items() if k != PV.ANCHOR_DECLARATION}
    with pytest.raises(PV.CacheRejected) as e:
        PV.accredit(path, bare)
    assert e.value.field == "calendar"
    _one_rejection(str(e.value))

    got, man = PV.accredit(path, _request(tmp_path), echo=False)
    assert len(got) == 604
    acc = man["_accreditation"]
    assert "calendar" not in acc["compared"], "an uncompared window must never read as compared"
    assert "calendar" in acc["uncompared"]
    assert "defines" in acc["uncompared_why"]["calendar"].lower()
    assert any("CACHE DEGRADED [calendar]" in d and "DEFINES the mark grid" in d
               for d in acc["degraded"]), acc["degraded"]

    with pytest.raises(PV.CacheRejected) as e2:
        PV.accredit(path, _request(tmp_path, calendar=PV.calendar_block(full)))
    msg2 = str(e2.value)
    assert e2.value.field == "calendar" and "210 marks short" in msg2
    _one_rejection(msg2)


# ------------------------------------------------------------ (ix) AN EMPTY IDENTITY BLOCK

@pytest.mark.parametrize("block", list(PV.IDENTITY_BLOCKS))
def test_an_identity_block_left_empty_is_refused_and_never_listed_as_compared(block, tmp_path):
    """`req['costs'] = {}` returned [] AND `_accreditation.compared` still listed `costs`.

    A record that overstates what was checked is worse than no record: it is the sentence a
    reviewer quotes. Every identity block is covered, not just the one that was measured.
    """
    path, _b, req = _accredited(tmp_path)
    bad = dict(req)
    bad[block] = {}
    if block == "calendar":
        bad.pop(PV.ANCHOR_DECLARATION)

    with pytest.raises(PV.CacheRejected) as e:
        PV.accredit(path, bad)
    msg = str(e.value)
    assert e.value.field == block, f"{block} was caught as {e.value.field}"
    assert f"CACHE REJECTED [{block}]" in msg
    if block == "calendar":
        assert "declares neither a mark grid nor 'calendar_anchor'" in msg
    else:
        assert f"the request declares no {block!r} block ({{}})" in msg
        assert "identity field" in msg and "never silently uncompared" in msg
    _one_rejection(msg)


def test_an_identity_block_missing_a_required_key_is_refused_by_that_key(tmp_path):
    """Half a declaration is not a declaration: the etf leg alone would let 20/8 read as 20/15."""
    path, _b, req = _accredited(tmp_path)
    bad = dict(req, costs=dict(stock_bp_per_side=35.0, scenario_label="stress"))
    with pytest.raises(PV.CacheRejected) as e:
        PV.accredit(path, bad)
    msg = str(e.value)
    assert e.value.field == "costs.etf_bp_per_side"
    assert "does not declare 'etf_bp_per_side'" in msg
    assert "cannot be left to the manifest to assert about itself" in msg
    _one_rejection(msg)


def test_the_record_of_what_was_checked_is_true_and_not_flattering(tmp_path):
    """compared / uncompared / uncompared_why / uncompared_keys, each asserted against the truth.

    The derived fields are the point: `universe` and most of `sectors` cannot be produced by a
    cache reader without loading the 264 MB panel the cache exists to avoid, so they are RECORDED
    and named rather than compared - which is only defensible because `data:price_close`, the
    field their identity comes from, IS compared now.
    """
    book = _book()
    path = str(tmp_path / "russell_base.pkl")
    pd.to_pickle(book, path)
    req = _request(tmp_path)
    fuller = dict(req)
    fuller["config"] = dict(req["config"], start_bar=41)
    fuller["sectors"] = dict(requested_mode="fixed", mode="fixed_map", snapshot_date="20260905")
    fuller["universe"] = dict(n_columns=6048, columns_sha256="cols-a")
    PV.write_manifest(book, path, fuller)

    _got, man = PV.accredit(path, req, echo=False)
    acc = man["_accreditation"]
    assert "config" in acc["compared"] and "sectors" in acc["compared"]
    assert "config.start_bar" in acc["uncompared_keys"]
    assert "sectors.mode" in acc["uncompared_keys"]
    assert "sectors.snapshot_date" in acc["uncompared_keys"]
    assert not any(k.startswith("result.") for k in acc["uncompared_keys"]), \
        "a block compared against the BOOK has no request keys to be missing"
    assert "universe" in acc["uncompared"]
    assert "price_close" in acc["uncompared_why"]["universe"], \
        "a derived field must name the compared field that carries its identity"
    assert PV.DERIVED_BLOCKS["universe"] == acc["uncompared_why"]["universe"]


# ============================================================ THE DOCSTRING'S OWN CLAIMS

def test_a_cost_mismatch_surfaces_as_costs_and_not_as_the_config_hash(tmp_path):
    """The message the module docstring quotes, made reachable from a real caller.

    The bp pair is baked into `config.v9_effective_sha256`, so a genuine cost change moves BOTH
    blocks. With `config` asked first, every real cost mismatch read
    `[config.v9_effective_sha256] ... driven under a different configuration` - true, and the
    less precise of two names for one fact, while the quoted `[costs]` line was reachable only
    from a hand-edited manifest. `costs` is asked first now, so the docstring is honest.
    """
    path, _b, _ = _accredited(tmp_path, name="russell_stress.pkl", stock_bp=35.0, etf_bp=10.0)
    req = _request(tmp_path, stock_bp=20.0, etf_bp=8.0, label="conservative")
    req["config"] = dict(req["config"], v9_effective_sha256="cfg-b")   # as a real caller's does

    with pytest.raises(PV.CacheRejected) as e:
        PV.accredit(path, req)
    msg = str(e.value)
    assert e.value.field == "costs", f"a cost change surfaced as {e.value.field}"
    assert ("russell_stress.pkl: stored stock_bp=35.0 etf_bp=10.0; requested stock_bp=20.0 "
            "etf_bp=8.0. The cached book was priced at costs other than the ones asked for.") in msg
    assert msg.split(": ", 1)[0].endswith("russell_stress.pkl")
    _one_rejection(msg)
    order = [f for f, _ in PV.CHECKS]
    assert order.index("costs") < order.index("config"), "the quoted message must stay reachable"


def test_a_deliberate_re_sealer_is_not_stopped_and_nothing_here_claims_it_is(tmp_path):
    """The limit, measured rather than hoped: `seal()` is an UNKEYED digest from a public function.

    Re-pricing the manifest 35/10 -> 20/8, moving `config.v9_effective_sha256` to agree and
    re-running `PV.seal()` is ACCEPTED, and the 35/10 book answers the 20/8 question. Closing it
    needs a secret this module does not have, so the docstring states the real threat model -
    accidental edits and drift, not an adversary - and this test keeps that statement a fact in
    the suite instead of a paragraph nobody re-reads.
    """
    path, book, _ = _accredited(tmp_path, name="russell_conservative.pkl",
                                stock_bp=35.0, etf_bp=10.0)
    man = PV.read_manifest(path)
    man["costs"]["stock_bp_per_side"], man["costs"]["etf_bp_per_side"] = 20.0, 8.0
    man["config"]["v9_effective_sha256"] = "cfg-b"
    _repoison(path, man)                                   # the PUBLIC seal(), re-run

    req = _request(tmp_path, stock_bp=20.0, etf_bp=8.0, label="conservative")
    req["config"] = dict(req["config"], v9_effective_sha256="cfg-b")
    got, _m = PV.accredit(path, req, echo=False)
    assert float(got.iloc[-1]) == float(book.iloc[-1]), \
        "measured: the 35/10 book answered the 20/8 question"
    assert "NOT tamper-evidence against a deliberate adversary" in PV.__doc__
    assert "editing it to match a poisoned book fails as well" not in PV.__doc__


def test_the_module_docstring_does_not_overstate_what_the_code_does():
    """Three claims the adversarial verifier found false or unreachable on 2026-09-12."""
    doc = PV.__doc__
    # the artifact field is no longer both distinguishing and never compared
    assert "artifact" not in PV.NEVER_COMPARED
    assert "artifact" in PV.ALWAYS_CHECKED
    # `data - a different panel` is a claim about the REQUEST's block, which is now read
    assert "data" in PV.IDENTITY_BLOCKS
    assert "are these the inputs I ASKED FOR" in PV._check_data.__doc__
    # and the identity/derived split is written down rather than implied
    assert set(PV.DERIVED_BLOCKS) == {"universe"}
    assert "AN UNDECLARED IDENTITY FIELD IS A REFUSAL, NOT A SKIP" in doc
    assert "DERIVED IS NOT THE SAME AS IGNORED" in doc


def test_a_manifest_with_no_result_digest_is_refused_not_treated_as_agreement(tmp_path):
    """`_check_result` used to `return []` when the manifest carried no result sha256.

    It is the ONLY check that looks at the bytes actually loaded, so a manifest without a digest
    certifies nothing about the book beside it - yet the absence read as agreement and `result`
    was still listed in `_accreditation.compared`. Reachable without re-sealing anything: `schema`
    is never compared, so a manifest under another schema whose `result` block is shaped
    differently arrived here with no sha256 at all.
    """
    import pandas as pd
    book = pd.Series([1.0, 1.1], index=pd.to_datetime(["2010-06-28", "2010-07-06"]))
    path = tmp_path / "b.pkl"
    pd.to_pickle(book, path)
    for empty in ({}, {"n": 2}, {"sha256": ""}, {"sha256": None}):
        man = {"schema": "hydra.lab.manifest/0", "artifact": "b.pkl", "result": empty}
        out = PV._check_result(man, {"_artifact_result": {"sha256": "deadbeef", "n": 2}}, "b.pkl")
        assert out, f"a manifest whose result block is {empty!r} must be refused"
        tag, field, body = out[0]
        assert field == "result" and "no result sha256" in body
