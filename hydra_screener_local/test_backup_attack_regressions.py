"""Second pass — every escape an adversarial agent found, as a regression.

The first version of this service passed its own 72 tests and was then taken apart: six files
written outside the directory named on the command line via a junction, a restore that ignored the
deny list, a refusal that deleted a concurrently published good generation, and three ways to make
an incoherent set verify complete. That is the same shape as the failure before it, so each escape
gets a test here rather than a paragraph in a commit message.

Nothing in this file writes outside its own `tmp_path`. The junction tests need `mklink /J`, which
needs no elevation on Windows; where the OS cannot make one the test says so out loud instead of
passing quietly, because a silent skip is how this project has been fooled before.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import backup_service as BS
from backup_service import (
    BackupContext,
    BackupRefused,
    ExecutionMode,
    _Unwind,
    denied_destinations,
    deny_destination,
    generation_is_complete,
    new_run_id,
    publish_generation,
    read_manifest,
    restore_generation,
    tree_fingerprint,
    verify_generation,
)
from backup_service import _clear_denied_destinations_for_tests

DATE = "2026-09-04"


# --------------------------------------------------------------------------- helpers
def _live_tree(root: Path, date: str = DATE) -> dict:
    state_dir, journal_dir = root / "state", root / "journal"
    state_dir.mkdir(parents=True, exist_ok=True)
    journal_dir.mkdir(parents=True, exist_ok=True)
    state = state_dir / "portfolio_v9.json"
    state.write_text(json.dumps({"capital_reference": 100000.0, "pending": []}), encoding="utf-8")
    md = state_dir / f"instructions_{date}.md"
    md.write_text("# sheet\n", encoding="utf-8")
    js = state_dir / f"instructions_{date}.json"
    js.write_text(json.dumps({"date": date, "orders": []}), encoding="utf-8")
    rec = journal_dir / f"{date}.json"
    rec.write_text(json.dumps({"date": date}), encoding="utf-8")
    jmd = journal_dir / "JOURNAL.md"
    jmd.write_text("# journal\n", encoding="utf-8")
    return {"state": state, "sheet_md": md, "sheet_json": js, "journal": rec, "journal_md": jmd,
            "all": [state, md, js, rec, jmd]}


def _ctx(tmp_path: Path, *, date=DATE, dest=None, profile="daily_v9") -> BackupContext:
    return BackupContext.create(
        run_id=new_run_id(), date=date,
        dest_root=dest if dest is not None else tmp_path / "off",
        allowed_source_roots=(tmp_path / "live",), profile=profile, mode=ExecutionMode.DRILL)


def _make_junction(link: Path, target: Path) -> bool:
    """A real junction, or False if this OS/build cannot make one."""
    target.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        try:
            link.symlink_to(target, target_is_directory=True)
            return True
        except (OSError, NotImplementedError):  # pragma: no cover - platform dependent
            return False
    out = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                         capture_output=True, text=True)
    return out.returncode == 0 and link.exists()


def _published(tmp_path: Path, date: str = DATE):
    files = _live_tree(tmp_path / "live", date)
    ctx = _ctx(tmp_path, date=date)
    return publish_generation(ctx, files["all"])["generation_dir"]


@pytest.fixture(autouse=True)
def _keep_the_session_deny_list():
    installed = list(denied_destinations())
    yield
    _clear_denied_destinations_for_tests()
    for d in installed:
        deny_destination(d)


# --------------------------------------------------------------------------- the write escapes
def test_a_junction_as_the_restore_target_is_refused(tmp_path):
    """Escape 1: the guard tested `resolve().is_symlink()`, and resolve() had already followed the
    link. Six files landed in the junction's target and the CLI printed success."""
    gen = _published(tmp_path)
    elsewhere = tmp_path / "somewhere_else"
    link = tmp_path / "drill_target"
    if not _make_junction(link, elsewhere):
        pytest.fail("could not create a junction on this machine; the guard is untested here")
    before = tree_fingerprint(elsewhere)
    with pytest.raises(BackupRefused) as e:
        restore_generation(gen, link, live_state_path=tmp_path / "live" / "state" / "portfolio_v9.json")
    assert e.value.code == "RESTORE_TARGET_IS_LINK"
    assert tree_fingerprint(elsewhere) == before == {}


def test_a_junctioned_parent_is_refused(tmp_path):
    """Escape 2: the resolved path was judged and the UNRESOLVED one created, so a target under a
    junctioned parent was created through the link."""
    gen = _published(tmp_path)
    elsewhere = tmp_path / "outside"
    parent = tmp_path / "pjunction"
    if not _make_junction(parent, elsewhere):
        pytest.fail("could not create a junction on this machine; the guard is untested here")
    with pytest.raises(BackupRefused) as e:
        restore_generation(gen, parent / "sub" / "deep",
                           live_state_path=tmp_path / "live" / "state" / "portfolio_v9.json")
    assert e.value.code == "RESTORE_TARGET_IS_LINK"
    assert tree_fingerprint(elsewhere) == {}


def test_link_on_path_sees_a_junction_anywhere_on_the_way_in(tmp_path):
    real = tmp_path / "real"
    link = tmp_path / "j"
    if not _make_junction(link, real):
        pytest.fail("could not create a junction on this machine")
    assert BS.link_on_path(link) == link
    assert BS.link_on_path(link / "a" / "b") == link
    assert BS.link_on_path(tmp_path / "plain" / "path") is None


def test_restore_obeys_the_deny_list(tmp_path):
    """Escape 3: publish checked `forbidden_by()`, restore checked nothing, so the one fence the
    test policy installs did not cover the restore path at all."""
    gen = _published(tmp_path)
    forbidden = tmp_path / "pretend_real_backup"
    forbidden.mkdir()
    deny_destination(forbidden)
    with pytest.raises(BackupRefused) as e:
        restore_generation(gen, forbidden / "state_v9" / "restored",
                           live_state_path=tmp_path / "live" / "state" / "portfolio_v9.json")
    assert e.value.code == "RESTORE_TARGET_DENIED"
    assert tree_fingerprint(forbidden) == {}


def test_a_rollback_does_not_delete_what_it_did_not_create(tmp_path):
    """Escape 4, the worst one: `_Unwind.rollback` rmtree'd every directory it believed it had
    created. Two publishes racing into the same date directory was enough — A recorded it, B
    published a complete generation inside it, and A's refusal deleted B's backup."""
    shared = tmp_path / "dest" / "state_v9" / "20260904"
    unwind = _Unwind()
    unwind.mkdir(shared)                      # A believes it owns dest/, state_v9/ and the date dir
    neighbour = shared / "20260904T000000Z-deadbeef"
    neighbour.mkdir(parents=True)
    (neighbour / "portfolio_v9.json").write_text("{}", encoding="utf-8")
    keep = tree_fingerprint(tmp_path / "dest")
    unwind.rollback()
    assert (neighbour / "portfolio_v9.json").is_file(), "the rollback destroyed a neighbour's work"
    assert tree_fingerprint(tmp_path / "dest") == keep


def test_a_rollback_still_removes_its_own_empty_directories(tmp_path):
    root = tmp_path / "dest"
    unwind = _Unwind()
    unwind.mkdir(root / "a" / "b" / "c")
    unwind.rollback()
    assert not root.exists(), "nothing of ours must survive a refusal"


# --------------------------------------------------------------------------- verification holes
def test_publishing_another_days_files_under_todays_date_is_refused(tmp_path):
    """Escape 5: `role_for` matched ANY day's sheet, so a generation stamped 09-06 whose sheet and
    journal were 09-04 files verified COMPLETE. Date coherence was the caller's job and nobody
    else's. Now the publish itself refuses, so the incoherent set never exists."""
    files = _live_tree(tmp_path / "live", DATE)          # 2026-09-04 artefacts
    ctx = _ctx(tmp_path, date="2026-09-06")              # stamped a different day
    with pytest.raises(BackupRefused) as e:
        publish_generation(ctx, files["all"])
    assert e.value.code == "STAGED_GENERATION_INVALID"
    assert "GEN_DATE_INCOHERENT" in str(e.value)
    assert tree_fingerprint(ctx.dest_root) == {}, "a refusal leaves nothing behind"


def test_a_forged_mixed_date_generation_does_not_verify(tmp_path):
    """The attacker's actual route was a hand-forged manifest, not the publish path: swap in another
    day's sheet and recompute the hashes. The roles are all filled, by the wrong day's files."""
    gen = _published(tmp_path, DATE)
    manifest = read_manifest(gen)
    old_name = next(n for n, r in manifest["files"].items() if r["role"] == "sheet_md")
    (gen / old_name).unlink()
    del manifest["files"][old_name]
    forged = gen / "instructions_20260906.md"            # a different day, same role
    forged.write_text("# another day\n", encoding="utf-8")
    manifest["files"][forged.name] = {
        "role": "sheet_md", "sha256": BS.sha256_file(forged),
        "bytes": forged.stat().st_size, "run_id": manifest["run_id"],
    }
    (gen / BS.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")

    codes = [f.code for f in verify_generation(gen, require_profile="daily_v9")]
    assert "GEN_DATE_INCOHERENT" in codes
    assert not generation_is_complete(gen, require_profile="daily_v9")


def test_a_coherent_generation_still_verifies(tmp_path):
    gen = _published(tmp_path)
    assert generation_is_complete(gen, require_profile="daily_v9")
    assert [f.code for f in verify_generation(gen, require_profile="daily_v9")] == []


def test_date_in_name_reads_both_sheet_spellings():
    assert BS.date_in_name("instructions_20260904.md") == "2026-09-04"
    assert BS.date_in_name("instructions_2026-09-04.json") == "2026-09-04"
    assert BS.date_in_name("2026-09-04.json") == "2026-09-04"
    assert BS.date_in_name("portfolio_v9.json") is None
    assert BS.date_in_name("JOURNAL.md") is None


def test_a_downgraded_profile_no_longer_buys_a_clean_verdict(tmp_path):
    """Escape 6: cutting `required_roles` was refused, but rewriting the profile NAME was not —
    `daily_v9` -> `sheet_only` plus deleting the journal verified clean with no profile demanded."""
    gen = _published(tmp_path)
    manifest = read_manifest(gen)
    for role in ("journal", "journal_md"):
        name = next(n for n, r in manifest["files"].items() if r["role"] == role)
        (gen / name).unlink()
        del manifest["files"][name]
    manifest["profile"] = "sheet_only"
    (gen / BS.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")

    assert not generation_is_complete(gen), "a set whose role list was chosen by itself is not complete"
    codes = [f.code for f in verify_generation(gen)]
    assert "GEN_PROFILE_UNVERIFIED" in codes
    with pytest.raises(BackupRefused) as e:
        restore_generation(gen, tmp_path / "restored",
                           live_state_path=tmp_path / "live" / "state" / "portfolio_v9.json")
    assert e.value.code == "RESTORE_SOURCE_INVALID"


def test_two_names_differing_only_in_case_are_refused(tmp_path):
    """Escape 7's second half: on NTFS they are one file and two manifest entries, and the manifest
    verified complete while listing a file that was not a distinct file."""
    files = _live_tree(tmp_path / "live")
    twin = files["journal_md"].with_name("journal.MD")
    twin.write_text("# twin\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    with pytest.raises(BackupRefused) as e:
        publish_generation(ctx, files["all"] + [twin])
    assert e.value.code == "SOURCE_NAME_CASE_COLLISION"
    assert tree_fingerprint(ctx.dest_root) == {}


# --------------------------------------------------------------------------- the environment fence
def test_the_deny_decision_is_not_a_path_shape(tmp_path, monkeypatch):
    """A path is not trustworthy because of what it is called. An inherited value merely CONTAINING
    the marker substring was treated as a throwaway and never denied, leaving the service with no
    forbidden root at all."""
    import hydra_test_policy as P
    trap = tmp_path / "OneDrive" / "HydraBackups" / "hydra-test-backup" / "oops"
    trap.mkdir(parents=True)
    monkeypatch.setattr(P, "_INSTALLED", None)
    monkeypatch.setenv(P.ENV_BACKUP_DIR, str(trap))
    monkeypatch.delenv(P.ENV_BACKUP_DENY, raising=False)
    monkeypatch.delenv(P.ENV_SESSION, raising=False)
    state = P.install()
    try:
        assert str(trap) in state["denied"], "an inherited destination is denied whatever it is called"
    finally:
        monkeypatch.setattr(P, "_INSTALLED", None)


def test_a_session_root_must_prove_it_is_ours(tmp_path, monkeypatch):
    """The session variable could relocate the whole suite's destination into any directory whose
    NAME carried the marker; ownership is now a file this policy wrote."""
    import hydra_test_policy as P
    hijack = tmp_path / "hydra-test-backup-session-hijack"
    hijack.mkdir()
    assert not P._is_our_session(str(hijack))
    (hijack / P.OWNERSHIP_MARKER).write_text("x", encoding="utf-8")
    assert P._is_our_session(str(hijack))
    assert not P._is_our_session("")
    assert not P._is_our_session(str(tmp_path / "does_not_exist"))


def test_the_child_environment_drops_the_session_variable(tmp_path):
    """`HYDRA_TEST_BACKUP_SESSION` does not start with HYDRA_BACKUP, so the original strip left in
    place the one variable that relocates the session tree — contrary to its own docstring."""
    import hydra_test_policy as P
    base = {"PATH": os.environ.get("PATH", ""),
            "HYDRA_BACKUP_DIR": r"C:\Users\caslu\OneDrive\HydraBackups",
            "HYDRA_TEST_BACKUP_SESSION": r"C:\somewhere\hostile",
            "UNIVERSE": "all"}
    env = P.build_child_env(base=base)
    assert env["HYDRA_BACKUP_DIR"] == str(P.process_backup_dir())
    assert env["HYDRA_TEST_BACKUP_SESSION"] == str(P.session_root())
    assert env["UNIVERSE"] == "all", "unrelated opt-ins still pass through"


def test_the_fence_is_not_removable_by_a_public_name():
    """It was public API, and an adversarial pass published seven files into the root the policy had
    just denied by calling it. Renaming does not make it safe — it makes it visible."""
    assert not hasattr(BS, "clear_denied_destinations")
    assert callable(BS._clear_denied_destinations_for_tests)


def test_a_refusal_after_the_copy_began_leaves_no_staging_directory(tmp_path):
    """Found by the test above while fixing escape 4, which is why it is here rather than in a
    commit message: tightening the rollback to "remove only what is empty" left
    `.staging-<run_id>` behind with its partial files on every refusal that happened after the
    copy started. The staging tree is exclusively ours, so it is removed whole; the shared
    ancestors it sits under are still only removed while empty.
    """
    files = _live_tree(tmp_path / "live", DATE)
    ctx = _ctx(tmp_path, date="2026-09-06")          # incoherent on purpose: refuses after copying
    with pytest.raises(BackupRefused) as e:
        publish_generation(ctx, files["all"])
    assert e.value.code == "STAGED_GENERATION_INVALID"
    assert tree_fingerprint(ctx.dest_root) == {}, "a refusal must leave the destination as it was"
    assert not ctx.dest_root.exists(), "and must not leave the destination root behind either"


def test_a_refusal_next_to_a_published_generation_keeps_the_neighbour(tmp_path):
    """The two halves together: our staging goes, the neighbour's generation stays."""
    good = _published(tmp_path, DATE)
    dest = good.parent.parent.parent                  # <dest>/state_v9/<date>/<run_id>
    keep = tree_fingerprint(dest)
    bad_files = _live_tree(tmp_path / "live", DATE)
    bad_ctx = BackupContext.create(
        run_id=new_run_id(), date=DATE, dest_root=dest,
        allowed_source_roots=(tmp_path / "live",), profile="daily_v9", mode=ExecutionMode.DRILL)
    twin = bad_files["journal_md"].with_name("journal.MD")
    twin.write_text("# twin\n", encoding="utf-8")
    with pytest.raises(BackupRefused):
        publish_generation(bad_ctx, bad_files["all"] + [twin])
    assert tree_fingerprint(dest) == keep
    assert generation_is_complete(good, require_profile="daily_v9")


def test_staging_debris_from_a_killed_process_can_be_named_and_swept(tmp_path):
    """Escape 11 is a limit, not a defect: a refusal cleans its staging, a SIGKILL cannot. So the
    debris has to be nameable. Sweeping must never take a publish that is in flight."""
    gen = _published(tmp_path)
    date_dir = gen.parent
    dead = date_dir / f"{BS._STAGING_PREFIX}20260904T000000Z-deadbeef"
    dead.mkdir()
    (dead / "portfolio_v9.json").write_text("{}", encoding="utf-8")
    inflight = date_dir / f"{BS._STAGING_PREFIX}20260904T111111Z-inflight"
    inflight.mkdir()

    assert BS.stale_staging(date_dir) == sorted([dead, inflight])
    assert BS.stale_staging(date_dir, keep_run_id="20260904T111111Z-inflight") == [dead]
    removed = BS.sweep_staging(date_dir, keep_run_id="20260904T111111Z-inflight")
    assert removed == [dead] and not dead.exists()
    assert inflight.is_dir(), "sweeping must not delete a publish that is staging right now"
    assert generation_is_complete(gen, require_profile="daily_v9"), "and must not touch a generation"
