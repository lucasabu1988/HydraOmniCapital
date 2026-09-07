"""TASK-394/395/396 — the backup service's contract.

What a generation is, what makes one complete, and what the service refuses. The reproductions of
the incidents live next door in `test_backup_regressions.py` (TASK-397); this file is the positive
contract plus the per-check refusals.

Every test builds its own `BackupContext` and declares its own authorised source root. That is not
boilerplate — it IS the design: nothing here can acquire a destination or an authorisation from
the environment, so a test that forgets to declare one publishes nothing.
"""
import json
from pathlib import Path

import pytest

from backup_service import (
    GENERATION_PROFILES,
    MANIFEST_NAME,
    BackupContext,
    BackupRefused,
    ExecutionMode,
    _clear_denied_destinations_for_tests,
    deny_destination,
    generation_is_complete,
    is_safe_entry_name,
    latest_generation,
    new_run_id,
    plan_generation,
    publish_generation,
    read_manifest,
    restore_generation,
    role_for,
    tree_fingerprint,
    verify_generation,
)

DATE = "2026-09-04"


def _live_tree(root: Path, date: str = DATE) -> dict:
    """A minimal but role-complete local tree: state, both sheets, journal, JOURNAL.md."""
    state_dir = root / "state"
    journal_dir = root / "journal"
    state_dir.mkdir(parents=True, exist_ok=True)
    journal_dir.mkdir(parents=True, exist_ok=True)
    state = state_dir / "portfolio_v9.json"
    state.write_text(json.dumps({"capital_reference": 100000.0, "pending": []}), encoding="utf-8")
    md = state_dir / f"instructions_{date}.md"
    md.write_text("# sheet\n", encoding="utf-8")
    js = state_dir / f"instructions_{date}.json"
    js.write_text(json.dumps({"date": date, "orders": []}), encoding="utf-8")
    rec = journal_dir / f"{date}.json"
    rec.write_text(json.dumps({"date": date, "book": {"total": 100000.0}}), encoding="utf-8")
    jmd = journal_dir / "JOURNAL.md"
    jmd.write_text("# journal\n", encoding="utf-8")
    return {"state": state, "sheet_md": md, "sheet_json": js, "journal": rec, "journal_md": jmd,
            "all": [state, md, js, rec, jmd]}


def _ctx(tmp_path: Path, *, profile="daily_v9", date=DATE, dest=None, allowed=None,
         mode=ExecutionMode.LIVE) -> BackupContext:
    return BackupContext.create(
        run_id=new_run_id(), date=date,
        dest_root=dest if dest is not None else tmp_path / "off",
        allowed_source_roots=allowed if allowed is not None else (tmp_path / "live",),
        profile=profile, mode=mode,
    )


@pytest.fixture(autouse=True)
def _keep_the_session_deny_list():
    """A test may add a forbidden destination; it may not remove the ones the test policy
    installed for the whole session (that fence is what keeps the suite off the real root)."""
    from backup_service import denied_destinations
    installed = list(denied_destinations())
    yield
    _clear_denied_destinations_for_tests()
    for d in installed:
        deny_destination(d)


# --------------------------------------------------------------------------- names and roles

@pytest.mark.parametrize("name", [
    "../victim.txt", "..\\victim.txt", "a/b.json", "a\\b.json", "..", ".", "",
    "C:/abs.json", "/abs.json", "C:abs.json", "trailing.", "trailing ", "NUL", "con.json",
    "nul.txt", "bad\x00.json",
])
def test_unsafe_entry_names_are_refused(name):
    """Defect 5 of the rejected branch: it checked the target dir, then did `target / name`, and
    an entry `../victim.txt` overwrote a sibling file."""
    assert not is_safe_entry_name(name)


@pytest.mark.parametrize("name", ["portfolio_v9.json", "2026-09-04.json", "JOURNAL.md",
                                  "instructions_2026-09-04.md", "manifest.json"])
def test_safe_entry_names_are_accepted(name):
    assert is_safe_entry_name(name)


def test_roles_come_from_the_name():
    assert role_for("portfolio_v9.json") == "state"
    assert role_for("instructions_2026-09-04.md") == "sheet_md"
    assert role_for("instructions_2026-09-04.json") == "sheet_json"
    assert role_for("2026-09-04.json") == "journal"
    assert role_for("JOURNAL.md") == "journal_md"
    assert role_for("random.txt") == ""


def test_the_profile_table_is_the_contract():
    assert GENERATION_PROFILES["daily_v9"] == ("state", "sheet_md", "sheet_json", "journal",
                                               "journal_md")
    assert "journal" not in GENERATION_PROFILES["sheet_only"]


# --------------------------------------------------------------------------- 392: no ambient env

def test_a_context_cannot_be_built_without_authorised_roots():
    with pytest.raises(BackupRefused) as e:
        BackupContext.create(run_id=new_run_id(), date=DATE, dest_root="x",
                             allowed_source_roots=(), profile="daily_v9")
    assert e.value.code == "NO_AUTHORISED_SOURCES"


@pytest.mark.parametrize("kwargs,code", [
    ({"run_id": "nope"}, "BAD_RUN_ID"),
    ({"date": "04/09/2026"}, "BAD_DATE"),
    ({"profile": "whatever"}, "UNKNOWN_PROFILE"),
])
def test_a_malformed_context_is_refused(tmp_path, kwargs, code):
    base = {"run_id": new_run_id(), "date": DATE, "dest_root": tmp_path / "off",
            "allowed_source_roots": (tmp_path,), "profile": "daily_v9"}
    base.update(kwargs)
    with pytest.raises(BackupRefused) as e:
        BackupContext.create(**base)
    assert e.value.code == code


# --------------------------------------------------------------------------- 395: publish whole

def test_publish_writes_one_generation_with_one_run_id(tmp_path):
    files = _live_tree(tmp_path / "live")
    ctx = _ctx(tmp_path)
    result = publish_generation(ctx, files["all"])
    gen = result["generation_dir"]
    assert gen == ctx.dest_root / "state_v9" / "20260904" / ctx.run_id
    assert sorted(p.name for p in gen.iterdir()) == sorted(
        [f.name for f in files["all"]] + [MANIFEST_NAME])
    manifest = read_manifest(gen)
    assert manifest["run_id"] == ctx.run_id
    assert manifest["profile"] == "daily_v9"
    assert manifest["mode"] == "live"
    assert {e["run_id"] for e in manifest["files"].values()} == {ctx.run_id}
    assert {e["role"] for e in manifest["files"].values()} == set(GENERATION_PROFILES["daily_v9"])
    assert generation_is_complete(gen, require_profile="daily_v9")
    assert latest_generation(gen.parent) == gen


def test_a_published_generation_is_immutable(tmp_path):
    """No second publication may add to or update a generation in place. That is what stopped the
    rejected branch's 'second copy that updated only the state' from being a complete backup."""
    files = _live_tree(tmp_path / "live")
    ctx = _ctx(tmp_path)
    publish_generation(ctx, files["all"])
    with pytest.raises(BackupRefused) as e:
        publish_generation(ctx, files["all"])
    assert e.value.code == "GENERATION_EXISTS"


def test_two_runs_of_the_same_date_are_two_generations(tmp_path):
    files = _live_tree(tmp_path / "live")
    first = publish_generation(_ctx(tmp_path), files["all"])
    files["state"].write_text(json.dumps({"capital_reference": 100001.0}), encoding="utf-8")
    second = publish_generation(_ctx(tmp_path), files["all"])
    assert first["generation_dir"] != second["generation_dir"]
    assert first["run_id"] != second["run_id"]
    assert generation_is_complete(first["generation_dir"], require_profile="daily_v9")
    assert generation_is_complete(second["generation_dir"], require_profile="daily_v9")
    assert latest_generation(second["generation_dir"].parent) == second["generation_dir"]


def test_a_sheet_only_generation_cannot_pass_as_a_daily_one(tmp_path):
    files = _live_tree(tmp_path / "live")
    ctx = _ctx(tmp_path, profile="sheet_only")
    gen = publish_generation(ctx, [files["state"], files["sheet_md"], files["sheet_json"]])["generation_dir"]
    assert generation_is_complete(gen, require_profile="sheet_only")
    codes = [f.code for f in verify_generation(gen, require_profile="daily_v9")]
    assert "GEN_PROFILE_MISMATCH" in codes


def test_a_drill_generation_cannot_pass_as_the_live_backup(tmp_path):
    files = _live_tree(tmp_path / "live")
    ctx = _ctx(tmp_path, mode=ExecutionMode.DRILL)
    gen = publish_generation(ctx, files["all"])["generation_dir"]
    # `require_profile` is named because "complete" is a claim about a role set: since the second
    # pass, generation_is_complete refuses to make that claim when nothing pinned which set applies
    # (a rewritten profile name used to buy a clean verdict for a generation missing its journal).
    assert not generation_is_complete(gen, require_profile="daily_v9", require_mode=ExecutionMode.LIVE)
    assert generation_is_complete(gen, require_profile="daily_v9", require_mode=ExecutionMode.DRILL)


def test_an_incomplete_set_is_refused_before_anything_is_created(tmp_path):
    files = _live_tree(tmp_path / "live")
    ctx = _ctx(tmp_path)
    before = tree_fingerprint(ctx.dest_root)
    with pytest.raises(BackupRefused) as e:
        publish_generation(ctx, [files["state"], files["sheet_md"], files["sheet_json"]])
    assert e.value.code == "GENERATION_INCOMPLETE"
    assert not ctx.dest_root.exists(), "a refused publication created the destination root"
    assert tree_fingerprint(ctx.dest_root) == before


def test_plan_writes_nothing(tmp_path):
    files = _live_tree(tmp_path / "live")
    ctx = _ctx(tmp_path)
    plan = plan_generation(ctx, files["all"])
    assert plan.names == tuple(sorted(f.name for f in files["all"]))
    assert not ctx.dest_root.exists()


# --------------------------------------------------------------------------- 394: refusals

def test_a_source_outside_the_authorised_roots_is_refused(tmp_path):
    files = _live_tree(tmp_path / "live")
    stray = tmp_path / "elsewhere"
    stray.mkdir()
    fixture = stray / "portfolio_v9.json"
    fixture.write_text(json.dumps({"capital_reference": 8000.0}), encoding="utf-8")
    ctx = _ctx(tmp_path)
    with pytest.raises(BackupRefused) as e:
        publish_generation(ctx, [fixture, files["sheet_md"], files["sheet_json"],
                                 files["journal"], files["journal_md"]])
    assert e.value.code == "SOURCE_NOT_AUTHORISED"
    assert not ctx.dest_root.exists()


def test_a_roleless_file_may_not_enter_a_generation(tmp_path):
    files = _live_tree(tmp_path / "live")
    stray = tmp_path / "live" / "state" / "notes.txt"
    stray.write_text("hello", encoding="utf-8")
    ctx = _ctx(tmp_path)
    with pytest.raises(BackupRefused) as e:
        publish_generation(ctx, files["all"] + [stray])
    assert e.value.code == "SOURCE_UNKNOWN_ROLE"


def test_two_sources_with_the_same_name_are_refused(tmp_path):
    files = _live_tree(tmp_path / "live")
    other = tmp_path / "live" / "second"
    other.mkdir()
    clone = other / "portfolio_v9.json"
    clone.write_text("{}", encoding="utf-8")
    ctx = _ctx(tmp_path)
    with pytest.raises(BackupRefused) as e:
        publish_generation(ctx, files["all"] + [clone])
    assert e.value.code == "SOURCE_NAME_COLLISION"


def test_a_missing_source_is_refused(tmp_path):
    files = _live_tree(tmp_path / "live")
    ctx = _ctx(tmp_path)
    with pytest.raises(BackupRefused) as e:
        publish_generation(ctx, files["all"] + [tmp_path / "live" / "state" / "2026-09-05.json"])
    assert e.value.code == "SOURCE_MISSING"


def test_a_denied_destination_is_refused(tmp_path):
    """The deny list is authorisation, not location: the test policy registers the operator's real
    root, and the service refuses it however a caller arrives at that path."""
    files = _live_tree(tmp_path / "live")
    protected = tmp_path / "protected"
    deny_destination(protected)
    ctx = _ctx(tmp_path, dest=protected / "nested")
    with pytest.raises(BackupRefused) as e:
        publish_generation(ctx, files["all"])
    assert e.value.code == "DEST_DENIED"
    assert not (protected / "nested").exists()


# --------------------------------------------------------------------------- verification

def _published(tmp_path) -> Path:
    files = _live_tree(tmp_path / "live")
    return publish_generation(_ctx(tmp_path), files["all"])["generation_dir"]


def test_an_altered_file_is_caught(tmp_path):
    gen = _published(tmp_path)
    (gen / "portfolio_v9.json").write_text(json.dumps({"capital_reference": 8000.0}), encoding="utf-8")
    codes = [f.code for f in verify_generation(gen)]
    assert "GEN_HASH_MISMATCH" in codes


def test_a_missing_file_is_caught(tmp_path):
    gen = _published(tmp_path)
    (gen / "JOURNAL.md").unlink()
    codes = [f.code for f in verify_generation(gen)]
    assert "GEN_FILE_MISSING" in codes and "GEN_INCOMPLETE" in codes


def test_a_file_appearing_after_publication_is_caught(tmp_path):
    gen = _published(tmp_path)
    (gen / "2026-09-05.json").write_text("{}", encoding="utf-8")
    codes = [f.code for f in verify_generation(gen)]
    assert "GEN_UNTRACKED_FILE" in codes


def test_weakening_required_roles_in_the_manifest_does_not_weaken_the_contract(tmp_path):
    """Defect 7. The rejected branch read `required_roles` from the manifest, so an edited
    manifest with `["state"]` verified clean. Here the roles come from GENERATION_PROFILES."""
    gen = _published(tmp_path)
    man = json.loads((gen / MANIFEST_NAME).read_text(encoding="utf-8"))
    man["required_roles_informational"] = ["state"]
    man["files"] = {k: v for k, v in man["files"].items() if k == "portfolio_v9.json"}
    (gen / MANIFEST_NAME).write_text(json.dumps(man), encoding="utf-8")
    codes = [f.code for f in verify_generation(gen)]
    assert "GEN_INCOMPLETE" in codes or "GEN_UNTRACKED_FILE" in codes


def test_a_manipulated_role_is_caught(tmp_path):
    gen = _published(tmp_path)
    man = json.loads((gen / MANIFEST_NAME).read_text(encoding="utf-8"))
    man["files"]["JOURNAL.md"]["role"] = "state"
    (gen / MANIFEST_NAME).write_text(json.dumps(man), encoding="utf-8")
    codes = [f.code for f in verify_generation(gen)]
    assert "GEN_ROLE_TAMPERED" in codes


def test_roles_from_different_runs_are_not_a_generation(tmp_path):
    """The 21 undecidable files of 2026-09-06 are the reason: no per-file check can say whether a
    state and a journal belong to the same execution. A shared run_id can."""
    gen = _published(tmp_path)
    man = json.loads((gen / MANIFEST_NAME).read_text(encoding="utf-8"))
    man["files"]["2026-09-04.json"]["run_id"] = new_run_id()
    (gen / MANIFEST_NAME).write_text(json.dumps(man), encoding="utf-8")
    codes = [f.code for f in verify_generation(gen)]
    assert "GEN_RUN_ID_MIXED" in codes and "GEN_INCOMPLETE" in codes


def test_a_generation_without_a_manifest_is_not_verifiable(tmp_path):
    gen = _published(tmp_path)
    (gen / MANIFEST_NAME).unlink()
    assert [f.code for f in verify_generation(gen)] == ["GEN_NO_MANIFEST"]


# --------------------------------------------------------------------------- 396: restore

def test_restore_publishes_only_after_validating(tmp_path):
    gen = _published(tmp_path)
    target = tmp_path / "drill"
    out = restore_generation(gen, target, live_state_path=tmp_path / "live" / "state" / "portfolio_v9.json")
    assert sorted(p.name for p in target.iterdir()) == sorted(
        list(out["hashes"]) + [MANIFEST_NAME])
    assert tree_fingerprint(target) == tree_fingerprint(gen)
    assert not list(target.glob(".staging-*")), "staging survived the restore"


def test_restore_refuses_the_live_state_tree_without_creating_anything(tmp_path):
    gen = _published(tmp_path)
    live_state = tmp_path / "live" / "state" / "portfolio_v9.json"
    with pytest.raises(BackupRefused) as e:
        restore_generation(gen, live_state.parent, live_state_path=live_state)
    assert e.value.code == "RESTORE_TARGET_IS_LIVE"


def test_restore_refuses_a_non_empty_target(tmp_path):
    gen = _published(tmp_path)
    target = tmp_path / "drill"
    target.mkdir()
    (target / "keep.txt").write_text("mine", encoding="utf-8")
    before = tree_fingerprint(target)
    with pytest.raises(BackupRefused) as e:
        restore_generation(gen, target, live_state_path=tmp_path / "live" / "state" / "portfolio_v9.json")
    assert e.value.code == "RESTORE_TARGET_NOT_EMPTY"
    assert tree_fingerprint(target) == before


def test_restore_of_a_lesser_profile_is_refused_by_default(tmp_path):
    files = _live_tree(tmp_path / "live")
    gen = publish_generation(_ctx(tmp_path, profile="sheet_only"),
                             [files["state"], files["sheet_md"], files["sheet_json"]])["generation_dir"]
    target = tmp_path / "drill"
    with pytest.raises(BackupRefused) as e:
        restore_generation(gen, target, live_state_path=files["state"])
    assert e.value.code == "RESTORE_SOURCE_INVALID"
    assert not target.exists()


# --------------------------------------------------------------------------- the operator's drills

def test_the_verify_cli_resolves_latest_and_reports_findings(tmp_path):
    """`verify_state.py --verify-generation <date dir>` is step 1 of the RUNBOOK's disk-loss row."""
    import verify_state
    gen = _published(tmp_path)
    assert verify_state.main(["--verify-generation", str(gen.parent)]) == 0
    assert verify_state.main(["--verify-generation", str(gen)]) == 0
    (gen / "portfolio_v9.json").write_text("{}", encoding="utf-8")
    assert verify_state.main(["--verify-generation", str(gen.parent)]) == 1


def test_the_restore_cli_refuses_the_live_tree_and_creates_nothing(tmp_path):
    """Step 2 of the same row. Exit 2 = refused; the live tree must be untouched."""
    import verify_state
    live_state = tmp_path / "live" / "state" / "portfolio_v9.json"
    gen = _published(tmp_path)
    before = tree_fingerprint(live_state.parent)
    rc = verify_state.main(["--restore-into", str(live_state.parent),
                            "--from-generation", str(gen), "--state", str(live_state)])
    assert rc == 2
    assert tree_fingerprint(live_state.parent) == before

    drill = tmp_path / "drill"
    assert verify_state.main(["--restore-into", str(drill), "--from-generation", str(gen.parent),
                              "--state", str(live_state)]) == 0
    assert tree_fingerprint(drill) == tree_fingerprint(gen)
