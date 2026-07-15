# Private Git Project Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent private Git repository that safely synchronizes per-project task snapshots across devices and generates a cross-project task and activity collection.

**Architecture:** Canonicalize each project snapshot into a deterministic content hash and store the last shared hash locally. `memory sync` fetches and fast-forwards the private memory repository, compares local, memory, and base hashes, then transfers a complete validated snapshot only when one side changed. Uploads rebuild all global projections and create at most one commit; divergent changes stop without overwrite or automatic merge.

**Tech Stack:** Python 3 standard library (`hashlib`, `json`, `os`, `pathlib`, `shutil`, `subprocess`, `tempfile`), Git CLI, existing task, project, activity, and atomic modules, `unittest` with local bare remotes.

## Global Constraints

- Stage one local tasks must remain fully usable without memory configuration or network access.
- The private memory repository is not a task editing surface.
- Add no third-party dependency.
- Never create a public repository or assume GitHub; the user creates and authorizes any remote.
- Fetch before sync and only fast-forward the current memory branch.
- Never force, rebase, create merge commits, or resolve task content conflicts automatically.
- Use canonical content hashes rather than wall-clock ordering to choose sync direction.
- Transfer only `project.json`, `task-state.json`, `tasks/`, and `history/`; regenerate indexes and entry points.
- Reject symlink escapes, invalid snapshots, secrets, project ID conflicts, and activity identity conflicts before replacement.
- Keep handoff documents local to their source repository and never copy them into private memory.
- A failed push keeps the valid local memory commit and reports that remote synchronization is incomplete.

## File Map

- Create `handoff_core/snapshot.py`: enumerate, validate, hash, stage, and install canonical project snapshots.
- Create `handoff_core/memory_git.py`: memory repository Git status, upstream, fetch, fast-forward, commit, and push operations.
- Create `handoff_core/memory_service.py`: configuration, three-way decision, recoverable transfer, aggregation, and sync results.
- Modify `handoff_core/project.py`: expose project file parsing needed by snapshot validation.
- Modify `handoff.py`: nested `memory init|status|sync` commands.
- Create `tests/test_memory.py`: hash, validation, aggregation, transaction, and conflict tests.
- Create `tests/test_memory_cli.py`: init, status, upload, download, no-op, divergence, and push behavior.
- Modify `tests/test_distribution.py`: memory guidance and bilingual documentation contract.
- Modify `SKILL.md`: explicit cross-project query routing and manual sync behavior.
- Modify `adapters/trigger-block.md`: short global-query routing rule.
- Modify `README.md`: bilingual setup, privacy, synchronization, conflict, and recovery instructions.

---

### Task 1: Canonical Snapshot Format and Hash

**Files:**
- Create: `handoff_core/snapshot.py`
- Modify: `handoff_core/project.py`
- Create: `tests/test_memory.py`

**Interfaces:**
- Consumes: `parse_task_draft`, `parse_activity`, project identity parser, `DocumentError`.
- Produces: `Snapshot(project_id: str, digest: str, files: dict[str, bytes])`, `load_snapshot(root: Path) -> Snapshot`, `stage_snapshot(snapshot: Snapshot, destination: Path) -> None`, `install_snapshot(snapshot: Snapshot, project_root: Path) -> None`.

- [ ] **Step 1: Write failing canonical snapshot tests**

```python
from handoff_core.snapshot import install_snapshot, load_snapshot, stage_snapshot


class SnapshotTests(TaskRepoCase):
    def test_hash_ignores_generated_indexes_and_file_times(self) -> None:
        self.tasks.add("project-memory", TASK_DRAFT)
        first = load_snapshot(self.repo)
        (self.repo / ".ai/TASKS.md").write_text("tampered generated view\n", encoding="utf-8")
        os.utime(self.repo / ".ai/tasks/project-memory.md", (1, 1))
        second = load_snapshot(self.repo)
        self.assertEqual(first.digest, second.digest)

    def test_hash_changes_with_semantic_task_or_history(self) -> None:
        self.tasks.add("project-memory", TASK_DRAFT)
        first = load_snapshot(self.repo)
        self.tasks.milestone("project-memory", TASK_DRAFT, "Parser implemented.")
        second = load_snapshot(self.repo)
        self.assertNotEqual(first.digest, second.digest)

    def test_snapshot_rejects_symlinks_and_registry_mismatch(self) -> None:
        self.tasks.add("project-memory", TASK_DRAFT)
        task = self.repo / ".ai/tasks/project-memory.md"
        task.unlink()
        task.symlink_to(self.repo / "tracked.txt")
        with self.assertRaisesRegex(DocumentError, "snapshot_symlink"):
            load_snapshot(self.repo)
```

- [ ] **Step 2: Run snapshot tests and confirm missing module**

Run: `python3 -m unittest tests.test_memory.SnapshotTests -v`

Expected: import failure for `handoff_core.snapshot`.

- [ ] **Step 3: Expose project identity parsing**

In `handoff_core/project.py`, add:

```python
def parse_project_identity(value: dict[str, object]) -> ProjectIdentity:
    if value.get("version") != 1:
        raise DocumentError("invalid_project")
    project_id = value.get("id")
    name = value.get("name")
    remote = value.get("remote")
    if not isinstance(project_id, str) or not isinstance(name, str):
        raise DocumentError("invalid_project")
    validate_project_id(project_id)
    if remote is not None and not isinstance(remote, str):
        raise DocumentError("invalid_project")
    return ProjectIdentity(project_id, name, remote)
```

Use one project ID validator in both creation and parsing.

- [ ] **Step 4: Implement canonical loading and hashing**

Canonical snapshot paths are exactly:

```python
ROOT_FILES = ("project.json", "task-state.json")
TREE_DIRS = ("tasks", "history")
```

`load_snapshot(project_root)` must:

1. Reject symlinks in `.ai` and every included path component.
2. Require valid `project.json` and `task-state.json` version 1.
3. Require registry IDs to equal task filenames.
4. Parse every task file and confirm status matches registry.
5. Parse every history file and confirm its filename equals each event’s local date.
6. Confirm every event project ID equals the snapshot project ID.
7. Serialize JSON files with sorted keys and a trailing newline before hashing.
8. Sort relative POSIX paths and hash `path length + path + content length + content` using SHA-256.

Use an immutable dataclass:

```python
@dataclass(frozen=True)
class Snapshot:
    project_id: str
    digest: str
    files: dict[str, bytes]
```

- [ ] **Step 5: Implement staging and installation**

`stage_snapshot()` writes only canonical files beneath a new empty destination and uses mode `0o600` for files. `install_snapshot()` stages under `<repo>/.ai/.memory-stage-*`, validates the staged snapshot, then calls a TaskService helper that transactionally replaces `project.json`, `task-state.json`, `tasks/`, and `history/` and regenerates `README.md` and `TASKS.md`.

Add `TaskService.install_snapshot(files: dict[str, bytes]) -> None` in stage-one code rather than duplicating task index logic.

- [ ] **Step 6: Run snapshot tests**

Run: `python3 -m unittest tests.test_memory.SnapshotTests -v`

Expected: all tests pass.

- [ ] **Step 7: Commit canonical snapshots**

```bash
git add handoff_core/snapshot.py handoff_core/project.py handoff_core/task_service.py tests/test_memory.py
git commit -m "Add canonical project memory snapshots"
```

---

### Task 2: Memory Repository Git Boundary and Configuration

**Files:**
- Create: `handoff_core/memory_git.py`
- Create: `handoff_core/memory_service.py`
- Modify: `tests/test_memory.py`

**Interfaces:**
- Consumes: Git CLI and `repo_root`.
- Produces: `MemoryGit`, `MemoryConfig`, `MemoryResult`, `MemoryService.init(path: Path)`, `MemoryService.status()`.

- [ ] **Step 1: Write failing configuration and Git boundary tests**

```python
from handoff_core.memory_service import MemoryService


class MemoryConfigurationTests(TaskRepoCase):
    def setUp(self) -> None:
        super().setUp()
        self.config_home = self.repo.parent / "config"
        self.memory = self.repo.parent / "memory"
        init_repo(self.memory)
        self.service = MemoryService(self.repo, config_home=self.config_home)

    def test_init_persists_existing_git_repository(self) -> None:
        result = self.service.init(self.memory)
        self.assertEqual("memory_initialized", result.code)
        config = json.loads((self.config_home / "maintaining-task-handoffs/config.json").read_text())
        self.assertEqual(str(self.memory.resolve()), config["memory_path"])

    def test_init_rejects_non_git_directory(self) -> None:
        plain = self.repo.parent / "plain"
        plain.mkdir()
        with self.assertRaisesRegex(DocumentError, "memory_not_git_repo"):
            self.service.init(plain)

    def test_status_reports_dirty_and_upstream(self) -> None:
        self.service.init(self.memory)
        (self.memory / "dirty").write_text("x", encoding="utf-8")
        status = self.service.status()
        self.assertTrue(status.details["dirty"])
        self.assertFalse(status.details["has_upstream"])
```

- [ ] **Step 2: Run tests and confirm missing services**

Run: `python3 -m unittest tests.test_memory.MemoryConfigurationTests -v`

Expected: import failure for `handoff_core.memory_service`.

- [ ] **Step 3: Implement the Git boundary**

Create `MemoryGit` with a single `_run(*args, check=True)` helper. Public methods and exact behavior:

```python
class MemoryGit:
    def __init__(self, root: Path) -> None: ...
    def is_clean(self) -> bool: ...              # git status --porcelain --untracked-files=all
    def head(self) -> str: ...                    # git rev-parse HEAD
    def current_branch(self) -> str: ...          # reject detached HEAD
    def upstream(self) -> str | None: ...         # git rev-parse --abbrev-ref --symbolic-full-name @{u}
    def fetch(self) -> None: ...                  # git fetch --prune
    def can_fast_forward(self, upstream: str) -> bool: ...  # merge-base --is-ancestor HEAD upstream
    def fast_forward(self, upstream: str) -> None: ...      # git merge --ff-only upstream
    def commit(self, message: str) -> str | None: ...       # no diff returns None
    def push(self) -> None: ...                    # plain git push, structured failure
```

Map errors to `memory_dirty`, `memory_detached`, `pull_not_fast_forward`, and `push_failed`. Never invoke force, rebase, or merge without `--ff-only`.

- [ ] **Step 4: Implement configuration and status**

Config path is `${XDG_CONFIG_HOME:-~/.config}/maintaining-task-handoffs/config.json`; tests inject `config_home` directly. Schema:

```json
{
  "version": 1,
  "memory_path": "/absolute/path/to/project-memory"
}
```

`MemoryService.init()` resolves the path, verifies it is a Git repository with at least one commit and a non-detached branch, writes config atomically, and creates no remote. `status()` returns path, clean flag, branch, head, upstream presence, and whether the current project exists under `projects/<project-id>`.

- [ ] **Step 5: Run configuration tests**

Run: `python3 -m unittest tests.test_memory.MemoryConfigurationTests -v`

Expected: all tests pass.

- [ ] **Step 6: Commit memory configuration and Git boundary**

```bash
git add handoff_core/memory_git.py handoff_core/memory_service.py tests/test_memory.py
git commit -m "Add private memory Git boundary"
```

---

### Task 3: Cross-Project Aggregation

**Files:**
- Modify: `handoff_core/memory_service.py`
- Modify: `tests/test_memory.py`

**Interfaces:**
- Consumes: canonical snapshots, task index renderer, activity parser and renderer.
- Produces: `rebuild_memory_views(memory_root: Path) -> dict[str, str]` and validated `registry.json`, `TASKS.md`, `PROJECTS.md`, `history/YYYY-MM-DD.md`.

- [ ] **Step 1: Add failing aggregation tests with two projects**

```python
class MemoryAggregationTests(unittest.TestCase):
    def test_rebuilds_global_tasks_projects_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = create_snapshot_fixture(root / "projects/github.com-owner-one", "github.com-owner-one", "task-one")
            second = create_snapshot_fixture(root / "projects/github.com-owner-two", "github.com-owner-two", "task-two")
            views = rebuild_memory_views(root)
            self.assertIn("github.com-owner-one", views["TASKS.md"])
            self.assertIn("task-two", views["TASKS.md"])
            self.assertIn("projects/github.com-owner-one/TASKS.md", views["PROJECTS.md"])
            self.assertIn("github.com-owner-two/task-two", views["history/2026-07-15.md"])

    def test_conflicting_project_or_event_stops_rebuild(self) -> None:
        with self.assertRaisesRegex(DocumentError, "project_id_conflict"):
            rebuild_memory_views(make_duplicate_project_fixture())
        with self.assertRaisesRegex(DocumentError, "history_conflict"):
            rebuild_memory_views(make_conflicting_history_fixture())
```

- [ ] **Step 2: Run aggregation tests and confirm missing function**

Run: `python3 -m unittest tests.test_memory.MemoryAggregationTests -v`

Expected: import or attribute failure for `rebuild_memory_views`.

- [ ] **Step 3: Implement deterministic project registry and indexes**

Scan only immediate directories under `projects/`; reject symlinks and directory names that differ from the contained project ID. For each validated snapshot, generate its local `TASKS.md` from task files and collect:

```python
{
    "version": 1,
    "projects": {
        project_id: {
            "name": identity.name,
            "snapshot_hash": snapshot.digest,
            "synced": sync_metadata["synced"],
        }
    }
}
```

Root `TASKS.md` groups `in-progress`, `todo`, and `blocked`; within each group sort by project name, task updated descending, and task ID. Every link points to `projects/<project-id>/tasks/<task-id>.md`.

Root `PROJECTS.md` sorts by display name then project ID and includes project ID, latest sync time, and `projects/<project-id>/TASKS.md`.

- [ ] **Step 4: Implement full daily history rebuild**

Parse all project history files, merge by event identity, reject conflicting identities, group by local date encoded in each source filename, and render all root daily files. Return a complete desired view map so sync can remove stale root history files as well as add new ones.

- [ ] **Step 5: Run aggregation tests**

Run: `python3 -m unittest tests.test_memory.MemoryAggregationTests -v`

Expected: all aggregation and conflict tests pass.

- [ ] **Step 6: Commit cross-project aggregation**

```bash
git add handoff_core/memory_service.py tests/test_memory.py
git commit -m "Add cross-project memory aggregation"
```

---

### Task 4: Three-Way Upload, Download, and Divergence Protection

**Files:**
- Modify: `handoff_core/memory_service.py`
- Modify: `handoff_core/task_service.py`
- Modify: `tests/test_memory.py`

**Interfaces:**
- Consumes: snapshot, Git boundary, aggregation, and task snapshot install.
- Produces: `MemoryService.sync(push: bool = True) -> MemoryResult`, `.ai/memory-sync.json`, recoverable memory transaction manifest.

- [ ] **Step 1: Write failing direction and divergence tests**

```python
class MemorySyncTests(MemoryRepoCase):
    def test_first_sync_uploads_and_commits_once(self) -> None:
        self.tasks.add("project-memory", TASK_DRAFT)
        result = self.service.sync(push=False)
        self.assertEqual("memory_uploaded", result.code)
        self.assertTrue((self.memory / f"projects/{self.project_id}/tasks/project-memory.md").is_file())
        self.assertEqual(1, commit_count(self.memory) - self.initial_commits)

    def test_no_change_sync_creates_no_commit(self) -> None:
        self.tasks.add("project-memory", TASK_DRAFT)
        self.service.sync(push=False)
        before = commit_count(self.memory)
        result = self.service.sync(push=False)
        self.assertEqual("memory_current", result.code)
        self.assertEqual(before, commit_count(self.memory))

    def test_memory_only_change_downloads_and_regenerates_views(self) -> None:
        self.tasks.add("project-memory", TASK_DRAFT)
        self.service.sync(push=False)
        replace_memory_snapshot_with_valid_new_task(self.memory, self.project_id)
        commit_all(self.memory, "remote device change")
        (self.repo / ".ai/TASKS.md").write_text("broken\n", encoding="utf-8")
        result = self.service.sync(push=False)
        self.assertEqual("memory_downloaded", result.code)
        self.assertIn("remote-task", (self.repo / ".ai/TASKS.md").read_text())
        self.assertNotIn("broken", (self.repo / ".ai/TASKS.md").read_text())

    def test_both_sides_changed_stops_without_overwrite(self) -> None:
        self.tasks.add("project-memory", TASK_DRAFT)
        self.service.sync(push=False)
        self.tasks.update("project-memory", TASK_DRAFT.replace("parser", "local service"))
        replace_memory_snapshot_with_valid_new_task(self.memory, self.project_id)
        commit_all(self.memory, "remote device change")
        local_before = load_snapshot(self.repo).digest
        memory_before = load_memory_project_snapshot(self.memory, self.project_id).digest
        with self.assertRaisesRegex(DocumentError, "memory_diverged"):
            self.service.sync(push=False)
        self.assertEqual(local_before, load_snapshot(self.repo).digest)
        self.assertEqual(memory_before, load_memory_project_snapshot(self.memory, self.project_id).digest)
```

- [ ] **Step 2: Run sync tests and confirm missing behavior**

Run: `python3 -m unittest tests.test_memory.MemorySyncTests -v`

Expected: failures because `sync()` is absent.

- [ ] **Step 3: Implement base metadata and three-way direction**

Local `.ai/memory-sync.json` schema:

```json
{
  "version": 1,
  "project_id": "github.com-owner-repo",
  "base_hash": "sha256",
  "memory_commit": "git object id"
}
```

Memory project sync metadata lives at `projects/<project-id>/sync.json` and contains `version`, `snapshot_hash`, `synced` ISO timestamp, and source repository identity.

Implement a pure direction function:

```python
def sync_direction(local: str, memory: str | None, base: str | None) -> str:
    if memory is None and base is None:
        return "upload"
    if local == memory:
        return "current"
    if base is not None and memory == base and local != base:
        return "upload"
    if base is not None and local == base and memory != base:
        return "download"
    raise DocumentError("memory_diverged")
```

If no base exists and memory already contains a different snapshot, raise `memory_diverged`.

- [ ] **Step 4: Implement fetch and fast-forward preflight**

Before reading memory snapshot state:

1. Require memory worktree clean.
2. If upstream exists, fetch.
3. Require `HEAD` is an ancestor of upstream.
4. Fast-forward to upstream.
5. Require worktree clean again.

No upstream means local-only sync and no push attempt.

- [ ] **Step 5: Implement recoverable upload**

Stage the current project snapshot outside tracked paths, validate it, copy it into a complete desired memory tree, rebuild every generated view, and write a transaction manifest containing old and new bytes for each affected path. Apply replacements, remove stale generated files, commit once, then update local base metadata.

If push is requested and upstream exists, call plain `git push`. A push failure returns or raises `push_failed`, leaves the commit and base hash intact, and includes `remote_synced: false` in result details.

- [ ] **Step 6: Implement recoverable download**

Validate the memory snapshot before touching the project. Use `TaskService.install_snapshot()` to replace canonical task data and regenerate local indexes. Write `.ai/memory-sync.json` only after install succeeds. Download must not commit or modify other memory projects.

- [ ] **Step 7: Run all memory sync tests**

Run: `python3 -m unittest tests.test_memory.MemorySyncTests -v`

Expected: upload, no-op, download, divergence, rollback, and push-failure tests pass.

- [ ] **Step 8: Commit three-way synchronization**

```bash
git add handoff_core/memory_service.py handoff_core/task_service.py tests/test_memory.py
git commit -m "Add three-way private memory sync"
```

---

### Task 5: Memory CLI and Bare-Remote End-to-End Tests

**Files:**
- Modify: `handoff.py`
- Create: `tests/test_memory_cli.py`

**Interfaces:**
- Consumes: `MemoryService.init`, `status`, and `sync`.
- Produces commands: `handoff memory init --path`, `handoff memory status`, `handoff memory sync [--no-push]`.

- [ ] **Step 1: Write failing CLI tests with a local bare remote**

Create a bare remote, clone it as memory repository, make an initial commit, configure user identity, and exercise:

```python
class MemoryCliTests(unittest.TestCase):
    def test_init_upload_pull_download_and_noop(self) -> None:
        first_device, second_device, memory, remote, config_home = make_two_device_fixture()
        add_task_via_cli(first_device, "shared-task")
        initialized = run_cli(
            "memory", "init", "--path", str(memory),
            cwd=first_device, env={"XDG_CONFIG_HOME": str(config_home)},
        )
        uploaded = run_cli("memory", "sync", cwd=first_device, env=memory_env(config_home))
        clone_memory_for_second_device(remote, memory)
        initialized_second = run_cli(
            "memory", "init", "--path", str(memory),
            cwd=second_device, env=memory_env(config_home),
        )
        downloaded = run_cli("memory", "sync", cwd=second_device, env=memory_env(config_home))
        current = run_cli("memory", "sync", "--no-push", cwd=second_device, env=memory_env(config_home))
        self.assertEqual("memory_initialized", payload(initialized)["code"])
        self.assertEqual("memory_uploaded", payload(uploaded)["code"])
        self.assertEqual("memory_initialized", payload(initialized_second)["code"])
        self.assertEqual("memory_downloaded", payload(downloaded)["code"])
        self.assertEqual("memory_current", payload(current)["code"])
```

Use separate config homes or update the configured clone path between devices; do not share one writable memory worktree concurrently.

Add tests for dirty memory, non-fast-forward upstream, divergence, missing config, and push rejection. Every error must be structured JSON and nonzero.

- [ ] **Step 2: Run memory CLI tests and confirm parser rejection**

Run: `python3 -m unittest tests.test_memory_cli -v`

Expected: `argparse` rejects the unknown `memory` command.

- [ ] **Step 3: Add nested memory parsers**

Add:

```text
handoff memory init --path <path>
handoff memory status
handoff memory sync [--no-push]
```

`init` and `sync` print `MemoryResult.to_dict()` JSON. `status` also prints JSON because it is machine-oriented. Use the same `DocumentError`, I/O, and not-Git error exit conventions as existing commands.

- [ ] **Step 4: Run memory CLI and existing CLI tests**

Run:

```bash
python3 -m unittest tests.test_cli tests.test_task_cli tests.test_memory_cli -v
```

Expected: all handoff, task, and memory commands pass.

- [ ] **Step 5: Commit the memory CLI**

```bash
git add handoff.py tests/test_memory_cli.py
git commit -m "Add private memory sync CLI"
```

---

### Task 6: Cross-Project Query Guidance and Bilingual Documentation

**Files:**
- Modify: `tests/test_distribution.py`
- Modify: `SKILL.md`
- Modify: `adapters/trigger-block.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: memory CLI and generated root indexes.
- Produces: user-facing cross-project query, setup, privacy, and conflict-resolution contract.

- [ ] **Step 1: Add failing documentation contract tests**

Require skill, adapter, and README to include:

```python
for phrase in (
    "handoff memory init",
    "handoff memory sync",
    "all projects",
    "private",
    "memory_diverged",
    "fast-forward",
    "does not copy handoff",
):
    self.assertIn(phrase.lower(), text.lower())
```

Add Chinese README assertions for `所有專案`, `私人`, `不複製 handoff`, `不同步秘密`, and `雙邊都有變更`.

- [ ] **Step 2: Run distribution tests and confirm failures**

Run: `python3 -m unittest tests.test_distribution -v`

Expected: new memory documentation assertions fail.

- [ ] **Step 3: Update skill and adapter routing**

Add concise rules:

- Explicit “all projects” task queries read the configured private memory root `TASKS.md`.
- Explicit cross-project yesterday queries read only the matching root history file.
- Current-project queries still prefer local `.ai/` files.
- The agent may run manual `handoff memory sync` when the user asks to synchronize; it must report local commit success separately from remote push success.
- The memory repository must be private, but secrets remain forbidden.
- Handoff files are never copied.

Do not make every ordinary prompt read the global memory repository.

- [ ] **Step 4: Update bilingual README**

Document:

1. Creating a private Git repository and cloning it locally.
2. `handoff memory init --path ~/project-memory`.
3. Manual sync lifecycle and one-commit batching.
4. Cross-device upload/download based on base hash.
5. Dirty, non-fast-forward, divergence, and push failure behavior.
6. Explicit manual resolution: choose one side outside default sync, restore the chosen snapshot, then sync again.
7. Data included and excluded, especially no handoff documents and no secrets.

- [ ] **Step 5: Run documentation and formatting checks**

```bash
python3 -m unittest tests.test_distribution -v
git diff --check
```

Expected: both commands exit 0.

- [ ] **Step 6: Commit memory documentation**

```bash
git add tests/test_distribution.py SKILL.md adapters/trigger-block.md README.md
git commit -m "Document private cross-project memory"
```

---

### Task 7: Full End-to-End Verification and Review

**Files:**
- Modify only when verification reveals a defect in stage-one or stage-two files.

**Interfaces:**
- Consumes: complete local task and private memory implementation.
- Produces: verified implementation matching all design acceptance criteria.

- [ ] **Step 1: Run the complete unit and integration suite**

In the existing harness-capable test environment, run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all original 78 tests plus local-task and private-memory tests pass with zero failures and errors.

- [ ] **Step 2: Run syntax and shell checks**

```bash
python3 -m py_compile handoff.py handoff_core/*.py hooks/handoff_hook.py
bash -n scripts/install.sh scripts/uninstall.sh scripts/detect-hooks.sh
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 3: Exercise two projects and two devices end to end**

Using temporary directories and a local bare remote:

1. Create tasks in two source repositories.
2. Sync both into separate clones of the same private memory remote.
3. Confirm global `TASKS.md`, `PROJECTS.md`, and daily history include both projects.
4. Modify one project on device A, push, then sync the unchanged project clone on device B and verify download.
5. Modify both sides from the same base and verify `memory_diverged` with byte-identical pre-sync snapshots.
6. Complete one task, sync, and confirm it disappears from global active tasks while remaining in daily history.
7. Run a same-ID active handoff and confirm task completion remains blocked.

- [ ] **Step 4: Run repository review gates**

```bash
git status --short
git log --oneline --decorate -12
git diff 3ebbdce..HEAD --stat
git diff 3ebbdce..HEAD --check
```

Confirm no `.ai/` runtime state, temporary repository, secret fixture value, or unrelated file is tracked.

- [ ] **Step 5: Run code review and simplification passes**

Invoke `/code-review high` for correctness and `/simplify` for reuse and efficiency. Apply only verified findings, rerun the affected focused tests, then rerun the complete suite.

- [ ] **Step 6: Create an integration commit only if review fixes remain uncommitted**

```bash
git add handoff.py handoff_core tests SKILL.md adapters scripts README.md
git commit -m "Complete private project memory sync"
```

Skip this commit when the working tree is clean.
