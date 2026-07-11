# maintaining-task-handoffs

<p align="center">
  <strong>中文</strong> · <a href="#english">English</a>
</p>

## 這是做什麼的

長任務常跨好幾個對話。上一輪做了什麼、卡在哪、下一步是什麼——若只留在聊天記錄裡，新 session 就要重讀或重講。

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

### B. skill + 可選全域 adapter（建議）

Adapter 是**有起迄標記的短區塊**，只**附加一次**到各平台全域說明檔，**不覆寫**你既有規則。重複執行安裝**不會**插入第二份。

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
.ai/designs/
.ai/plans/
```

進度／交接文件留在磁碟給下一輪讀即可；除非你明確要求，否則**不建議**提交進專案 Git。

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

Long coding tasks often span multiple chat sessions. What was done, what is blocked, and what to do next usually lives only in the conversation—so a fresh session has to re-read or re-explain everything.

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

### B. Skill + optional global adapters (recommended)

Adapters are **small marked blocks** appended **once** to each harness’s global instruction file. They do **not** replace your existing rules. Re-running install will **not** add a second copy.

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
.ai/designs/
.ai/plans/
```

Keep the progress/handoff file on disk for the next session. Do not commit it unless the user explicitly asks.

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
