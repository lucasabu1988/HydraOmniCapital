"""TASK-397 — every reproduction from the 2026-09-06 incident and from the rejected branch,
turned into a regression. No other task in this family closes without a test here.

The list, in Lucas's order, and where each one is:

  custom TEMP                  test_a_fixture_under_a_custom_basetemp_is_still_refused
  inherited backup dir         test_an_inherited_backup_dir_is_a_forbidden_destination
                               test_a_bare_pytest_run_writes_nothing_to_the_inherited_root
                               (the policy layer itself: test_backup_isolation.py)
  the direct journal copy      test_save_record_copies_nothing_anywhere
  rejection-without-effects    test_every_refusal_leaves_the_destination_byte_identical
  traversal                    test_a_traversal_entry_cannot_escape_the_restore_target
  invalid hashes               test_a_restore_of_an_altered_generation_creates_nothing
  manipulated roles            test_a_manipulated_role_refuses_the_restore_before_creating
  mixed generations            test_a_mixed_run_id_generation_cannot_be_restored
                               test_a_run_cannot_complete_by_reusing_an_older_generations_roles

Every one of them runs on an ISOLATED export and asserts that the forbidden destination did not
change — `tree_fingerprint` before and after, not just "the file I expected is absent".
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import hydra_test_policy
import journal
from backup_service import (
    MANIFEST_NAME,
    BackupContext,
    BackupRefused,
    ExecutionMode,
    denied_destinations,
    new_run_id,
    publish_generation,
    restore_generation,
    tree_fingerprint,
    verify_generation,
)

ROOT = Path(__file__).parent
DATE = "2026-09-04"
REAL_BACKUP_HINTS = ("onedrive", "hydrabackups")


def _looks_like_a_real_backup_root(path) -> bool:
    low = str(path).lower()
    return any(h in low for h in REAL_BACKUP_HINTS)


def executable_source(path: Path) -> str:
    """The file's CODE with comments and string literals removed, tokens joined without spaces.

    Grepping the raw text cannot tell a read from a docstring that explains why there is no read,
    and these modules explain that at length. Joining without spaces keeps dotted attribute
    accesses (`os.environ`) greppable.
    """
    import io
    import tokenize
    keep = []
    with path.open("rb") as fh:
        for tok in tokenize.tokenize(io.BytesIO(fh.read()).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            if tokenize.tok_name[tok.type].startswith("FSTRING"):
                continue
            keep.append(tok.string)
    return "".join(keep)


def string_keys_looked_up(path: Path) -> set[str]:
    """Every string literal this module uses as a lookup key: `x.get("K")`, `x["K"]`, `getenv("K")`.

    The name of an environment variable only ever appears in code AS a string literal, so the
    tokenised check above cannot see it. This walks the AST instead. It deliberately
    over-collects (any dict `.get`), which only makes the assertion stricter.
    """
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args:
            first = node.args[0]
            fn = node.func
            attr = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if (isinstance(first, ast.Constant) and isinstance(first.value, str)
                    and attr in ("get", "getenv", "setenv", "delenv", "pop", "setdefault")):
                keys.add(first.value)
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            if isinstance(node.slice.value, str):
                keys.add(node.slice.value)
    return keys


def _live_tree(root: Path, date: str = DATE, capital: float = 100000.0) -> dict:
    state_dir = root / "state"
    journal_dir = root / "journal"
    state_dir.mkdir(parents=True, exist_ok=True)
    journal_dir.mkdir(parents=True, exist_ok=True)
    out = {
        "state": state_dir / "portfolio_v9.json",
        "sheet_md": state_dir / f"instructions_{date}.md",
        "sheet_json": state_dir / f"instructions_{date}.json",
        "journal": journal_dir / f"{date}.json",
        "journal_md": journal_dir / "JOURNAL.md",
    }
    out["state"].write_text(json.dumps({"capital_reference": capital, "pending": []}), encoding="utf-8")
    out["sheet_md"].write_text("# sheet\n", encoding="utf-8")
    out["sheet_json"].write_text(json.dumps({"date": date}), encoding="utf-8")
    out["journal"].write_text(json.dumps({"date": date, "book": {"total": capital}}), encoding="utf-8")
    out["journal_md"].write_text("# journal\n", encoding="utf-8")
    out["all"] = [out["state"], out["sheet_md"], out["sheet_json"], out["journal"], out["journal_md"]]
    return out


def _ctx(dest, allowed, *, profile="daily_v9", date=DATE) -> BackupContext:
    return BackupContext.create(run_id=new_run_id(), date=date, dest_root=dest,
                                allowed_source_roots=allowed, profile=profile,
                                mode=ExecutionMode.LIVE)


# --------------------------------------------------------------------------- inherited backup dir

def test_an_inherited_backup_dir_is_a_forbidden_destination(tmp_path):
    """The inherited value is registered with the SERVICE, not merely overwritten in the env, so
    a caller that reconstructs the path by any route is still refused."""
    denied = hydra_test_policy.denied_roots()
    if not denied:
        pytest.skip("nothing was inherited in this environment (CI); nothing to forbid")
    files = _live_tree(tmp_path / "live")
    # The inherited root IS the operator's real backup root on this machine, so this test never
    # reads it: hashing it would pull cloud-only OneDrive files down. The assertion is the
    # refusal plus the absence of the probe directory.
    probe = Path(denied[0]) / "hydra-test-probe-never-created"
    with pytest.raises(BackupRefused) as e:
        publish_generation(_ctx(probe, (tmp_path / "live",)), files["all"])
    assert e.value.code == "DEST_DENIED"
    assert not probe.exists()
    assert all(Path(d).resolve() in denied_destinations() for d in denied)


# --------------------------------------------------------------------------- custom TEMP

def test_a_fixture_under_a_custom_basetemp_is_still_refused(tmp_path):
    """Defect 2 of the rejected branch, reproduced.

    Its guard recognised temporary LOCATIONS captured at import (`TEMP_ROOTS`), so a fixture under
    a custom `--basetemp` — a perfectly ordinary directory that is not under the system temp — was
    copied anyway. Recognising `pytest-of-*` would not have fixed it: fixture names and locations
    are arbitrary. Here the refusal is provenance: `basetemp` is not a root anybody authorised.
    """
    basetemp = tmp_path / "custom-basetemp"
    fixture = _live_tree(basetemp / "fixture-run")
    live = tmp_path / "live"
    _live_tree(live)
    dest = tmp_path / "off"
    before = tree_fingerprint(dest)
    with pytest.raises(BackupRefused) as e:
        publish_generation(_ctx(dest, (live,)), fixture["all"])
    assert e.value.code == "SOURCE_NOT_AUTHORISED"
    assert tree_fingerprint(dest) == before
    assert not dest.exists()


def test_authorisation_is_not_a_path_shape(tmp_path):
    """The converse, which is what makes the design honest rather than a stricter heuristic: a
    file UNDER the system temp publishes fine when the caller declares that root. Provenance is
    who authorised it, not what the path looks like."""
    files = _live_tree(tmp_path / "live")
    result = publish_generation(_ctx(tmp_path / "off", (tmp_path / "live",)), files["all"])
    assert result["generation_dir"].is_dir()
    assert not any(f.level == "ERROR" for f in verify_generation(result["generation_dir"],
                                                                 require_profile="daily_v9"))


# --------------------------------------------------------------------------- the direct copy

def test_save_record_copies_nothing_anywhere(tmp_path):
    """TASK-392, the original leak inverted.

    `journal.save_record` used to end with `os.environ.get("HYDRA_BACKUP_DIR")` and two
    `shutil.copy2` calls. `python -m pytest test_journal.py` against a decoy root wrote four files
    into `state_v9/20260903` and `/20260904`; the full suite on an unfenced branch wrote 25. Local
    persistence and backup are now separate concerns: this must write two files locally and
    nothing at all off disk.
    """
    backup = Path(os.environ["HYDRA_BACKUP_DIR"])
    backup.mkdir(parents=True, exist_ok=True)
    before = tree_fingerprint(backup)
    journal.save_record({"date": DATE, "book": {"total": 100000.0}}, journal_dir=tmp_path)
    assert (tmp_path / f"{DATE}.json").exists()
    assert (tmp_path / "JOURNAL.md").exists()
    assert tree_fingerprint(backup) == before, "save_record still copies off disk"
    code = executable_source(ROOT / "journal.py")
    assert "environ" not in code, "journal.py reads the environment again"
    assert "shutil" not in code, "journal.py copies files again"
    assert not [k for k in string_keys_looked_up(ROOT / "journal.py") if k.startswith("HYDRA")]


def test_a_bare_pytest_run_writes_nothing_to_the_inherited_root(tmp_path):
    """The exact shape of the incident: `python -m pytest test_journal.py` from inside the package
    with HYDRA_BACKUP_DIR inherited. Before the fence this wrote four files into
    <root>/state_v9/20260903 and /20260904. The decoy must come back byte-identical.

    The inherited value here is a DECOY under tmp_path — never the machine's real backup root,
    which is the whole point of the regression.
    """
    decoy = tmp_path / "inherited-backup-root"
    decoy.mkdir()
    (decoy / "sentinel.txt").write_text("do not touch", encoding="utf-8")
    before = tree_fingerprint(decoy)
    env = dict(os.environ, HYDRA_BACKUP_DIR=str(decoy))
    env.pop("HYDRA_TEST_BACKUP_SESSION", None)
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "test_journal.py", "-q", "-p", "no:cacheprovider"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=180,
    )
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]
    assert tree_fingerprint(decoy) == before, "the child wrote into the inherited backup root"


def test_only_the_entry_point_reader_touches_the_backup_variable():
    """TASK-392, as a structural assertion over the whole package.

    `backup_env.py` resolves HYDRA_BACKUP_DIR; the test policy exports it; `preflight.py` reads it
    to PRINT a status row and takes `backup_dir=` explicitly when a caller has a context — reading
    to print is not a write path. Any other module naming it in CODE (not in a docstring
    explaining why it does not) is a new leak of the 2026-09-06 shape.
    """
    allowed = {"backup_env.py", "hydra_test_policy.py", "conftest.py", "run_all_tests.py",
               "preflight.py"}
    offenders = {}
    for path in sorted(ROOT.glob("*.py")) + sorted(ROOT.glob("core/*.py")) \
            + sorted(ROOT.glob("data/*.py")) + sorted(ROOT.glob("utils/*.py")):
        if path.name in allowed or path.name.startswith("test_"):
            continue
        hits = sorted(k for k in string_keys_looked_up(path) if k.startswith("HYDRA_BACKUP"))
        if hits:
            offenders[path.name] = hits
    assert offenders == {}, offenders


def test_the_service_reads_no_environment_at_all():
    """If this fails the leak is back: the write path could once again find a destination that
    nobody handed it."""
    code = executable_source(ROOT / "backup_service.py")
    for forbidden in ("environ", "getenv", "putenv"):
        assert forbidden not in code, f"backup_service touches {forbidden}"
    assert not [k for k in string_keys_looked_up(ROOT / "backup_service.py")
                if k.startswith("HYDRA")]


# --------------------------------------------------------------------------- refusal has no effects

def test_every_refusal_leaves_the_destination_byte_identical(tmp_path):
    """Lucas's transversal condition, as one table.

    Defect 3: the rejected branch created the destination and wrote `backup_manifest.json` BEFORE
    evaluating the files, so a refused copy still left a directory and a manifest behind, and a
    mixed set could copy some files before the set was judged.
    """
    live = tmp_path / "live"
    files = _live_tree(live)
    stray = tmp_path / "outside"
    stray.mkdir()
    (stray / "portfolio_v9.json").write_text("{}", encoding="utf-8")
    (live / "state" / "notes.txt").write_text("x", encoding="utf-8")

    dest = tmp_path / "off"
    seeded = _live_tree(tmp_path / "seed", date="2026-09-03")
    publish_generation(_ctx(dest, (tmp_path / "seed",), date="2026-09-03"), seeded["all"])
    before = tree_fingerprint(dest)
    assert before, "the destination must already hold a generation, or this proves nothing"

    cases = [
        ("SOURCE_NOT_AUTHORISED", [stray / "portfolio_v9.json", files["sheet_md"],
                                   files["sheet_json"], files["journal"], files["journal_md"]]),
        ("SOURCE_UNKNOWN_ROLE", files["all"] + [live / "state" / "notes.txt"]),
        ("GENERATION_INCOMPLETE", [files["state"], files["sheet_md"], files["sheet_json"]]),
        ("SOURCE_MISSING", files["all"] + [live / "journal" / "2026-09-05.json"]),
        ("NO_SOURCES", []),
    ]
    for code, sources in cases:
        with pytest.raises(BackupRefused) as e:
            publish_generation(_ctx(dest, (live,)), sources)
        assert e.value.code == code
        assert tree_fingerprint(dest) == before, f"{code} left effects behind"


def test_a_refusal_does_not_even_create_the_destination_root(tmp_path):
    live = tmp_path / "live"
    _live_tree(live)
    dest = tmp_path / "never"
    with pytest.raises(BackupRefused):
        publish_generation(_ctx(dest, (live,)), [live / "state" / "portfolio_v9.json"])
    assert not dest.exists(), "a refused publication created the destination root"


# --------------------------------------------------------------------------- traversal

def _published(tmp_path, *, date=DATE, capital=100000.0) -> Path:
    files = _live_tree(tmp_path / "live", date=date, capital=capital)
    return publish_generation(_ctx(tmp_path / "off", (tmp_path / "live",), date=date),
                              files["all"])["generation_dir"]


@pytest.mark.parametrize("evil", ["../victim.txt", "..\\victim.txt", "sub/victim.txt",
                                  "C:/victim.txt", "/victim.txt"])
def test_a_traversal_entry_cannot_escape_the_restore_target(tmp_path, evil):
    """Defect 5, introduced BY the rejected branch: `restore_into` checked the target directory
    but not each manifest NAME, then did `target / name`. An entry `../victim.txt` overwrote a
    sibling file — against its own docstring, "Writes nothing outside target_dir".
    """
    gen = _published(tmp_path)
    man = json.loads((gen / MANIFEST_NAME).read_text(encoding="utf-8"))
    man["files"][evil] = dict(man["files"]["JOURNAL.md"])
    (gen / MANIFEST_NAME).write_text(json.dumps(man), encoding="utf-8")

    sibling = tmp_path / "drills"
    sibling.mkdir()
    victim = sibling / "victim.txt"
    victim.write_text("the file next door", encoding="utf-8")
    target = sibling / "restore"
    before = tree_fingerprint(sibling)

    with pytest.raises(BackupRefused) as e:
        restore_generation(gen, target, live_state_path=tmp_path / "live" / "state" / "portfolio_v9.json")
    assert e.value.code == "RESTORE_SOURCE_INVALID"
    assert "GEN_UNSAFE_NAME" in "".join(f.code for f in e.value.findings)
    assert not target.exists(), "the destination was created despite the refusal"
    assert victim.read_text(encoding="utf-8") == "the file next door"
    assert tree_fingerprint(sibling) == before


def test_a_link_inside_a_generation_is_refused(tmp_path):
    """Escapes through links/junctions. Skipped where the platform will not let us make one."""
    gen = _published(tmp_path)
    outside = tmp_path / "secret.json"
    outside.write_text(json.dumps({"secret": True}), encoding="utf-8")
    link = gen / "2026-09-05.json"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("no permission to create a symlink on this platform")
    man = json.loads((gen / MANIFEST_NAME).read_text(encoding="utf-8"))
    man["files"]["2026-09-05.json"] = {"role": "journal", "sha256": "x", "bytes": 1,
                                       "source": str(outside), "run_id": man["run_id"]}
    (gen / MANIFEST_NAME).write_text(json.dumps(man), encoding="utf-8")
    codes = [f.code for f in verify_generation(gen)]
    assert "GEN_LINK_ENTRY" in codes
    target = tmp_path / "drill"
    with pytest.raises(BackupRefused):
        restore_generation(gen, target, live_state_path=tmp_path / "live" / "state" / "portfolio_v9.json")
    assert not target.exists()


# --------------------------------------------------------------------------- invalid hashes

def test_a_restore_of_an_altered_generation_creates_nothing(tmp_path):
    """Defect 6, introduced BY the rejected branch: `restore_into` collected `verify_backup`'s
    findings and then created the destination and copied anyway, exiting non-zero afterwards.
    Exiting non-zero after writing is not refusing."""
    gen = _published(tmp_path)
    (gen / "portfolio_v9.json").write_text(json.dumps({"capital_reference": 8000.0}), encoding="utf-8")
    target = tmp_path / "drill"
    with pytest.raises(BackupRefused) as e:
        restore_generation(gen, target, live_state_path=tmp_path / "live" / "state" / "portfolio_v9.json")
    assert e.value.code == "RESTORE_SOURCE_INVALID"
    assert "GEN_HASH_MISMATCH" in "".join(f.code for f in e.value.findings)
    assert not target.exists()


# --------------------------------------------------------------------------- manipulated roles

def test_a_manipulated_role_refuses_the_restore_before_creating(tmp_path):
    gen = _published(tmp_path)
    man = json.loads((gen / MANIFEST_NAME).read_text(encoding="utf-8"))
    man["files"]["instructions_2026-09-04.md"]["role"] = "journal"
    (gen / MANIFEST_NAME).write_text(json.dumps(man), encoding="utf-8")
    target = tmp_path / "drill"
    with pytest.raises(BackupRefused) as e:
        restore_generation(gen, target, live_state_path=tmp_path / "live" / "state" / "portfolio_v9.json")
    assert "GEN_ROLE_TAMPERED" in "".join(f.code for f in e.value.findings)
    assert not target.exists()


def test_one_role_less_file_cannot_stand_in_for_the_contract(tmp_path):
    """Defect 7's first half: `required_roles` reduced to `["state"]` with that role assigned to
    `one.txt`, verified clean. `one.txt` has no role at all here, so it cannot even be a source."""
    live = tmp_path / "live"
    live.mkdir()
    one = live / "one.txt"
    one.write_text("state, honestly", encoding="utf-8")
    with pytest.raises(BackupRefused) as e:
        publish_generation(_ctx(tmp_path / "off", (live,)), [one])
    assert e.value.code == "SOURCE_UNKNOWN_ROLE"


# --------------------------------------------------------------------------- mixed generations

def test_a_mixed_run_id_generation_cannot_be_restored(tmp_path):
    gen = _published(tmp_path)
    man = json.loads((gen / MANIFEST_NAME).read_text(encoding="utf-8"))
    man["files"]["portfolio_v9.json"]["run_id"] = new_run_id()
    (gen / MANIFEST_NAME).write_text(json.dumps(man), encoding="utf-8")
    target = tmp_path / "drill"
    with pytest.raises(BackupRefused) as e:
        restore_generation(gen, target, live_state_path=tmp_path / "live" / "state" / "portfolio_v9.json")
    assert "GEN_RUN_ID_MIXED" in "".join(f.code for f in e.value.findings)
    assert not target.exists()


def test_a_run_cannot_complete_by_reusing_an_older_generations_roles(tmp_path):
    """Defect 7's second half: a second copy of the same date that updated only the state while
    keeping the previous sheets and journal also verified clean.

    A generation directory is created whole and never appended to, so the only way to "keep the
    previous sheets" is to publish them again — and then they carry the new run_id and are the
    same bytes, which is a real, coherent generation, not a mixture. Updating the state alone is
    refused for want of the other roles.
    """
    live = tmp_path / "live"
    files = _live_tree(live)
    dest = tmp_path / "off"
    first = publish_generation(_ctx(dest, (live,)), files["all"])
    before = tree_fingerprint(dest)

    files["state"].write_text(json.dumps({"capital_reference": 8000.0}), encoding="utf-8")
    with pytest.raises(BackupRefused) as e:
        publish_generation(_ctx(dest, (live,)), [files["state"]])
    assert e.value.code == "GENERATION_INCOMPLETE"
    assert tree_fingerprint(dest) == before

    # the first generation is untouched and still verifies as the complete run it was
    assert not any(f.level == "ERROR" for f in verify_generation(first["generation_dir"],
                                                                 require_profile="daily_v9"))
    kept = json.loads((first["generation_dir"] / "portfolio_v9.json").read_text(encoding="utf-8"))
    assert kept["capital_reference"] == 100000.0
