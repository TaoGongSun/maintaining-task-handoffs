# maintaining-task-handoffs

<p align="center">
  <strong>中文</strong> · <a href="#english">English</a>
</p>

長任務常跨會話，上下文一斷就得重講。這個 skill 讓相容的 coding agent 在**長任務結束或中斷時**，維護一份精簡、預設不進 Git 的交接：

```text
<repo>/.ai/HANDOFF.md
```

**觸發（長任務）**：正式 plan、三步以上、多檔變更、branch/commit、約 10 分鐘以上、或未完成需下一會話接續。  
**不觸發**：純問答、無後續價值的短任務。  
**聊天回應**：只保留交接路徑 + 最後一行的唯一下一步；細節寫在 HANDOFF。

這不是手動「把對話壓成暫存檔」的 `/handoff`，而是**長任務進行中的 checkpoint 契約**。

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

### 本機交接與 Git

預設在 Git **global excludes**（既有 `core.excludesFile`，否則 `$HOME/.config/git/ignore`）各加一次：

```gitignore
.ai/HANDOFF.md
.ai/designs/
.ai/plans/
```

除非你明確要求，否則**不建議**把 HANDOFF 提交進專案。

## 行為摘要

| 情境 | 預期 |
|------|------|
| 長任務完成或暫停 | 更新 `<repo>/.ai/HANDOFF.md` |
| 阻塞／額度／缺權限 | 立刻 checkpoint |
| 短答／瑣事 | 不建立 handoff |
| 寫完交接後的聊天 | 路徑 + 唯一下一步 |

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

Long coding-agent sessions lose continuity. This skill tells compatible agents to keep a **compact, local-only** handoff at:

```text
<repo>/.ai/HANDOFF.md
```

…when work is **long** (formal plan, multi-step, multi-file, branch/commit, ~10+ minutes, or unfinished work for a later session). **Short Q&A does not** create a handoff. After writing it, chat keeps only the path and a **single next action**.

This is **not** a manual “compress this chat into a temp file” command. It is a **checkpoint contract** for long work.

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

### Local-only handoffs (Git)

Install adds these **once** to your Git global excludes (`core.excludesFile`, or creates `$HOME/.config/git/ignore`):

```gitignore
.ai/HANDOFF.md
.ai/designs/
.ai/plans/
```

Do not commit handoffs unless the user explicitly asks.

## Behavior

| Case | Expected |
|------|----------|
| Long task completes or pauses | Update `<repo>/.ai/HANDOFF.md` |
| Blocked / limit / missing authority | Checkpoint immediately |
| Short / trivial task | No handoff file |
| Final chat after handoff | Path + single next action only |

## License

[MIT](./LICENSE)

## Privacy

Do not put secrets, tokens, or personal data in handoff files. The skill instructs agents to omit credentials and unrelated chat.
