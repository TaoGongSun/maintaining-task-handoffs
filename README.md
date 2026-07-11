# maintaining-task-handoffs

<p align="center">
  <strong>中文</strong> · <a href="#english">English</a>
</p>

## 這是做什麼的

這個 skill 主要處理一種很常見、也很昂貴的長任務斷點：代理完成一段長時間工作後，使用者因為等太久而離開；等使用者回來時，對話可能早已結束超過五分鐘，原本仍在快取中的內容已被移出。這時才手動呼叫 `/handoff`，模型往往必須重新讀取整份長任務的大量 context，不只慢，也會再次產生成本。

因此，本 skill 會在長任務結束、中斷或必須暫停時，自動建立交接文件。它把握 context 仍在快取中、模型注意力仍集中在當前工作上的時機，產出高品質但精簡的當前狀態，讓下一輪只需讀取一份小文件，不必重新吞下整段長對話。

長任務也常跨好幾個對話。上一輪做了什麼、卡在哪、下一步是什麼——若只留在聊天記錄裡，新 session 就要重讀或重講。

這個 skill 讓相容的 coding agent 在**長任務結束或中斷時**，把**目前進度與接續狀態**寫成一份精簡、預設不進 Git 的本機文件：

```text
<repo>/.ai/HANDOFF.md
```

可以把它想成：

- **進度／狀態文件**（progress / status）：目標、已完成、未完成、驗證結果  
- **會話接續**（session continuity）：給下一個對話或另一個代理接著做  
- **檢查點**（checkpoint）：額度用盡、阻塞、暫停時先落盤，避免進度只存在上下文裡  

檔名用 `HANDOFF` 是因為內容給「下一個代理／下一輪對話」讀，不是給人做週報的長篇進度報告。

**何時會寫入（長任務）**：正式 plan、三個以上實質步驟、多檔變更、branch／commit、約 10 分鐘以上，或留下未完成、需下一會話接續的工作。  
**何時不寫**：純問答、沒有後續價值的短任務。  
**聊天怎麼回**：只保留交接文件路徑，以及最後一行的**唯一下一步**；細節都在 `.ai/HANDOFF.md`。

### 和手動 `/handoff` 類 skill 的差別

| | 本 skill | 常見手動 handoff |
|--|--|--|
| 觸發 | 長任務收尾／中斷時依契約更新 | 使用者下指令才壓縮對話 |
| 產物位置 | 專案內 `.ai/HANDOFF.md`（本機） | 常是暫存目錄或一次性摘要 |
| 用途 | 持續可接續的**當前狀態** | 把整段對話壓短帶走 |

這不是「把聊天貼上再總結一次」，而是長任務的**狀態檢查點契約**。

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

Adapter 是**有起迄標記的短區塊**，只**附加一次**到各平台全域說明檔，**不覆寫**你既有規則。重複執行安裝**不會**插入第二份。

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

解除安裝（移除 skill 與 adapter；不動 Git excludes 與既有 `.ai/HANDOFF.md`）：

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
.ai/handoff-state.json
.ai/handoff-metrics.jsonl
.ai/handoff-hook-errors.jsonl
.ai/handoff-transaction.json
.ai/designs/
.ai/plans/
```

進度／交接文件留在磁碟給下一輪讀即可；除非你明確要求，否則**不建議**提交進專案 Git。

## 半硬式閘門

長任務仍由代理依情境判定。未標記的短任務不建立 state，也不覆寫既有 HANDOFF。一旦標記，`.ai/handoff-state.json` 會保存 task identity，之後必須通過：

```bash
handoff checkpoint --task-id <id> --input <draft.md> --harness claude
handoff validate --task-id <id>
handoff complete --task-id <id> --input <completed-draft.md> --harness claude
```

草稿語意由代理撰寫。Validator 不補寫或改寫內容；草稿上限為 **8 KiB UTF-8**，超過時以 `handoff_too_large` 拒絕，不會截斷。它也檢查結構、task identity、時間、repo／branch／HEAD／dirty state、唯一 Next action 與常見秘密格式。Checkpoint 使用同目錄暫存檔、`fsync` 與原子取代覆寫 `.ai/HANDOFF.md`。

Checkpoint 採事件式寫入：啟用長任務時、compaction 前且既有 checkpoint 已 stale、工作暫停或阻塞時，或完成一個一旦遺失就必須大量重建的里程碑後。一般編輯與測試不會各自觸發 checkpoint。正常收尾直接驗證最新 completed draft，不要求先重寫一份內容重複的 in-progress checkpoint。

Hook 的 state 與 HANDOFF 檢查都是本機 I/O：inactive hook 只讀 state，active `PreCompact` 才在本機驗證 HANDOFF；它不會將 HANDOFF 內容注入模型 context，失敗時只回傳簡短修正指令。

Claude 與支援 hooks 的 Codex 會在 `PreCompact` 阻擋 stale active task，並在 `Stop` 要求 `handoff complete` 成功。Hook 失敗記在 `.ai/handoff-hook-errors.jsonl`；完成嘗試記在 `.ai/handoff-metrics.jsonl`。`handoff compliance` 回報有效數、嘗試數與合規率，不保存 HANDOFF 內容。

若代理被 `Stop` 擋下後仍再次嘗試停止，hook 會以「blocked failure」終止該次續跑，保留 active state 並計入失敗分母，避免無限迴圈；這不算正常完成。

SIGKILL、斷電、宿主崩潰、hook 未啟用或未信任時，無法保證最後 checkpoint。較早的 checkpoint 只能降低損失，不能消除它。

## 行為摘要

| 情境 | 預期 |
|------|------|
| 長任務完成或暫停 | 更新 `<repo>/.ai/HANDOFF.md`（進度與下一步） |
| 阻塞／額度／缺權限 | 立刻寫入 checkpoint |
| 短答／瑣事 | 不建立文件 |
| 寫完後的聊天 | 路徑 + 唯一下一步 |

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

This skill tells compatible coding agents to keep a **compact, local-only progress / status file** when a **long task finishes or is interrupted**:

```text
<repo>/.ai/HANDOFF.md
```

In plain terms it is:

- A **progress / status** snapshot (goal, done, remaining, verification)
- **Session continuity** so the next chat or another agent can resume
- A **checkpoint** when limits, blockers, or pauses would otherwise drop state from context

The filename is `HANDOFF` because the document is for the *next* agent or session, not a long human status report.

**When it writes (long tasks):** formal plan, three or more substantive steps, multi-file work, branch/commit, about 10+ minutes, or unfinished work that another conversation may continue.  
**When it does not:** simple Q&A or short tasks with no continuation value.  
**Chat after writing:** only the file path and a **single next action** on the last line; detail stays in `.ai/HANDOFF.md`.

### How this differs from manual `/handoff` skills

| | This skill | Typical manual handoff |
|--|--|--|
| Trigger | End or interruption of long work | User asks to compress the chat |
| Where | In-repo `.ai/HANDOFF.md` (local-only by default) | Often a temp file or one-off paste |
| Purpose | Current **resumable state** | Carry a shortened transcript elsewhere |

Not “summarize the whole chat again”—a **checkpoint contract** for long work.

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

Adapters are **small marked blocks** appended **once** to each harness’s global instruction file. They do **not** replace your existing rules. Re-running install will **not** add a second copy.

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

Uninstall (skill + adapters; leaves Git excludes and `.ai/HANDOFF.md`):

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
.ai/handoff-state.json
.ai/handoff-metrics.jsonl
.ai/handoff-hook-errors.jsonl
.ai/handoff-transaction.json
.ai/designs/
.ai/plans/
```

Keep the progress/handoff file on disk for the next session. Do not commit it unless the user explicitly asks.

## Semi-hard gates

Long-task classification remains contextual. Unmarked short tasks create no state and do not overwrite an existing handoff. Once marked, `.ai/handoff-state.json` stores the task identity and these gates apply:

```bash
handoff checkpoint --task-id <id> --input <draft.md> --harness codex
handoff validate --task-id <id>
handoff complete --task-id <id> --input <completed-draft.md> --harness codex
```

The agent authors semantic content. The validator never invents or rewrites it. Drafts have an **8 KiB UTF-8** ceiling; larger inputs fail with `handoff_too_large` and are never truncated. It also checks structure, task identity, freshness, repo/branch/HEAD/dirty metadata, one valid Next action, and common secret formats. Checkpoints replace `.ai/HANDOFF.md` atomically with a same-directory temporary file and `fsync`.

Checkpoint writes are event-based: at long-task activation, before compaction when the existing checkpoint is stale, when work pauses or becomes blocked, or after a milestone whose loss would require material reconstruction. Ordinary edits and tests do not independently trigger checkpoints. Normal completion validates the latest completed draft directly and does not require a redundant in-progress checkpoint first.

Hook state and HANDOFF checks are local I/O: an inactive hook reads only state, while an active `PreCompact` validates HANDOFF locally. It does not inject HANDOFF contents into model context; failures return only a short corrective instruction.

Claude and hook-capable Codex block stale active tasks at `PreCompact` and require successful `handoff complete` at `Stop`. Hook failures go to `.ai/handoff-hook-errors.jsonl`; completion attempts go to `.ai/handoff-metrics.jsonl`. `handoff compliance` reports valid count, attempt count, and rate without storing handoff content.

If an agent tries to stop again after `Stop` already continued it, the hook ends that continuation as a blocked failure, preserves active state, and counts the failure. This avoids an infinite loop and is not treated as normal completion.

SIGKILL, power loss, host failure, disabled hooks, or untrusted hooks cannot guarantee a final checkpoint. Earlier checkpoints reduce loss but cannot eliminate it.

## Behavior

| Case | Expected |
|------|----------|
| Long task completes or pauses | Update `<repo>/.ai/HANDOFF.md` (progress + next step) |
| Blocked / limit / missing authority | Checkpoint immediately |
| Short / trivial task | No file |
| Final chat after write | Path + single next action only |

## License

[MIT](./LICENSE)

## Privacy

Do not put secrets, tokens, or personal data in handoff files. The skill instructs agents to omit credentials and unrelated chat.
