# The backup service — design (TASK-392..397)

Supersedes `feat/astra-12-restore-drill`, which was rejected by adversarial review with seven P1
defects. That branch should be abandoned, not merged: two of its defects were introduced by the
branch itself, and its central idea — recognising temporary *locations* — cannot be repaired.

## The problem, in numbers

`HYDRA_BACKUP_DIR` is a USER variable on the operator's machine. Until this change two write paths
read it from the environment **at call time** and copied into it:

* `journal.py:92` — `dest_root = os.environ.get("HYDRA_BACKUP_DIR")`, then
  `Path(dest_root)/"state_v9"/date` and `shutil.copy2`;
* `portfolio_v9.copy_state_off_disk` — the same read, the same layout.

`run_all_tests.py` handed children `os.environ.copy()`, so every test process inherited the
production destination. Measured: `python -m pytest test_journal.py` against a decoy root wrote
four files into `state_v9/20260903` and `/20260904`; a full suite run on an unfenced branch wrote
25. In the real root, **35 of 60 files were fixtures, 2 were real and 21 were undecidable from
content** — a journal record with an empty book is byte-shaped exactly like the live book, which is
also empty until the first settle. That last number is the argument for generations: no per-file
check can answer it.

## The service

`backup_service.py` (top level, beside `journal.py` and `preflight.py`). It reads **no**
environment variable, holds no default destination, and has no ambient state except an explicit
deny list. `test_backup_regressions.py::test_the_service_reads_no_environment_at_all` asserts that
structurally, over the tokenised source.

### What a caller must pass

```python
BackupContext.create(
    run_id=new_run_id(),            # one id for the whole execution
    date="2026-09-04",              # the trading date, YYYY-MM-DD
    dest_root=Path(...),            # WHERE. resolved by the caller, never discovered
    allowed_source_roots=(ROOT,),   # WHAT this caller is authorised to publish
    profile="daily_v9",             # WHICH role set makes a complete generation
    mode=ExecutionMode.LIVE,        # LIVE or DRILL
    denied_dest_roots=(),           # optional extra forbidden destinations
)
```

`allowed_source_roots` is the whole provenance policy. A source file is copied only if it resolves
under one of those roots. It is **authorisation, not location**: the rejected branch captured
`TEMP_ROOTS` at import and asked "does this path look temporary", and a fixture under a custom
`--basetemp` was copied anyway — fixture names and locations are arbitrary. Here a fixture nobody
declared is simply not authorised, and a caller that declares nothing publishes nothing (fails
closed). The converse is also true and is tested: a file under the system temp publishes fine when
its caller declares that root, because a path shape is not evidence of anything.

### Interface

| Function | Guarantee |
|---|---|
| `plan_generation(ctx, sources) -> GenerationPlan` | Validates sources and destination. Creates and writes nothing. |
| `publish_generation(ctx, sources) -> dict` | Validates, stages, verifies the staged copy, then publishes by one `os.replace` of the staging directory. |
| `verify_generation(dir, *, require_profile=, require_mode=)` | Read-only findings: hashes, sizes, names, roles, run\_id coherence, untracked files, required roles. |
| `generation_is_complete(dir, ...) -> bool` | No ERROR findings. |
| `restore_generation(gen, target, *, live_state_path, require_profile="daily_v9")` | Verify → judge target → judge every name → stage inside the target → verify staging → publish. |
| `latest_generation(date_dir) -> Path \| None` | The `LATEST` pointer, refused if unsafe. |
| `tree_fingerprint(root) -> {relpath: sha256}` | The measurement "same file set, count and hashes" is made with. |
| `deny_destination(path)` | Registers a root this process may never publish into. |

Refusals raise `BackupRefused(code, message, findings)`. Every code is one of a closed set:
`DEST_DENIED`, `SOURCE_NOT_AUTHORISED`, `SOURCE_UNKNOWN_ROLE`, `SOURCE_NAME_COLLISION`,
`SOURCE_UNSAFE_NAME`, `SOURCE_IS_LINK`, `SOURCE_MISSING`, `GENERATION_INCOMPLETE`,
`GENERATION_EXISTS`, `RESTORE_TARGET_IS_LIVE`, `RESTORE_TARGET_NOT_EMPTY`,
`RESTORE_SOURCE_INVALID`, `RESTORE_ESCAPE`, `RESTORE_HASH_MISMATCH`, …

### Where the environment is read

Exactly one module: **`backup_env.py`**. It resolves `HYDRA_BACKUP_DIR` and the
`os.pathsep`-separated `HYDRA_BACKUP_DENY`, and builds a `BackupContext`. Only three entry points
call it:

* `daily.main` → `build_backup_context()` (profile upgraded to `daily_v9` once the journal exists);
* `portfolio_v9.main` → a `sheet_only` context;
* `verify_state.main` → the drills, which take their paths as arguments.

`preflight.py` still reads the variable to PRINT a status row and takes `backup_dir=` explicitly
when the caller has a context. Reading to print is not a write path;
`test_only_the_entry_point_reader_touches_the_backup_variable` walks the AST of every module in
the package and allows it there and nowhere else.

## What a generation is

```
<HYDRA_BACKUP_DIR>/state_v9/<YYYYMMDD>/<run_id>/portfolio_v9.json
                                              /instructions_<YYYYMMDD>.md
                                              /instructions_<YYYYMMDD>.json
                                              /<YYYY-MM-DD>.json          (journal record)
                                              /JOURNAL.md
                                              /backup_manifest.json
<HYDRA_BACKUP_DIR>/state_v9/<YYYYMMDD>/LATEST                             (a run_id)
```

`run_id` is `<YYYYMMDDTHHMMSSZ>-<8 hex>`. Every manifest entry records the role, sha256, byte size,
absolute source and **the generation's run\_id**.

Hashes prove byte identity. They do not prove that the state, the sheets and the journal came from
one execution. Three things do:

1. **A common `run_id`.** Every role carries it; `verify_generation` errors `GEN_RUN_ID_MIXED` if
   any entry disagrees with the manifest.
2. **Required roles that cannot be weakened.** The role set comes from `GENERATION_PROFILES` in
   the code, looked up by the manifest's profile NAME. The manifest's own role list is written as
   `required_roles_informational` and is never read back. The rejected branch read
   `required_roles` from the manifest, so editing it to `["state"]` verified clean. A role is also
   recomputed from the file NAME and compared to the manifest's claim (`GEN_ROLE_TAMPERED`), and a
   file with no role in the contract cannot even be a source.
3. **Indivisible publication.** A generation directory is created whole by one `os.replace` and is
   never appended to; a second publication into the same directory is `GENERATION_EXISTS`. A rerun
   of the same date publishes a NEW `run_id`. So the rejected branch's "second copy that updated
   only the state while keeping the previous sheets and journal" is not expressible.

`profile` and `mode` are also part of what "verified" means: a `sheet_only` generation cannot pass
as a `daily_v9` one, and a DRILL copy cannot pass as the book's LIVE backup.

## A refusal has no effects

> A rejected restore or verification may leave no partial effects: before and after the rejection
> the destination tree must keep the same file set, count and hashes. — Lucas

All validation runs before the first `mkdir`. Both write paths then record every directory they
create and unwind them on any exception, so a refusal cannot leave a destination root, a staging
directory or a manifest behind. The rejected branch created the destination and wrote
`backup_manifest.json` *before* judging the files, so a refused copy left both, and a mixed set
could copy some files before the set was judged.

`test_backup_regressions.py::test_every_refusal_leaves_the_destination_byte_identical` runs five
refusal codes against a destination that already holds a real generation and compares
`tree_fingerprint` on both sides of each.

## Restore

Order, and nothing may be created until all of it has passed:

1. `verify_generation(gen, require_profile=...)` — any ERROR raises `RESTORE_SOURCE_INVALID`.
2. The target is judged: not the live state tree, not a parent of it, not a link, and empty or
   absent.
3. Every manifest NAME is judged with `is_safe_entry_name`: one plain path component, no absolute
   path, no drive letter, neither separator, no `.`/`..`, no control characters, no Windows device
   name. The rejected branch checked the target directory and then did `target / name`; an entry
   `../victim.txt` overwrote a sibling file, against its own docstring.
4. Only now: create the target, stage into `target/.staging-<run_id>`, copy, re-hash each file,
   check the resolved path is still inside staging, verify the staged generation, then move the
   files up and remove staging.

`restore_generation` raises instead of copying and exiting non-zero afterwards. Exiting non-zero
after writing is not refusing.

CLI:

```
python verify_state.py --verify-generation <generation dir | date dir>
python verify_state.py --restore-into D:/tmp/drill --from-generation <generation dir>
```

## Test isolation (TASK-393)

`hydra_test_policy.py` is the policy, installed by IMPORT from two places before any package
module loads: the top of `conftest.py` (pytest-routed files) and the top of `run_all_tests.py`
(files run as scripts, which never load a conftest). It:

* **exports** `HYDRA_BACKUP_DIR` for this process and its children;
* gives each process its own directory `p<pid>-<token>` inside one throwaway session tree;
* builds child environments explicitly (`build_child_env` strips every `HYDRA_BACKUP*` variable and
  sets exactly the policy ones) instead of `os.environ.copy()`;
* registers whatever the process INHERITED with `backup_service.deny_destination()` and exports it
  in `HYDRA_BACKUP_DENY`, so the service refuses that destination however a caller reaches it.

None of this is the load-bearing guarantee. The load-bearing guarantee is that the service reads no
environment and copies nothing unauthorised; the policy is the fence around it for the day some
future write path forgets.

## Regressions (TASK-397)

| Reproduction | Test |
|---|---|
| custom TEMP / `--basetemp` | `test_a_fixture_under_a_custom_basetemp_is_still_refused` |
| authorisation is not a path shape | `test_authorisation_is_not_a_path_shape` |
| inherited backup dir | `test_an_inherited_backup_dir_is_a_forbidden_destination`, `test_a_bare_pytest_run_writes_nothing_to_the_inherited_root` |
| the direct journal copy | `test_save_record_copies_nothing_anywhere`, `test_only_the_entry_point_reader_touches_the_backup_variable` |
| rejection without effects | `test_every_refusal_leaves_the_destination_byte_identical`, `test_a_refusal_does_not_even_create_the_destination_root` |
| traversal | `test_a_traversal_entry_cannot_escape_the_restore_target` (5 shapes), `test_a_link_inside_a_generation_is_refused` |
| invalid hashes | `test_a_restore_of_an_altered_generation_creates_nothing` |
| manipulated roles | `test_a_manipulated_role_refuses_the_restore_before_creating`, `test_one_role_less_file_cannot_stand_in_for_the_contract` |
| mixed generations | `test_a_mixed_run_id_generation_cannot_be_restored`, `test_a_run_cannot_complete_by_reusing_an_older_generations_roles` |
| the daily run end to end | `test_daily_generation.py` (5 tests) |

## Ported from the rejected branch

Kept, because the review said these survived: the manifest recording hashes and roles; tests that
detect altered, missing and role-less files; a daily run that ends non-zero and records
`incomplete` in `state/run_status.json` when the journal or the backup fails; and the initial
refusal of an occupied target or the declared live state tree.

Dropped: `TEMP_ROOTS` / `refuses_synthetic_copy` / `BACKUP_SYNTHETIC_SOURCE` (location, not
provenance); manifests that accumulate entries across repeated copies of one date (the opposite of
an indivisible generation); `required_roles` read from the manifest; `restore_into`'s
copy-then-report.

## Not in this change

`closeout()` (the broker-CSV drill from the rejected branch's `verify_state.py`) is unrelated to
the backup seam and is not ported here. `docs/RUNBOOK.md` still describes the pre-generation
layout for historical copies made before this lands; those directories have no manifest and
`verify_generation` reports `GEN_NO_MANIFEST` on them, which is the correct answer — they were
never verifiable.

## What this design does NOT promise (second pass, 2026-09-07)

An adversarial pass took the first version apart — six files written outside the directory named on
the command line through a junction, a restore that ignored the deny list, and a refusal that
deleted a concurrently published generation. Those are fixed and each one has a regression in
`test_backup_attack_regressions.py`. Two findings from the same pass are **limits**, not defects,
and are written here so nobody has to rediscover them:

1. **The `run_id` detects accidental incoherence, not tampering.** It lives in the same unsigned
   manifest as the hashes, so an editor who re-stamps one `run_id` and recomputes the hashes
   produces a set that verifies. Closing that needs a signing key this project does not have. The
   check that does not depend on the editor's cooperation is `GEN_DATE_INCOHERENT`: it compares the
   manifest's date against the dates encoded in the file NAMES, so yesterday's sheet cannot fill
   today's role however the manifest is rewritten.
2. **A killed process leaves staging debris.** A refusal removes its own staging tree; a `SIGKILL`
   cannot. The debris is inert — it is not a generation, `latest_generation` never resolves to it,
   `verify_generation` never reads it — but it accumulates. `stale_staging(date_dir)` names it and
   `sweep_staging(date_dir, keep_run_id=...)` removes it; the `keep_run_id` argument exists because
   sweeping blindly would delete a publish that is staging right now, which is precisely the
   mistake the old rollback made.

And one rule the second pass turned into code, after breaking it itself: **a rollback removes what
it OWNS, not what it merely created.** A staging tree carries our own `run_id` and nobody else
knows its name, so it goes whole; a shared ancestor may hold a neighbour's generation, so it goes
only while empty. Tightening that to "empty only" everywhere is what left partial files behind on
a refusal — a refusal with effects, which is the one condition this task exists to hold.
