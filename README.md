# maintaining-task-handoffs

<p align="center">
  <strong>中文</strong> · <a href="#english">English</a>
</p>

## 這是做什麼的

這個 skill 主要處理一種很常見、也很昂貴的長任務斷點：代理完成一段長時間工作後，使用者因為等太久而離開；等使用者回來時，對話可能早已結束超過五分鐘，原本仍在快取中的內容已被移出。這時才手動呼叫 `/handoff`，模型往往必須重新讀取整份長任務的大量 context，不只慢，也會再次產生成本。

因此，本 skill 會在長任務結束、中斷或必須暫停時，自動建立交接文件。它把握 context 仍在快取中、模型注意力仍集中在當前工作上的時機，產出高品質但精簡的當前狀態，讓下一輪只需讀取一份小文件，不必重新吞下整段長對話。

長任務也常跨好幾個對話。上一輪做了什麼、卡在哪、下一步是什麼——若只留在聊天記錄裡，新 session 就要重讀或重講。

這個 skill 讓相容的 coding agent 在**長任務結束或中斷時**，把**目前進度與接續狀態**寫成精簡、預設不進 Git 的本機文件：

```text
<repo>/.ai/HANDOFF.md
<repo>/.ai/handoffs/<task-id>.md
```

`.ai/HANDOFF.md` 是未完成任務索引；每個任務的完整語意交接位於 `.ai/handoffs/<task-id>.md`。同時只允許一個 active 任務，但可保留多個 paused／blocked 任務。

可以把它想成：

- **進度／狀態文件**（progress / status）：目標、已完成、未完成、驗證結果  
- **會話接續**（session continuity）：給下一個對話或另一個代理接著做  
- **檢查點**（checkpoint）：額度用盡、阻塞、暫停時先落盤，避免進度只存在上下文裡  

檔名用 `HANDOFF` 是因為內容給「下一個代理／下一輪對話」讀，不是給人做週報的長篇進度報告。

**何時會寫入（長任務）**：正式 plan、三個以上實質步驟、多檔變更、branch／commit、約 10 分鐘以上，或留下未完成、需下一會話接續的工作。  
**何時不寫**：純問答、沒有後續價值的短任務。  
**聊天怎麼回**：只保留路徑、精簡狀況，以及最後一行的**唯一具體下一步**。Checkpoint／pause 回報 `.ai/handoffs/<task-id>.md`；complete 因任務文件已刪除，改回報 `.ai/HANDOFF.md` 索引。

### 和手動 `/handoff` 類 skill 的差別

| | 本 skill | 常見手動 handoff |
|--|--|--|
| 觸發 | 長任務收尾／中斷時依契約更新 | 使用者下指令才壓縮對話 |
| 產物位置 | 專案內 `.ai/HANDOFF.md` 索引與 `.ai/handoffs/` 任務文件（本機） | 常是暫存目錄或一次性摘要 |
| 用途 | 持續可接續的**當前狀態** | 把整段對話壓短帶走 |

這不是「把聊天貼上再總結一次」，而是長任務的**狀態檢查點契約**。

### 本機專案待辦

除了長任務 handoff，同一個 repository 也可在 `.ai/` 持久管理**未完成待辦**。待辦與 handoff 使用各自生命週期，可共用 task ID 作為軟連結，但不會互相自動建立或自動完成。

```text
.ai/README.md          # 入口連結
.ai/TASKS.md           # 未完成待辦索引
.ai/tasks/<task-id>.md # 個別待辦語意文件
.ai/history/YYYY-MM-DD.md  # milestone／completed 活動紀錄
.ai/project.json
.ai/task-state.json
```

常用命令：

```bash
handoff task add --task-id <id> --input <draft.md>
handoff task update --task-id <id> --input <draft.md>
handoff task milestone --task-id <id> --input <draft.md> --summary "..."
handoff task complete --task-id <id> --summary "..."
handoff task list
handoff task show --task-id <id>
```

查詢時先讀 `.ai/TASKS.md`；「昨天做了什麼」只讀對應本地日期的 `.ai/history/` 檔。完成項會從活躍索引移除，只在歷史留下一行 milestone 或 completed 摘要。若同 ID handoff 仍為 active／paused／blocked，待辦完成會回報 `handoff_still_open`。預設全部本機、不進產品 Git。

### 跨專案私人記憶（可選）

若要在**所有專案**之間查詢待辦與活動，可自建一個**私人** Git 倉庫（例如本機 bare remote 或你有權限的私人 hosting），clone 到本機後再綁定：

```bash
# 1) 建立／clone 私人記憶庫（使用者自行授權 remote；本工具從不代建公開庫）
git clone <private-memory-url> ~/project-memory

# 2) 在任一產品專案內綁定路徑
handoff memory init --path ~/project-memory

# 3) 手動同步（一次最多一個 commit；有 upstream 才 push）
handoff memory status
handoff memory sync
handoff memory sync --no-push   # 只做本機記憶庫 fast-forward／比對
```

同步生命週期：

1. 記憶庫 worktree 必須乾淨；有 upstream 時先 `fetch`，且只允許 **fast-forward** 目前分支。
2. 以內容雜湊比較本機 snapshot、記憶庫 snapshot 與上次共同 base（`.ai/memory-sync.json`）。
3. 僅單邊變更時整包上傳或下載；雙方相同則 `memory_current` 且不新 commit。
4. **雙邊都有變更**時回報 `memory_diverged` 並停止，不覆蓋任一側，也不自動 force／rebase／merge。
5. 上傳成功但 `push` 失敗時保留有效本機記憶 commit，並標示 remote 尚未同步完成。

手動解衝突：在預設 sync 之外選定一側（還原選定 snapshot 後再 sync），或把其中一邊當成新基準後重新同步。

納入記憶的內容：`project.json`、`task-state.json`、`tasks/`、`history/`；根目錄 `TASKS.md`／`PROJECTS.md`／每日 history 為再生索引。**不複製 handoff** 文件與 registry；**不同步秘密**、token 或無關聊天。私人總集**不是** task 編輯面——專案待辦的 update／complete 仍只在來源 repo 用 `handoff task …`。

跨專案查詢：明確要求「所有專案」時讀記憶庫根 `TASKS.md`；跨專案「昨天」只讀該根 history 對應日檔。一般提示仍優先目前專案的本機 `.ai/`。

---

## 安裝

### A. 只裝 skill

```bash
npx skills add TaoGongSun/maintaining-task-handoffs -g -y
```

或：

```bash
git clone https://github.com/TaoGongSun/maintaining-task-handoffs.git
cd maintaining-task-handoffs
./scripts/install.sh --skill-only
```

### B. skill + CLI、hooks 與全域 adapter（建議）

Adapter 是**有起迄標記的短區塊**，只**附加一次**到各平台全域說明檔，**不覆寫**你既有規則。重複執行安裝會原地更新這個受管理區塊，不會插入第二份，也不會留下舊版規則。

安裝器會先檢查本機 Claude／Codex 是否呈現 hook 能力。可確認時，合併本工具的 hooks 並保留既有 hooks；無法確認時只安裝手動 CLI 閘門並顯示降級訊息。Codex 的非管理 hooks 仍需在 `/hooks` 檢查與信任。

```bash
./scripts/install.sh
```

| 選項 | 效果 |
|------|------|
| `--skill-only` | 只裝 skill + 探索用 symlink |
| `--no-gitignore` | 不改 Git global excludes |
| `--dry-run` | 只列印、不寫入 |

修改設定前會備份到：

```text
$HOME/.agents/backups/maintaining-task-handoffs-<timestamp>/
```

解除安裝（移除 skill 與 adapter；不動 Git excludes 與既有 `.ai/` 交接文件）：

```bash
./scripts/uninstall.sh
```

### 各平台入口

| 代理 | Skill 探索 | 可選 adapter 檔 |
|------|------------|-----------------|
| **Codex** | `$HOME/.agents/skills/` | `$HOME/.codex/AGENTS.md` |
| **Claude Code** | `$HOME/.claude/skills/`（symlink） | `$HOME/.claude/Claude.md` |
| **Grok Build** | `$HOME/.grok/skills/`（symlink）；常兼載 Claude 相容全域規則 | `$HOME/.claude/Claude.md` |
| **Gemini / agy** | 依平台 skill 路徑 | `$HOME/.gemini/GEMINI.md` |

共用區塊見 `adapters/trigger-block.md`。

### 本機文件與 Git

預設在 Git **global excludes**（既有 `core.excludesFile`，否則 `$HOME/.config/git/ignore`）各加一次：

```gitignore
.ai/HANDOFF.md
.ai/handoffs/
.ai/handoff-state.json
.ai/handoff-metrics.jsonl
.ai/handoff-hook-errors.jsonl
.ai/handoff-transaction.json
.ai/designs/
.ai/plans/
.ai/README.md
.ai/TASKS.md
.ai/tasks/
.ai/history/
.ai/project.json
.ai/task-state.json
.ai/task-transaction.json
.ai/memory-sync.json
```

進度／交接文件留在磁碟給下一輪讀即可；除非你明確要求，否則**不建議**提交進專案 Git。

## 半硬式閘門

長任務仍由代理依情境判定。未標記的短任務不建立 state，也不改寫索引或任務文件。一旦標記，`.ai/handoff-state.json` 會保存明確的 task registry，之後必須通過：

```bash
handoff checkpoint --task-id <id> --input <draft.md> --harness claude
handoff pause --task-id <id> --input <draft.md> --harness claude
handoff validate --task-id <id>
handoff complete --task-id <id> --input <completed-draft.md> --harness claude
```

`handoff pause` 表示這一輪已安全收尾，但任務的整體 Goal 仍有後續工作；它接受 `in-progress` 或 `blocked`，保留任務文件與具體 Next action，也不封存計畫。`handoff complete` 只用於整體 Goal 確實完成的情況；完成後會刪除該任務文件及索引項目，但保留其他 paused／blocked 任務。兩者都會解除當前 active lifecycle，之後可用同一 task id 再次 checkpoint 來接續 paused 工作。

草稿語意由代理撰寫。Validator 不補寫或改寫內容；草稿上限為 **8 KiB UTF-8**，超過時以 `handoff_too_large` 拒絕，不會截斷。它也檢查結構、task identity、時間、repo／branch／HEAD／dirty state、唯一 Next action 與常見秘密格式。Checkpoint 以可復原 transaction 更新對應任務文件、registry 與 `.ai/HANDOFF.md` 索引；不掃描 `.ai/handoffs/` 推測任務歸屬。

若當前任務有計畫文件，可在草稿加入可選的 `## Plan files`，以 Markdown bullet 明列該任務擁有的 repo-relative paths。`handoff pause` 保留所有計畫；`handoff complete` 只封存這份 HANDOFF 明列的計畫，絕不掃描目錄或整理未列出的文件。一般計畫移至同目錄的 `archive/<year>/`；`.ai/plans/` 下的計畫移至 `.ai/archive/plans/<year>/`。來源或目的地不安全、遺失、重複、已封存或發生衝突時，completion 會失敗且不搬任何計畫；completion 狀態寫入失敗時也會回復已搬移的文件。Checkpoint、paused、blocked 與未完成狀態不會觸發封存。

Checkpoint 採事件式寫入：啟用長任務時、compaction 前且既有 checkpoint 已 stale、工作暫停或阻塞時，或完成一個一旦遺失就必須大量重建的里程碑後。一般編輯與測試不會各自觸發 checkpoint。正常收尾直接驗證最新 completed draft，不要求先重寫一份內容重複的 in-progress checkpoint。

Hook 的 state 與 HANDOFF 檢查都是本機 I/O：inactive hook 只讀 registry，active `PreCompact` 才在本機驗證 active 任務文件；它不會將 HANDOFF 內容注入模型 context，失敗時只回傳簡短修正指令。

Claude 與支援 hooks 的 Codex 會在 `PreCompact` 阻擋 stale active task，並在 `Stop` 依 Goal 狀態要求成功執行 `handoff pause` 或 `handoff complete`。Hook 失敗記在 `.ai/handoff-hook-errors.jsonl`；完成嘗試記在 `.ai/handoff-metrics.jsonl`。`handoff compliance` 回報有效數、嘗試數與合規率，不保存 HANDOFF 內容。

若代理被 `Stop` 擋下後仍再次嘗試停止，hook 會以「blocked failure」終止該次續跑，保留 active state 並計入失敗分母，避免無限迴圈；這不算正常完成。

SIGKILL、斷電、宿主崩潰、hook 未啟用或未信任時，無法保證最後 checkpoint。較早的 checkpoint 只能降低損失，不能消除它。

## 行為摘要

| 情境 | 預期 |
|------|------|
| 當前階段收尾、Goal 未完成 | `handoff pause`，保留進度與具體下一步 |
| 整體 Goal 完成 | `handoff complete`；刪除該任務文件與索引項目，且只有此時可封存明列計畫 |
| 完成且有 `## Plan files` | 只封存明列計畫；失敗則阻止 completion |
| 阻塞／額度／缺權限 | 立刻寫入 checkpoint |
| 短答／瑣事 | 不建立文件 |
| 寫完後的聊天 | 路徑 + 精簡狀況 + 唯一具體下一步 |

## 授權

[MIT](./LICENSE)

## 隱私

請勿把密鑰、token、個資寫進 HANDOFF。Skill 指示代理略過憑證與無關聊天。

---

<a id="english"></a>

# maintaining-task-handoffs (English)

<p align="center">
  <a href="#">中文</a> · <strong>English</strong>
</p>

## What this is for

This skill primarily addresses a common and expensive failure point in long tasks: after an agent finishes a lengthy stretch of work, the user leaves because the wait was long. By the time they return, the conversation may have been idle for more than five minutes and its context may no longer be cached. Calling `/handoff` only then can force the model to read the long task's full context again, adding both latency and cost.

To avoid that late reconstruction, this skill automatically creates a handoff when a long task ends, is interrupted, or must pause. It captures the state while the context is still cached and the model's attention is focused on the work, producing a high-quality but compact document. The next session reads that small handoff instead of loading the entire conversation again.

Long coding tasks also often span multiple chat sessions. What was done, what is blocked, and what to do next usually lives only in the conversation—so a fresh session has to re-read or re-explain everything.

This skill tells compatible coding agents to keep **compact, local-only progress / status files** when a **long task finishes or is interrupted**:

```text
<repo>/.ai/HANDOFF.md
<repo>/.ai/handoffs/<task-id>.md
```

`.ai/HANDOFF.md` is the unfinished-task index; each full semantic handoff lives at `.ai/handoffs/<task-id>.md`. Only one task may be active, while multiple paused or blocked tasks may remain.

In plain terms it is:

- A **progress / status** snapshot (goal, done, remaining, verification)
- **Session continuity** so the next chat or another agent can resume
- A **checkpoint** when limits, blockers, or pauses would otherwise drop state from context

The filename is `HANDOFF` because the document is for the *next* agent or session, not a long human status report.

**When it writes (long tasks):** formal plan, three or more substantive steps, multi-file work, branch/commit, about 10+ minutes, or unfinished work that another conversation may continue.  
**When it does not:** simple Q&A or short tasks with no continuation value.  
**Chat after writing:** only a path, concise status, and a **single concrete next action** on the last line. Checkpoint/pause reports `.ai/handoffs/<task-id>.md`; completion reports the `.ai/HANDOFF.md` index because the completed task document has been removed.

### How this differs from manual `/handoff` skills

| | This skill | Typical manual handoff |
|--|--|--|
| Trigger | End or interruption of long work | User asks to compress the chat |
| Where | In-repo `.ai/HANDOFF.md` index and `.ai/handoffs/` task documents | Often a temp file or one-off paste |
| Purpose | Current **resumable state** | Carry a shortened transcript elsewhere |

Not “summarize the whole chat again”—a **checkpoint contract** for long work.

### Local project tasks

Besides long-task handoffs, each repository can also keep **unfinished local project tasks** under `.ai/`. Tasks and handoffs have separate lifecycles; they may share a task ID as a soft link, but neither auto-creates nor auto-completes the other.

```text
.ai/README.md          # entry links
.ai/TASKS.md           # unfinished-task index
.ai/tasks/<task-id>.md # per-task semantic document
.ai/history/YYYY-MM-DD.md  # milestone / completed activity
.ai/project.json
.ai/task-state.json
```

Common commands:

```bash
handoff task add --task-id <id> --input <draft.md>
handoff task update --task-id <id> --input <draft.md>
handoff task milestone --task-id <id> --input <draft.md> --summary "..."
handoff task complete --task-id <id> --summary "..."
handoff task list
handoff task show --task-id <id>
```

Queries start at `.ai/TASKS.md`; “what did I do yesterday?” reads only the local-date file under `.ai/history/`. Completed work leaves the active index and remains as one-line milestone or completed history. A same-ID handoff that is still active, paused, or blocked blocks task completion with `handoff_still_open`. Default is local-only and excluded from product Git.

### Optional private cross-project memory

To query tasks and activity across **all projects**, create a **private** Git repository yourself (local bare remote or private hosting you authorize), clone it, then bind:

```bash
# 1) Create/clone a private memory repo (this tool never creates a public remote)
git clone <private-memory-url> ~/project-memory

# 2) Bind from any product repository
handoff memory init --path ~/project-memory

# 3) Manual sync (at most one commit per run; push only when upstream exists)
handoff memory status
handoff memory sync
handoff memory sync --no-push   # local memory fast-forward / compare only
```

Sync lifecycle:

1. Memory worktree must be clean; with upstream, `fetch` first and only **fast-forward** the current branch.
2. Compare content hashes for local snapshot, memory snapshot, and last shared base (`.ai/memory-sync.json`).
3. Upload or download a full validated snapshot when only one side changed; identical sides return `memory_current` with no new commit.
4. When **both sides changed**, return `memory_diverged` and stop without overwriting either side—never force, rebase, or merge task content.
5. A failed push keeps the valid local memory commit and reports that remote synchronization is incomplete.

Manual resolution: choose one side outside default sync, restore the chosen snapshot, then sync again.

Included: `project.json`, `task-state.json`, `tasks/`, `history/`; root `TASKS.md` / `PROJECTS.md` / daily history are regenerated. The memory repo **does not copy handoff** documents and must not carry secrets. It is not a task editing surface—mutate project tasks only in the source repo via `handoff task …`.

Cross-project queries: explicit “all projects” reads the private memory root `TASKS.md`; cross-project day queries read only that root history file. Ordinary prompts still prefer the current project’s local `.ai/`.

## Install

### A. Skill only

```bash
npx skills add TaoGongSun/maintaining-task-handoffs -g -y
```

Or:

```bash
git clone https://github.com/TaoGongSun/maintaining-task-handoffs.git
cd maintaining-task-handoffs
./scripts/install.sh --skill-only
```

### B. Skill + CLI, hooks, and global adapters (recommended)

Adapters are **small marked blocks** appended **once** to each harness’s global instruction file. They do **not** replace your existing rules. Re-running install updates the managed block in place; it neither adds a second copy nor leaves stale rules behind.

The installer checks whether local Claude and Codex commands expose hook capability. When detected, it merges these hooks while preserving unrelated hooks. Otherwise it installs manual CLI gates and reports degraded enforcement. Non-managed Codex hooks still require review and trust through `/hooks`.

```bash
./scripts/install.sh
```

| Flag | Effect |
|------|--------|
| `--skill-only` | Skill + discovery symlinks only |
| `--no-gitignore` | Skip Git global excludes |
| `--dry-run` | Print actions only |

Backups:

```text
$HOME/.agents/backups/maintaining-task-handoffs-<timestamp>/
```

Uninstall (skill + adapters; leaves Git excludes and existing `.ai/` handoff files):

```bash
./scripts/uninstall.sh
```

### Platform entry points

| Agent | Skill discovery | Optional adapter file |
|-------|-----------------|------------------------|
| **Codex** | `$HOME/.agents/skills/` | `$HOME/.codex/AGENTS.md` |
| **Claude Code** | `$HOME/.claude/skills/` (symlink) | `$HOME/.claude/Claude.md` |
| **Grok Build** | `$HOME/.grok/skills/` (symlink); often also loads Claude-compatible globals | `$HOME/.claude/Claude.md` |
| **Gemini / agy** | Per-platform skills path | `$HOME/.gemini/GEMINI.md` |

Shared block: `adapters/trigger-block.md`.

### Local files and Git

Install adds these **once** to your Git global excludes (`core.excludesFile`, or creates `$HOME/.config/git/ignore`):

```gitignore
.ai/HANDOFF.md
.ai/handoffs/
.ai/handoff-state.json
.ai/handoff-metrics.jsonl
.ai/handoff-hook-errors.jsonl
.ai/handoff-transaction.json
.ai/designs/
.ai/plans/
.ai/README.md
.ai/TASKS.md
.ai/tasks/
.ai/history/
.ai/project.json
.ai/task-state.json
.ai/task-transaction.json
.ai/memory-sync.json
```

Keep the progress/handoff file on disk for the next session. Do not commit it unless the user explicitly asks.

## Semi-hard gates

Long-task classification remains contextual. Unmarked short tasks create no state and do not alter the index or task documents. Once marked, `.ai/handoff-state.json` stores an explicit task registry and these gates apply:

```bash
handoff checkpoint --task-id <id> --input <draft.md> --harness codex
handoff pause --task-id <id> --input <draft.md> --harness codex
handoff validate --task-id <id>
handoff complete --task-id <id> --input <completed-draft.md> --harness codex
```

`handoff pause` safely ends the current run while the task's overall Goal still has remaining work. It accepts `in-progress` or `blocked`, preserves the task document and a concrete Next action, and never archives plans. `handoff complete` is reserved for a genuinely completed Goal. Completion deletes that task document and index entry while preserving unrelated paused or blocked tasks. Both release the active lifecycle; a later checkpoint with the same task id resumes paused work.

The agent authors semantic content. The validator never invents or rewrites it. Drafts have an **8 KiB UTF-8** ceiling; larger inputs fail with `handoff_too_large` and are never truncated. It also checks structure, task identity, freshness, repo/branch/HEAD/dirty metadata, one valid Next action, and common secret formats. Checkpoints use a recoverable transaction to update the target task document, registry, and `.ai/HANDOFF.md` index; ownership is never inferred by scanning `.ai/handoffs/`.

When the current task owns plan documents, the draft may include an optional `## Plan files` section containing their repo-relative paths as Markdown bullets. `handoff pause` preserves every plan; `handoff complete` archives only plans explicitly listed in that HANDOFF and never scans directories or cleans up unlisted documents. General plans move to a sibling `archive/<year>/`, while plans under `.ai/plans/` move to `.ai/archive/plans/<year>/`. Unsafe, missing, duplicate, already archived, or conflicting paths block completion before any plan moves. Multi-file archival is all-or-nothing, and moved plans are restored if writing completed state fails. Checkpoint, paused, blocked, and unfinished states never archive plans.

Checkpoint writes are event-based: at long-task activation, before compaction when the existing checkpoint is stale, when work pauses or becomes blocked, or after a milestone whose loss would require material reconstruction. Ordinary edits and tests do not independently trigger checkpoints. Normal completion validates the latest completed draft directly and does not require a redundant in-progress checkpoint first.

Hook state and HANDOFF checks are local I/O: an inactive hook reads only the registry, while an active `PreCompact` validates the active task document locally. It does not inject HANDOFF contents into model context; failures return only a short corrective instruction.

Claude and hook-capable Codex block stale active tasks at `PreCompact` and require either `handoff pause` or `handoff complete` at `Stop`, according to the Goal state. Hook failures go to `.ai/handoff-hook-errors.jsonl`; completion attempts go to `.ai/handoff-metrics.jsonl`. `handoff compliance` reports valid count, attempt count, and rate without storing handoff content.

If an agent tries to stop again after `Stop` already continued it, the hook ends that continuation as a blocked failure, preserves active state, and counts the failure. This avoids an infinite loop and is not treated as normal completion.

SIGKILL, power loss, host failure, disabled hooks, or untrusted hooks cannot guarantee a final checkpoint. Earlier checkpoints reduce loss but cannot eliminate it.

## Behavior

| Case | Expected |
|------|----------|
| Current run ends, Goal unfinished | `handoff pause`; preserve progress and concrete next action |
| Overall Goal completed | `handoff complete`; delete that task document and index entry, and only then archive listed plans |
| Completion with `## Plan files` | Archive only listed plans; archival failure blocks completion |
| Blocked / limit / missing authority | Checkpoint immediately |
| Short / trivial task | No file |
| Final chat after write | Path + concise status + single concrete next action |

## License

[MIT](./LICENSE)

## Privacy

Do not put secrets, tokens, or personal data in handoff files. The skill instructs agents to omit credentials and unrelated chat.
