"""HYDRA-BACKUP-02: a generation is never clobbered, never partial, and never mistaken.

Every test here runs against SYNTHETIC directories under tmp_path. Nothing touches
HYDRA_BACKUP_DIR, OneDrive, or any real generation - which is the rule the ticket itself
sets, and also the rule the old writer broke.

The defects being pinned, all of them realised on 2026-09-13:
  * a second write for the same date overwrote the first;
  * a missing source was skipped in silence, so a two-of-four generation looked complete;
  * nothing recorded where the bytes came from, so test output was indistinguishable from a
    production backup. Three September generations turned out to be pytest fixtures while
    docs/RUNBOOK.md pointed at that directory as the recovery path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core import backup as B  # noqa: E402


@pytest.fixture
def book(tmp_path):
    """A synthetic state/ with the three mandatory files, and an empty backup root."""
    state = tmp_path / "state"
    state.mkdir()
    (state / "portfolio_v9.json").write_text(json.dumps({"capital_reference": 100000.0}),
                                             encoding="utf-8")
    (state / "instructions_20260904.json").write_text('{"orders": []}', encoding="utf-8")
    (state / "instructions_20260904.md").write_text("# sheet\n", encoding="utf-8")
    root = tmp_path / "backups"
    (root / "state_v9").mkdir(parents=True)
    return state, root / "state_v9"


def _sources(state, **over):
    s = dict(state=state / "portfolio_v9.json",
             sheet_json=state / "instructions_20260904.json",
             sheet_md=state / "instructions_20260904.md")
    s.update(over)
    return s


# ------------------------------------------------------------- generations are preserved

def test_a_second_write_for_the_same_date_does_not_touch_the_first(book):
    state, parent = book
    first = B.write_generation(parent, "2026-09-04", _sources(state), silent=True)
    before = (first / "portfolio_v9.json").read_bytes()

    (state / "portfolio_v9.json").write_text('{"capital_reference": 8000.0}', encoding="utf-8")
    second = B.write_generation(parent, "2026-09-04", _sources(state), silent=True)

    assert second != first
    assert second.name == "20260904_r02"
    assert (first / "portfolio_v9.json").read_bytes() == before, "the first generation changed"
    assert b"8000" in (second / "portfolio_v9.json").read_bytes()


def test_generations_keep_counting_up(book):
    state, parent = book
    names = [B.write_generation(parent, "2026-09-04", _sources(state), silent=True).name
             for _ in range(3)]
    assert names == ["20260904", "20260904_r02", "20260904_r03"]


def test_an_existing_generation_directory_is_never_written_into(book):
    """Even an EMPTY directory at that name is someone else's; step over it."""
    state, parent = book
    (parent / "20260904").mkdir(parents=True)
    gen = B.write_generation(parent, "2026-09-04", _sources(state), silent=True)
    assert gen.name == "20260904_r02"
    assert list((parent / "20260904").iterdir()) == [], "the pre-existing directory was used"


# --------------------------------------------------------------- refusal, not a half-write

@pytest.mark.parametrize("role", list(B.MANDATORY_ROLES))
def test_a_missing_mandatory_source_refuses_and_writes_nothing(book, role):
    state, parent = book
    src = _sources(state)
    src[role] = state / "does_not_exist.json"
    with pytest.raises(B.BackupRefused) as exc:
        B.write_generation(parent, "2026-09-04", src, silent=True)
    assert role in str(exc.value)
    assert "Nothing was written" in str(exc.value)
    assert list(parent.iterdir()) == [], "a directory was created for a refused generation"


def test_a_mandatory_source_that_is_a_directory_is_also_refused(book):
    state, parent = book
    src = _sources(state)
    src["state"] = state                      # a directory, not a file
    with pytest.raises(B.BackupRefused):
        B.write_generation(parent, "2026-09-04", src, silent=True)
    assert list(parent.iterdir()) == []


def test_an_optional_source_that_is_absent_is_recorded_not_skipped_silently(book):
    state, parent = book
    src = _sources(state, **{"extra:equity_curve.csv": state / "nope.csv"})
    gen = B.write_generation(parent, "2026-09-04", src, silent=True)
    man = B.read_manifest(gen)
    assert "extra:equity_curve.csv" in man["absent_optional"]
    assert "nope.csv" not in [f for f in man["files"]]


# ------------------------------------------------- the manifest means complete AND verified

def test_the_manifest_is_written_last_so_its_presence_means_complete(book):
    state, parent = book
    gen = B.write_generation(parent, "2026-09-04", _sources(state), silent=True)
    assert B.is_complete(gen)
    man = B.read_manifest(gen)
    assert set(f["role"] for f in man["files"].values()) >= set(B.MANDATORY_ROLES)
    for name, entry in man["files"].items():
        assert entry["sha256"] == B.sha256_file(gen / name), "the manifest hash is not the copy's"
        assert entry["source"].endswith(name), "the manifest must name the real source"


def test_the_recorded_hash_is_read_back_from_the_copy_not_from_the_source(book, monkeypatch):
    """A copy that lands wrong must be caught, not certified by re-hashing the original."""
    state, parent = book
    real_copy = B.shutil.copy2

    def corrupting_copy(src, dst, *a, **k):
        out = real_copy(src, dst, *a, **k)
        if Path(dst).name == "portfolio_v9.json":
            Path(dst).write_bytes(b"TRUNCATED")
        return out

    monkeypatch.setattr(B.shutil, "copy2", corrupting_copy)
    with pytest.raises(B.BackupRefused) as exc:
        B.write_generation(parent, "2026-09-04", _sources(state), silent=True)
    assert "does not match its source" in str(exc.value)
    gen = parent / "20260904"
    assert not B.is_complete(gen), "a corrupt generation must not carry a manifest"


def test_a_generation_without_a_manifest_is_not_complete(book):
    state, parent = book
    gen = B.write_generation(parent, "2026-09-04", _sources(state), silent=True)
    (gen / B.MANIFEST_NAME).unlink()
    assert B.is_complete(gen) is False
    ok, why = B.is_restorable(gen)
    assert ok is False and "partial" in why


# ------------------------------------------------------- identity, not the shape of a path

def test_a_test_destination_is_identified_by_a_marker_file(tmp_path):
    root = tmp_path / "looks-completely-innocent"
    root.mkdir()
    assert B.destination_kind(root) == "production"
    B.mark_test_destination(root)
    assert B.destination_kind(root) == "test"


def test_renaming_a_test_destination_does_not_launder_it(tmp_path):
    """`"hydra-test-backup" in str(path)` describes a NAME. The marker travels with the bytes."""
    root = tmp_path / "hydra-test-backup-abc"
    B.mark_test_destination(root)
    renamed = tmp_path / "state_v9"
    root.rename(renamed)
    assert "hydra-test-backup" not in str(renamed)
    assert B.destination_kind(renamed) == "test", "a rename laundered a test destination"


def test_a_generation_written_into_a_test_destination_says_so_and_is_not_restorable(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    for n, body in (("portfolio_v9.json", "{}"), ("instructions_20260904.json", "{}"),
                    ("instructions_20260904.md", "#")):
        (state / n).write_text(body, encoding="utf-8")
    root = tmp_path / "throwaway"
    B.mark_test_destination(root)
    parent = root / "state_v9"
    parent.mkdir()

    gen = B.write_generation(parent, "2026-09-04", _sources(state), silent=True)
    assert B.read_manifest(gen)["destination_kind"] == "test"
    ok, why = B.is_restorable(gen)
    assert ok is False and "test output" in why


def test_a_real_generation_is_restorable_and_says_why(book):
    state, parent = book
    gen = B.write_generation(parent, "2026-09-04", _sources(state), silent=True)
    ok, why = B.is_restorable(gen)
    assert ok is True, why
    assert "complete" in why


def test_a_missing_generation_is_reported_not_assumed_fine(tmp_path):
    ok, why = B.is_restorable(tmp_path / "20991231")
    assert ok is False and "no such generation" in why


# ------------------------------------------------------------------- nothing is destroyed

def test_no_existing_generation_is_ever_renamed_or_deleted(book):
    state, parent = book
    keep = parent / "20260101"
    keep.mkdir(parents=True)
    (keep / "evidence.bin").write_bytes(b"OLD BUT REAL")
    for _ in range(3):
        B.write_generation(parent, "2026-09-04", _sources(state), silent=True)
    assert (keep / "evidence.bin").read_bytes() == b"OLD BUT REAL"
    assert keep.is_dir()


def test_the_live_writer_delegates_and_refuses_the_same_way(tmp_path, monkeypatch, capsys):
    """portfolio_v9.copy_state_off_disk must not have kept its own quiet path."""
    import portfolio_v9 as P9
    root = tmp_path / "bk"
    B.mark_test_destination(root)
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(root))
    state = tmp_path / "state"
    state.mkdir()
    only_one = state / "portfolio_v9.json"
    only_one.write_text("{}", encoding="utf-8")

    out = P9.copy_state_off_disk("2026-09-04", [only_one], silent=False, book=None)
    assert out is None, "a partial generation was written"
    assert "OFF-DISK BACKUP REFUSED" in capsys.readouterr().out
