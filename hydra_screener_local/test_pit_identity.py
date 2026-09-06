"""Audit phase 6 — immutable, content-addressed PIT inputs and baseline binding.

Reproductions R-601..R-606 in docs/AUDIT_REPRODUCTIONS.md. Synthetic files, no network.
"""
import json
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import data.pit as PIT  # noqa: E402
from core.baseline import (  # noqa: E402
    KEY_SUFFIX,
    baseline_key,
    check_baseline,
    code_hash,
    frame_hash,
    read_baseline_key,
    sha256_json,
    write_baseline_key,
)
from utils import runlog  # noqa: E402


# ------------------------------------------------------------------ R-601 / 6.10
def test_r601_same_date_different_content_have_different_identities(tmp_path):
    """R-601 — phase 6.2/6.10, the requirement stated outright in the brief.

    Pre-fix the dated file was rewritten in place: writing a different universe for
    2026-01-05 replaced the earlier one and left no trace at all.
    """
    PIT.write_universe_snapshot("sp500", ["AAA", "BBB"], "20260105", "sourceA", pit_dir=tmp_path)
    id_a = PIT.snapshot_identity("universe", "20260105", name="sp500", pit_dir=tmp_path)

    PIT.write_universe_snapshot("sp500", ["CCC", "DDD"], "20260105", "sourceB", pit_dir=tmp_path)
    id_b = PIT.snapshot_identity("universe", "20260105", name="sp500", pit_dir=tmp_path)

    assert id_a["sha256"] != id_b["sha256"], "different content, different identity"
    assert id_a["revision"] == 1 and id_b["revision"] == 2
    assert id_a["verified"] and id_b["verified"]

    revs = PIT.revisions("universe", "20260105", name="sp500", pit_dir=tmp_path)
    assert len(revs) == 2
    assert [r["revision"] for r in revs] == [1, 2]
    assert revs[0]["sha256"] != revs[1]["sha256"]


def test_r601_the_earlier_revision_is_still_byte_identical_on_disk(tmp_path):
    """Phase 6.1: a snapshot is immutable. Revision 1 must survive revision 2."""
    PIT.write_universe_snapshot("sp500", ["AAA", "BBB"], "20260105", "sourceA", pit_dir=tmp_path)
    rev1 = PIT.revisions("universe", "20260105", name="sp500", pit_dir=tmp_path)[0]
    path1 = tmp_path / os.path.basename(rev1["path"])
    before = path1.read_bytes()

    PIT.write_universe_snapshot("sp500", ["CCC", "DDD"], "20260105", "sourceB", pit_dir=tmp_path)
    assert path1.read_bytes() == before
    assert json.loads(before)["tickers"] == ["AAA", "BBB"]


def test_the_object_store_is_write_once(tmp_path):
    PIT.write_universe_snapshot("sp500", ["AAA", "BBB"], "20260105", "s", pit_dir=tmp_path)
    ident = PIT.snapshot_identity("universe", "20260105", name="sp500", pit_dir=tmp_path)
    obj = tmp_path / "objects" / f"{ident['sha256']}.json"
    assert obj.exists()
    before = obj.read_bytes()
    # the same content again is a no-op, not a rewrite
    PIT.write_universe_snapshot("sp500", ["BBB", "AAA"], "20260105", "s", pit_dir=tmp_path)
    assert obj.read_bytes() == before
    assert len(PIT.revisions("universe", "20260105", name="sp500", pit_dir=tmp_path)) == 1


def test_writing_the_same_content_twice_is_idempotent(tmp_path):
    a = PIT.write_universe_snapshot("sp500", ["AAA"], "20260105", "s", pit_dir=tmp_path)
    b = PIT.write_universe_snapshot("sp500", ["AAA"], "20260105", "s", pit_dir=tmp_path)
    assert a == b
    assert len(PIT.revisions("universe", "20260105", name="sp500", pit_dir=tmp_path)) == 1


def test_the_versioned_path_carries_name_date_revision_and_hash(tmp_path):
    """Phase 6.3."""
    PIT.write_universe_snapshot("sp500", ["AAA"], "20260105", "s", pit_dir=tmp_path)
    PIT.write_universe_snapshot("sp500", ["BBB"], "20260105", "s", pit_dir=tmp_path)
    names = sorted(p.name for p in tmp_path.glob("universe_sp500_20260105_r*.json"))
    assert len(names) == 2
    assert names[0].startswith("universe_sp500_20260105_r01_")
    assert names[1].startswith("universe_sp500_20260105_r02_")
    for n in names:
        digest = n.rsplit("_", 1)[-1].removesuffix(".json")
        assert len(digest) == 12 and all(c in "0123456789abcdef" for c in digest)


# ------------------------------------------------------------------ R-602 / R-603
def test_r602_the_payload_records_a_content_hash(tmp_path):
    """R-602 — phase 6.4: no hash of any kind was recorded."""
    p = PIT.write_universe_snapshot("sp500", ["AAA", "BBB"], "20260105", "src", pit_dir=tmp_path)
    payload = json.loads(p.read_text(encoding="utf-8"))
    assert payload["sha256"]
    assert payload["schema"] == PIT.SCHEMA
    assert payload["source"] == "src"
    assert payload["rows"] == 2
    assert payload["revision"] == 1


def test_r602_the_raw_payload_hash_is_recorded_separately(tmp_path):
    """Phase 6.4: raw *and* normalized."""
    raw = {"rows": [{"Symbol": "aaa "}, {"Symbol": "BBB"}]}
    PIT.write_universe_snapshot("sp500", ["AAA", "BBB"], "20260105", "src",
                                pit_dir=tmp_path, raw=raw)
    ident = PIT.snapshot_identity("universe", "20260105", name="sp500", pit_dir=tmp_path)
    assert ident["raw_sha256"] == PIT.sha256_of(raw)
    assert ident["raw_sha256"] != ident["sha256"]


def test_r603_the_identity_is_available_next_to_the_payload(tmp_path):
    """R-603 — phase 6.4/6.5: readers could not say which snapshot they had."""
    PIT.write_universe_snapshot("sp500", ["AAA"], "20260105", "src", pit_dir=tmp_path)
    ident = PIT.snapshot_identity("universe", "20260105", name="sp500", pit_dir=tmp_path)
    for key in ("sha256", "recorded_sha256", "verified", "revision", "source",
                "fetched_at", "rows", "schema", "path", "present"):
        assert key in ident
    assert ident["verified"] is True


def test_a_tampered_snapshot_fails_verification(tmp_path):
    PIT.write_universe_snapshot("sp500", ["AAA", "BBB"], "20260105", "src", pit_dir=tmp_path)
    pointer = tmp_path / "universe_sp500_20260105.json"
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    payload["tickers"] = ["AAA", "BBB", "SNEAKY"]
    pointer.write_text(json.dumps(payload), encoding="utf-8")
    ident = PIT.snapshot_identity("universe", "20260105", name="sp500", pit_dir=tmp_path)
    assert ident["verified"] is False
    assert ident["sha256"] != ident["recorded_sha256"]


def test_a_legacy_snapshot_is_readable_and_honestly_unverified(tmp_path):
    """Rule 4: the snapshots already on Lucas's disk must keep working, and must not
    be reported as content-addressed when they are not."""
    legacy = {"source": "wikipedia", "fetched_at": "2026-09-05T10:00:00",
              "count": 2, "tickers": ["AAA", "BBB"]}
    (tmp_path / "universe_sp500_20260905.json").write_text(json.dumps(legacy), encoding="utf-8")
    assert PIT.membership("sp500", "20260906", pit_dir=tmp_path) == {"AAA", "BBB"}
    ident = PIT.snapshot_identity("universe", "20260905", name="sp500", pit_dir=tmp_path)
    assert ident["present"] is True
    assert ident["recorded_sha256"] is None
    assert ident["verified"] is False
    assert ident["sha256"], "a hash is still computable on read"


def test_a_legacy_text_pointer_still_resolves(tmp_path):
    (tmp_path / "universe_sp500_20260105.json").write_text(
        json.dumps({"tickers": ["AAA"], "count": 1}), encoding="utf-8")
    (tmp_path / "universe_sp500_20260112.json").write_text("same_as_20260105\n", encoding="utf-8")
    assert PIT.membership("sp500", "20260112", pit_dir=tmp_path) == {"AAA"}


# ------------------------------------------------------------------ R-604
def test_r604_audit_mode_fails_closed_on_a_missing_universe(tmp_path):
    """R-604 — phase 6.6: a missing PIT input returned empty and the run continued."""
    assert PIT.membership("sp500", "20260105", pit_dir=tmp_path) == set()
    with pytest.raises(PIT.PitMissing) as exc:
        PIT.require_membership("sp500", "20260105", pit_dir=tmp_path)
    assert "audit mode" in str(exc.value)


def test_r604_audit_mode_fails_closed_on_a_missing_sector_map(tmp_path):
    assert PIT.sectors_at("20260105", pit_dir=tmp_path) == ({}, None)
    with pytest.raises(PIT.PitMissing):
        PIT.require_sectors_at("20260105", pit_dir=tmp_path)


def test_require_returns_the_identity_when_the_snapshot_is_there(tmp_path):
    PIT.write_universe_snapshot("sp500", ["AAA"], "20260105", "src", pit_dir=tmp_path)
    names, date, ident = PIT.require_membership("sp500", "20260110", pit_dir=tmp_path)
    assert names == {"AAA"} and date == "20260105"
    assert ident["verified"] is True


def test_require_refuses_an_empty_snapshot(tmp_path):
    PIT.write_universe_snapshot("sp500", [], "20260105", "src", pit_dir=tmp_path)
    with pytest.raises(PIT.PitMissing):
        PIT.require_membership("sp500", "20260105", pit_dir=tmp_path)


def test_the_inputs_manifest_names_the_fallbacks(tmp_path):
    """Phase 6.5/6.6: a fallback must be explicit in the run record."""
    PIT.write_universe_snapshot("sp500", ["AAA"], "20260105", "src", pit_dir=tmp_path)
    man = PIT.inputs_manifest(universes=["sp500", "russell2000"], date="20260110",
                              pit_dir=tmp_path)
    assert man["universes"]["sp500"]["present"] is True
    assert man["universes"]["russell2000"]["present"] is False
    assert set(man["fallback_used"]) == {"sectors", "russell2000"}
    assert man["schema"] == PIT.SCHEMA


# ------------------------------------------------------------------ R-605 sector cache
@pytest.mark.parametrize("bad", [None, float("nan"), "", "  ", "None", "nan", "null",
                                 "N/A", "unknown", "-", 3.14, True])
def test_r605_a_corrupt_sector_value_is_never_serialised_as_a_sector(bad, tmp_path):
    """R-605 — phase 6.7. `str(None)` is `"None"`, which reads back as a GICS sector."""
    clean, dropped = PIT.clean_sector_map({"AAA": "Technology", "BAD": bad})
    assert clean == {"AAA": "Technology"}
    assert dropped == ["BAD"]

    PIT.write_sectors_snapshot({"AAA": "Technology", "BAD": bad}, "20260105", pit_dir=tmp_path)
    payload = json.loads((tmp_path / "sectors_20260105.json").read_text(encoding="utf-8"))
    assert payload["sectors"] == {"AAA": "Technology"}
    assert "BAD" in payload["unknown"]
    assert "BAD" in payload["dropped"]

    sec, _ = PIT.sectors_at("20260105", pit_dir=tmp_path)
    assert sec == {"AAA": "Technology"}


def test_a_valid_sector_survives_cleaning():
    clean, dropped = PIT.clean_sector_map({
        "AAA": "Technology", "BBB": "Financial Services", "CCC": "  Energy  "})
    assert clean == {"AAA": "Technology", "BBB": "Financial Services", "CCC": "Energy"}
    assert dropped == []


# ------------------------------------------------------------------ R-606 baseline
def _panel():
    idx = pd.bdate_range("2024-01-02", periods=40)
    return pd.DataFrame({"A": range(40), "B": range(40, 80)}, index=idx).astype(float)


def test_r606_an_unkeyed_baseline_is_not_valid(tmp_path):
    """R-606 — phase 6.8/6.9: nothing tied audit_steps.pkl to its inputs, so a stale
    baseline could outlive the panel, the sector map, the config and the code."""
    art = tmp_path / "audit_steps.pkl"
    art.write_bytes(b"pretend pickle")
    out = check_baseline(art, panel_sha="p", sector_sha="s", config_sha="c", code_sha="k")
    assert out["valid"] is False
    assert KEY_SUFFIX in out["reason"]


def test_a_keyed_baseline_is_valid_for_the_same_inputs(tmp_path):
    art = tmp_path / "audit_steps.pkl"
    art.write_bytes(b"pretend pickle")
    write_baseline_key(art, panel_sha="p", sector_sha="s", config_sha="c", code_sha="k")
    out = check_baseline(art, panel_sha="p", sector_sha="s", config_sha="c", code_sha="k")
    assert out["valid"] is True
    assert read_baseline_key(art)["key"] == baseline_key(
        panel_sha="p", sector_sha="s", config_sha="c", code_sha="k")


@pytest.mark.parametrize("field", ["panel_sha", "sector_sha", "config_sha", "code_sha"])
def test_changing_any_input_invalidates_the_baseline(field, tmp_path):
    """Phase 6.9: any one of the four is enough."""
    art = tmp_path / "audit_steps.pkl"
    art.write_bytes(b"x")
    base = {"panel_sha": "p", "sector_sha": "s", "config_sha": "c", "code_sha": "k"}
    write_baseline_key(art, **base)
    changed = dict(base, **{field: "different"})
    out = check_baseline(art, **changed)
    assert out["valid"] is False
    assert out["changed"] == [{"panel_sha": "panel", "sector_sha": "sector_map",
                               "config_sha": "config", "code_sha": "code"}[field]]
    assert "regenerate" in out["reason"]


def test_a_missing_baseline_artefact_is_not_valid(tmp_path):
    out = check_baseline(tmp_path / "nope.pkl", panel_sha="p")
    assert out["valid"] is False
    assert "missing" in out["reason"]


def test_frame_hash_is_content_sensitive_and_stable():
    a, b = _panel(), _panel()
    assert frame_hash(a) == frame_hash(b)
    c = _panel()
    c.iloc[10, 0] += 1e-9
    assert frame_hash(c) != frame_hash(a)
    assert frame_hash(None) is None


def test_code_hash_notices_a_changed_file(tmp_path):
    (tmp_path / "config.py").write_text("A = 1\n", encoding="utf-8")
    first = code_hash(tmp_path, files=("config.py",))
    (tmp_path / "config.py").write_text("A = 2\n", encoding="utf-8")
    second = code_hash(tmp_path, files=("config.py",))
    assert first["combined"] != second["combined"]


def test_code_hash_notices_a_deleted_file(tmp_path):
    (tmp_path / "config.py").write_text("A = 1\n", encoding="utf-8")
    with_file = code_hash(tmp_path, files=("config.py",))
    (tmp_path / "config.py").unlink()
    without = code_hash(tmp_path, files=("config.py",))
    assert without["files"]["config.py"] is None
    assert with_file["combined"] != without["combined"]


# ------------------------------------------------------------------ run manifest
def test_the_run_manifest_carries_every_required_hash(tmp_path):
    """Phase 6.5 end to end."""
    PIT.write_universe_snapshot("sp500", ["AAA", "BBB"], "20260105", "wikipedia",
                                pit_dir=tmp_path / "pit")
    PIT.write_sectors_snapshot({"AAA": "Technology"}, "20260105", pit_dir=tmp_path / "pit")

    ctx = runlog.start_run("audit-test", argv=["x"], runs_dir=tmp_path / "runs")
    rec = ctx.inputs(
        universes=["sp500"], date="20260110", pit_dir=tmp_path / "pit",
        panel=_panel(), sector_map={"AAA": "Technology", "BAD": None},
        universe_tickers=["AAA", "BBB"],
        providers={"stocks": {"source": "yfinance", "fetched_at": "2026-01-10T00:00:00Z",
                              "requested": 2, "downloaded": 2, "failed_tickers": []}},
    )
    ctx.finish(0)
    ctx.close_log()

    man = runlog.load_manifest(ctx.directory)
    assert man["inputs"]["universe"]["sha256"] == sha256_json(["AAA", "BBB"])
    assert man["inputs"]["panel"]["sha256"]
    assert man["inputs"]["sector_map"]["sha256"]
    assert man["inputs"]["sector_map"]["dropped"] == 1
    assert man["inputs"]["pit"]["universes"]["sp500"]["verified"] is True
    assert man["inputs"]["pit"]["sectors"]["verified"] is True
    assert man["inputs"]["pit"]["fallback_used"] == []
    assert man["inputs"]["providers"]["stocks"]["source"] == "yfinance"
    assert man["versions"]["pandas"]
    assert man["versions"]["python_full"]
    assert man["timezone"]["local"]
    assert rec["pit"]["schema"] == PIT.SCHEMA


def test_the_run_manifest_records_a_stale_baseline(tmp_path):
    art = tmp_path / "audit_steps.pkl"
    art.write_bytes(b"x")
    write_baseline_key(art, panel_sha="p", sector_sha="s", config_sha="c", code_sha="k")
    ctx = runlog.start_run("audit-test", argv=["x"], runs_dir=tmp_path / "runs")
    out = ctx.baseline(art, panel_sha="CHANGED", sector_sha="s", config_sha="c", code_sha="k")
    ctx.finish(0)
    ctx.close_log()
    assert out["valid"] is False
    man = runlog.load_manifest(ctx.directory)
    assert man["baselines"]["audit_steps.pkl"]["valid"] is False
    assert man["baselines"]["audit_steps.pkl"]["changed"] == ["panel"]
