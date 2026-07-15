# 專案待辦記憶與跨專案總集設計

日期：2026-07-15

## 摘要

將 `maintaining-task-handoffs` 擴充成三個相互連結、責任分明的本機記憶層：

1. **專案待辦**記錄每個 repository 尚未完成的工作。
2. **長任務 handoff**保留既有跨 session 接續契約。
3. **私人 Git 總集**同步各專案的待辦與活動歷史，提供跨專案查詢。

待辦與 handoff 不共用同一份語意文件。它們共用安全的檔案操作能力，但維持各自的生命週期。完成項會從活躍待辦移除，只在按日期分片的歷史中留下精簡結果，兼顧「自動清除」與「昨天做了什麼」。

第一版採單一寫入介面的雙向檔案同步：待辦只能透過所屬專案的 task service 修改；私人總集不直接編輯任務，但可將另一台裝置已同步的較新專案快照安全帶回目前專案。若目前專案與總集自共同版本後都已變更，系統停止並要求人工選擇，不做自動 merge。

## 目標

- 每個 Git repository 擁有自己的待辦事項。
- 使用者以自然語言詢問時，代理能以最少讀取量回答目前專案或全部專案的狀況。
- 完成項不再出現在未完成索引，但仍能回答近期完成紀錄。
- 入口檔只保留用途說明與連結，不載入全部任務內容。
- 私人 Git repository 同時提供跨裝置同步與跨專案總覽。
- 延用現有的秘密掃描、路徑驗證、原子寫入與 transaction rollback 原則。
- 保持既有 handoff CLI、文件格式、hooks 與生命週期語意相容。

## 非目標

第一版不包含：

- 直接在私人總集內新增、更新或完成各專案待辦；跨裝置取回完整快照不在此限制內。
- 自動排程同步或背景 daemon。
- 通知、行事曆或期限提醒。
- 自動排定優先級。
- 全文搜尋引擎或資料庫。
- 依 commit、乾淨工作樹或久未更新自動判定任務完成。
- 同步秘密、token、個資或不必要的客戶敏感內容。
- 將 `.ai/` 待辦直接提交到原專案的產品歷史。

## 設計原則

### 領域分離

一般待辦回答「還要做什麼」，handoff 回答「下一輪如何接著做」。一個待辦可以在沒有 active handoff 的情況下存在；active handoff 可用 task ID 連回待辦，但不要求每個待辦都建立 handoff。

### 單一真實來源

- 專案內的個別待辦文件是待辦內容的真實來源。
- 專案 `TASKS.md` 是由待辦文件產生的索引。
- 私人總集內的專案副本是最近一次同步的快照；它可以成為另一台裝置專案端的安全還原來源，但不可直接編輯。
- 私人總集根目錄的 `TASKS.md`、`PROJECTS.md` 與每日歷史是由專案快照產生的聚合檢視。
- 自動產生的索引不得手動編輯。

### 漸進式讀取

代理先讀極短入口，再依問題只讀必要索引或單一任務文件。列出待辦不應需要打開所有任務文件；索引必須包含足以回答概況的一行摘要與下一步。

### 安全完成

只有使用者明確標示完成，或代理已完成整體目標且具有驗證證據時，才能執行完成操作。完成、歷史寫入與索引重建必須是同一筆可回復 transaction。

## 本機專案儲存配置

```text
<repo>/.ai/
├── README.md
├── TASKS.md
├── tasks/
│   └── <task-id>.md
├── history/
│   └── YYYY-MM-DD.md
├── project.json
├── task-state.json
├── memory-sync.json
├── HANDOFF.md
├── handoffs/
│   └── <task-id>.md
└── handoff-state.json
```

既有 handoff 檔案維持原名與格式。新增檔案繼續留在本機，並加入安裝器管理的 Git global excludes。

### `.ai/README.md`

固定且極短的入口，例如：

```markdown
# Project memory

- [未完成待辦](TASKS.md)
- [長任務交接](HANDOFF.md)
- [每日活動紀錄](history/)
```

它只說明去哪裡讀，不複製狀態。

### `.ai/project.json`

保存穩定專案身分：

```json
{
  "version": 1,
  "id": "github.com-taogongsun-maintaining-task-handoffs",
  "name": "maintaining-task-handoffs",
  "remote": "https://github.com/TaoGongSun/maintaining-task-handoffs.git"
}
```

專案 ID 的建立規則：

1. 優先正規化 `remote.origin.url` 的 host、owner 與 repository 名稱。
2. 相同 repository 的 SSH 與 HTTPS URL 必須得到相同 ID。
3. 沒有 remote 時建立持久 UUID，後續不得因資料夾搬移而改變。
4. 若偵測到不同專案產生同一 ID，同步必須停止並要求人工修正，不得覆寫。

### `.ai/task-state.json`

只保存機器需要的 registry，不重複保存完整任務內容：

```json
{
  "version": 1,
  "tasks": {
    "project-todo-memory": {
      "status": "in-progress",
      "created": "2026-07-15T09:00:00+08:00",
      "updated": "2026-07-15T10:30:00+08:00"
    }
  }
}
```

狀態只有：

- `todo`
- `in-progress`
- `blocked`

完成不是持久狀態。完成後任務會從 registry 與活躍文件移除，並寫入歷史。

### `.ai/memory-sync.json`

保存目前專案與私人總集最近一次共同版本的內容雜湊及中央 commit。內容雜湊只涵蓋正規化後的 `project.json`、`task-state.json`、`tasks/` 與 `history/`，不含自動產生的索引、同步 metadata 或檔案時間。這個 base hash 讓不同裝置能判斷哪一側有新變更，不依賴可能漂移的系統時鐘。

### `.ai/tasks/<task-id>.md`

第一版格式：

```markdown
# Task
Task-ID: project-todo-memory
Title: 建立專案待辦記憶
Status: in-progress
Created: 2026-07-15T09:00:00+08:00
Updated: 2026-07-15T10:30:00+08:00

## Summary
讓每個專案保有精簡、可查詢的未完成工作。

## Progress
- 已選定獨立待辦層。

## Next action
撰寫實作計畫。

## Constraints
- 不改變 handoff lifecycle。
```

規則：

- `Task-ID` 沿用現有安全字元限制。
- `Title`、`Summary` 與 `Next action` 必須是非 placeholder 內容。
- `Next action` 必須只有一個具體動作。
- `Progress` 與 `Constraints` 可省略；其餘語意欄位必填。
- `Created` 與 `Updated` 由 service 依設定時區寫入；代理提交的 semantic draft 不含也不能覆寫這兩個欄位。
- 文件沿用大小上限與秘密掃描。
- 待辦可連結同 ID handoff，但不能嵌入或複製完整 handoff。

### `.ai/TASKS.md`

由 registry 與任務文件自動產生：

```markdown
# Project tasks

## In progress
- [project-todo-memory](tasks/project-todo-memory.md) — 建立專案待辦記憶 — 下一步：撰寫實作計畫

## Todo
- None.

## Blocked
- [publish-v2](tasks/publish-v2.md) — 發布第二版 — 阻塞：等待套件權限
```

索引只列未完成項目，固定依 `in-progress`、`todo`、`blocked` 分組；各組內依 `updated` 新到舊、再依 task ID 排序，確保產出穩定。

## 活動歷史

### 事件範圍

為使「昨天做了什麼」不只等於「昨天完成了什麼」，歷史記錄兩類高訊號事件：

- `completed`：整體待辦完成。
- `milestone`：重要進度或阻塞變更，且其遺失會讓後續狀況報告明顯失真。

一般文字微調、每次 checkpoint、測試重跑與同步本身不寫入活動歷史，避免噪音。`milestone` 由代理在更新待辦時明確提供一行摘要；系統不從 Git diff 自動猜測。

### 日期與格式

檔名依使用者設定的 IANA 時區決定本地日期；預設取系統本地時區。事件時間保留 UTC offset：

```markdown
# Activity for 2026-07-15

- 10:30 +08:00 — `milestone` — `maintaining-task-handoffs/project-todo-memory`：選定獨立待辦層與私人 Git 聚合架構。
- 16:42 +08:00 — `completed` — `maintaining-task-handoffs/improve-hooks`：保留既有 hooks 並補上安裝回歸測試。
```

每日歷史按事件時間排序。Markdown 顯示本地時間，但每筆事件另以穩定、可解析的 HTML comment 保存完整 ISO 8601 timestamp；聚合及衝突判定不得解析顯示文字。事件 identity 是 `project ID + task ID + 類型 + 完整 timestamp`。事件至少包含時間、類型、project ID、task ID 與一行摘要。摘要必須通過秘密掃描。

### 保存政策

活躍待辦完成後，完整任務文件不保留；每日歷史只留下可閱讀的一行結果。歷史按日期分片，因此查「昨天」只需讀一個檔案。Git repository 仍會保存歷史版本，故「清除」定義為從目前活躍資料與索引移除，不是從 Git 物件永久抹除。

若未來需要真正消除敏感資料，必須另走 Git 歷史重寫流程；因此寫入前的秘密掃描是必要邊界。

## 待辦操作

CLI 使用獨立 `task` 命令群組，避免改變現有 handoff 命令：

```text
handoff task add
handoff task update
handoff task milestone
handoff task complete
handoff task list
handoff task show
```

具體輸入可沿用目前的 `--input <draft>` 模式，讓代理撰寫語意、CLI 驗證與保存，不由 CLI 生成任務內容。

### 新增

1. 驗證 task ID、文件格式、時間與秘密。
2. 確認 task ID 不存在。
3. transaction 寫入任務文件、registry 與重建後索引。

### 更新

1. 驗證目標存在。
2. 更新狀態、摘要、進度或下一步。
3. 保留原 `Created`，重設 `Updated`。
4. transaction 更新任務文件、registry 與索引。
5. 若呼叫端明確提供 milestone 摘要，同一 transaction 寫入當日日誌。

### 完成

1. 驗證目標存在且完成摘要非空。
2. 建立 `completed` 歷史事件。
3. 從 registry 移除任務。
4. 刪除活躍任務文件。
5. 重建 `TASKS.md`。
6. 將上述變更放在同一筆 transaction；任何失敗均回復全部檔案。

完成操作不得自動完成或刪除同 ID handoff。若該 handoff 仍 active、paused 或 blocked，CLI 應拒絕完成待辦並回報 `handoff_still_open`。代理必須先依既有契約 pause 或 complete handoff，再完成待辦，避免總覽宣稱完成但交接仍顯示未完成。

## 自然語言查詢契約

由 skill 與各平台 managed adapter 定義查詢範圍，不建立自然語言 parser。

| 使用者語意 | 讀取來源 | 行為 |
|---|---|---|
| 「現在還有什麼沒做？」、「待辦事項」 | 目前 repo `.ai/TASKS.md` | 依狀態列出目前專案待辦 |
| 「所有專案還有什麼沒做？」 | 私人總集 `TASKS.md` | 依專案與狀態摘要 |
| 「那個 hooks 項目現在狀況是？」 | 先讀索引，再讀命中的任務文件 | 回答摘要、進度、阻塞與下一步 |
| 「昨天做了什麼？」 | 目前 repo 昨日 history | 回答目前專案 milestone 與 completed 事件 |
| 「我昨天做了什麼？」、「昨天所有專案做了什麼？」 | 私人總集昨日 history | 回答跨專案事件 |
| 「這項完成了」 | 目前 repo task completion | 驗證後移除活躍項並寫入歷史 |

模糊名稱比對依序使用精確 task ID、精確標題、標題子字串。若同一層級命中多項，代理列出候選並停止，不自行猜測。

若目前目錄不是 Git repository，專案範圍查詢應回報無法判定目前專案；若已設定私人總集，仍可執行明確的跨專案查詢。

## 私人 Git 總集

### 定位

私人總集是：

- 各專案待辦與活動歷史的同步快照。
- 所有未完成工作的跨專案索引。
- 跨專案日期活動總覽。

它不是待辦的編輯端；所有語意修改仍透過專案端 task service 驗證。同步可在雜湊證明只有總集一側變更時，把整份快照帶回專案。

### 配置

使用者設定總集本機路徑，例如：

```text
~/project-memory
```

該目錄本身是獨立的私人 Git repository，remote 由使用者自行建立並授權。工具不得假設 GitHub，也不得自動建立公開 repository。

```text
project-memory/
├── README.md
├── TASKS.md
├── PROJECTS.md
├── registry.json
├── history/
│   └── YYYY-MM-DD.md
└── projects/
    └── <project-id>/
        ├── project.json
        ├── task-state.json
        ├── TASKS.md
        ├── tasks/
        └── history/
```

私人總集不複製 handoff 文件。handoff 包含當前工作樹、branch、HEAD 與接續脈絡，適合留在原 repository 本機；跨專案總覽只聚合待辦與活動歷史。

### 同步命令

```text
handoff memory init --path <path>
handoff memory status
handoff memory sync
```

`memory init` 驗證目標為 Git repository、保存本機配置並建立必要入口。它不建立 remote、不推送，也不修改原專案 Git 設定。

`memory sync` 每次只處理目前專案，但支援在不同裝置間安全地上傳或取回該專案快照：

1. 驗證目前專案身分、私人總集設定，以及專案 `.ai/` 中沒有未完成的 task transaction。
2. 確認私人總集工作樹乾淨；不覆蓋未提交變更。
3. 若有 remote，執行 `git fetch`，並要求目前 branch 可 fast-forward 到 upstream；否則停止。私人總集尚未存在未提交修改，因此允許 fast-forward 更新目前 branch。
4. 重新確認私人總集工作樹乾淨，計算目前專案 `local hash`、總集快照 `memory hash`，並讀取 `.ai/memory-sync.json` 的 `base hash`。
5. 依三方比較決定方向：
   - `local == memory`：無內容需要傳輸，只更新必要的同步 metadata。
   - `memory == base` 且 `local != base`：只有專案端改變，準備上傳本機快照。
   - `local == base` 且 `memory != base`：只有總集改變，準備取回總集快照。
   - `local != base` 且 `memory != base` 且兩者不同：回報 `memory_diverged` 並停止。
   - 尚無 base 且總集沒有此 project ID：視為首次上傳；尚無 base 但兩側都有不同內容時停止。
6. 上傳時，在私人總集內建立不受 Git 追蹤的 staging 目錄，放入目前專案的 `project.json`、`task-state.json`、`tasks/` 與 `history/`；取回時，在目前專案內建立 staging 目錄並載入總集快照。
7. 驗證 staging 快照、registry、任務文件、歷史與秘密掃描全部一致。取回時由本機 service 重建 `.ai/README.md` 與 `.ai/TASKS.md`，不得直接信任總集中的產生檔。
8. 上傳時在 staging 中重建完整根 `TASKS.md`、`PROJECTS.md` 與全部日期聚合歷史；取回不修改其他 project snapshot。
9. 將所有預定內容寫入可復原 transaction manifest，再依序替換目標檔案；本機 I/O 失敗時依 manifest 回復。
10. 上傳若產生總集差異，建立一筆批次 commit；預設訊息為 `Sync project memory for YYYY-MM-DD`。取回不建立總集 commit。
11. 上傳且使用者已配置 remote 時才 push；push 失敗保留本機 commit並回報，不宣稱遠端同步完成。
12. 傳輸成功後，將共同內容雜湊與總集 commit 寫入 `.ai/memory-sync.json`。若上傳 push 失敗，base hash 仍指向本機總集 commit，下一次可繼續推送，不重複建立內容 commit。

CLI 不使用 force pull、force push、自動 rebase 或自動解決內容衝突。

### 全域索引

根 `TASKS.md` 依狀態、專案名稱與 task 更新時間產生，保留每項一行摘要與來源連結。`PROJECTS.md` 列出 project ID、顯示名稱、最近同步時間及專案索引連結。

根 `history/YYYY-MM-DD.md` 合併各專案同日事件，以完整 timestamp 排序。聚合時使用已定義的事件 identity 去重；同一 identity 內容不同視為資料衝突並停止重建，不靜默覆蓋。

### 多裝置與衝突

兩台裝置仍可能在同一次共同版本後各自修改同一專案。處理原則：

- sync 前必須 fetch，且只允許 fast-forward 更新私人總集目前 branch。
- 遠端若無法 fast-forward，停止並保留兩邊資料。
- project snapshot 不做欄位層級自動 merge。
- `.ai/memory-sync.json` 的 base hash 與兩側目前內容雜湊構成三方比較，不以牆鐘時間判斷勝負。
- 只有一側改變時，自動將完整快照複製到另一側；兩側皆改變且內容不同時回報 `memory_diverged`。
- 使用者處理分歧時必須明確選擇保留專案端或總集端快照；工具可在後續實作提供顯式 `--prefer-local`／`--prefer-memory`，但預設 sync 絕不自行選擇。
- 工具不自動 rebase、建立 merge commit或逐欄位合併。

這個限制換取可預測、跨裝置可用且不靜默遺失資料的同步流程。

## 與 handoff 的整合

- 既有 `checkpoint`、`pause`、`validate`、`complete` 與 `compliance` 行為不變。
- 待辦與 handoff 可使用相同 task ID，作為軟連結。
- handoff checkpoint 不自動建立待辦，避免所有長任務都污染個人待辦。
- 代理若在處理既有待辦時啟用長任務 handoff，應沿用該 task ID。
- handoff complete 不自動完成待辦；代理必須依待辦 Goal 是否真的完成，另執行 task completion 或 task update。
- 待辦完成前檢查同 ID handoff 是否仍開啟，以防生命週期矛盾。

## 錯誤處理與資料安全

新增結構化錯誤碼，至少包含：

- `task_exists`
- `task_missing`
- `invalid_task`
- `handoff_still_open`
- `memory_not_configured`
- `memory_dirty`
- `memory_not_git_repo`
- `project_id_conflict`
- `memory_diverged`
- `pull_not_fast_forward`
- `history_conflict`
- `push_failed`

所有寫入先在記憶體或 staging 路徑完成驗證，再以 transaction 套用。錯誤輸出不得回顯秘密。同步前後都要驗證 symlink 與路徑不得逃出專案或私人總集根目錄。

私人 Git repository 必須在文件中標示為 private-only，但工具仍不能把「private」視為秘密儲存保證。秘密掃描涵蓋任務文件、完成摘要、milestone 與聚合歷史。

## 測試策略

### 文件與 parser

- 接受最小合法待辦。
- 拒絕缺欄位、placeholder、重複 task ID、多行 Next action、超大文件與秘密。
- 驗證時區與日期分片。
- 驗證 SSH／HTTPS remote 產生相同 project ID。
- 無 remote 的 UUID 在路徑搬移後保持不變。

### 服務與 transaction

- 新增、更新、milestone、完成會同步更新文件、registry、索引與歷史。
- 任一步驟 I/O 失敗均回復先前狀態。
- 完成只移除目標任務。
- 同 ID handoff 未關閉時拒絕完成待辦。
- 索引排序與內容可重現。

### 查詢契約

- 專案問題只讀專案索引。
- 跨專案問題只讀總集索引。
- 特定項目才讀個別文件。
- 昨日查詢使用設定時區並只讀對應日期檔。
- 模糊名稱多重命中時不自行選擇。

### 同步

以本機 bare remote 建立端到端測試：

- init、首次上傳、無變更 sync。
- 另一裝置只改總集時可安全取回，且重建本機產生檔。
- 本機單邊變更時可上傳，多項修改合併成單一 commit。
- 兩側都改變時回報 `memory_diverged`，不得覆蓋任一側。
- fetch／fast-forward、push 成功與 push 失敗。
- dirty memory repository 拒絕同步。
- 非 fast-forward、project ID 與 history 衝突均停止且不遺失資料。
- 兩個專案聚合成穩定的全域 TASKS、PROJECTS 與 history。

### 相容性

- 現有 handoff 單元、CLI、hooks、installer 與 plan archival 測試全部維持通過。
- 未設定私人總集時，本機待辦功能正常且不嘗試網路操作。
- 沒有任何待辦時仍產生固定、精簡的空索引。

## 實作切分

為控制風險，實作分成兩個可獨立驗證的階段：

### 階段一：本機專案待辦

- 待辦 document、registry、service 與 CLI。
- README／TASKS 索引。
- milestone 與 completed 日期歷史。
- handoff 軟連結與完成防衝突。
- skill、adapter、installer 與測試。

### 階段二：私人 Git 總集

- project identity 與 memory 設定。
- 專案快照、全域索引與日期歷史聚合。
- 內容雜湊三方同步、fast-forward-only Git 更新與批次 commit。
- 跨裝置取回、分歧防護與端到端測試。

兩階段使用同一份資料格式；階段一不依賴私人總集存在。

## 驗收標準

完成實作後，以下情境必須成立：

1. 在兩個不同 repository 建立待辦，彼此 `.ai/TASKS.md` 只顯示各自項目。
2. 完成一項待辦後，它立即從活躍索引與文件移除，當日本地歷史留下單行摘要。
3. 「昨天做了什麼」只需讀取昨天的單一日期檔即可回答 milestone 與 completed 事件。
4. 同一 task ID 的 handoff 未關閉時，不得將待辦標示完成。
5. 兩個專案依序 sync 後，私人總集能列出所有未完成項與合併後的活動歷史。
6. 另一台裝置在本機未修改時，可從私人總集取回較新待辦；若兩側皆修改則停止且不覆蓋。
7. 同一專案再次上傳的多項變更最多新增一筆 commit；無差異不新增 commit。
8. 非 fast-forward 或 dirty repository 不會被自動覆蓋。
9. 任務清單、完成摘要與歷史中的秘密會在寫入前遭拒絕。
10. 未設定私人總集時，所有本機待辦與既有 handoff 功能仍可使用。
11. 既有測試全部通過，新增 transaction 與同步端到端測試通過。
