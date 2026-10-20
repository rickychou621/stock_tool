# 資料庫規劃(MySQL)

> 本文件聚焦資料表設計,系統整體背景請參考 [overall.md](./overall.md)。此文件之後會隨開發過程持續調整,實際型別/長度以 SQLAlchemy migration 為準。

## 1. 資料表總覽

| 資料表 | 用途 |
|---|---|
| `stocks` | 上市櫃股票基本資料(主檔) |
| `stock_price_daily` | 日K價量資料(原始股價 + 自算的還原股價) |
| `stock_price_intraday` | 盤中分K價量資料(供左側爆量城牆K等歷史比對用) |
| `stock_price_events` | 分割／反分割／面額變更／減資價格事件 |
| `stock_price_event_sync` | 全市場價格事件每日同步狀態，單列 id=1 |
| `stock_dividend_events` | 股利/增資事件,用來反推還原股價的調整係數 |
| `condition_catalog` | 條件庫清單(供前端動態組裝規則時查詢可用條件與參數規格) |
| `watch_rules` | 使用者組合的監控規則 |
| `watch_rule_conditions` | 規則所引用的條件與參數(規則與條件為多對多) |
| `daily_condition_cache` | 每日/月頻條件的計算結果快取(供混合頻率規則使用) |
| `candidate_pool` | 目前粗篩產出的候選池 |
| `holdings_watchlist` | 手動維護的持股觀察清單 |
| `alerts_log` | 告警觸發歷史紀錄 |

## 2. 資料表設計

### 2.1 `stocks`(股票主檔)

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | INT PK | |
| `ticker` | VARCHAR(10) UNIQUE | 股票代號 |
| `name` | VARCHAR(50) | 股票名稱 |
| `market` | VARCHAR(10) | 上市/上櫃 |
| `is_active` | BOOLEAN | 是否納入掃描範圍(可排除下市/全額交割股等) |
| `updated_at` | DATETIME | |

### 2.2 `stock_price_daily`(日K)

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | BIGINT PK | |
| `ticker` | VARCHAR(10) FK → stocks.ticker | |
| `trade_date` | DATE | |
| `open` / `high` / `low` / `close` | DECIMAL(10,2) | 原始成交價(來源:FinMind `TaiwanStockPrice`,未還原除權息) |
| `adj_open` / `adj_high` / `adj_low` / `adj_close` | DECIMAL(10,2) NULL | 自算的還原股價,依`stock_dividend_events`反推(見`price_adjustment.py`);圖表/技術指標一律讀這組欄位,NULL代表還沒重算過(退回讀原始價) |
| `volume` | BIGINT | 成交量(不還原) |
| `created_at` | DATETIME | |

索引:`UNIQUE (ticker, trade_date)`,查詢時以此為主要存取路徑。

### 2.3 `stock_dividend_events`(股利/增資事件)

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | INT PK | |
| `ticker` | VARCHAR(10) FK → stocks.ticker | |
| `ex_dividend_date` | DATE | 除權息交易日(來源:FinMind `TaiwanStockDividend`) |
| `cash_dividend` | DECIMAL(10,4) | 每股現金股利 |
| `stock_dividend_ratio` | DECIMAL(10,6) | 無償配股率(股票股利/10) |
| `cash_capital_increase_ratio` / `cash_capital_increase_price` | DECIMAL | 現金增資配股率/認購價 |
| `created_at` | DATETIME | |

索引:`UNIQUE (ticker, ex_dividend_date)`。每次`/stocks/{ticker}/sync`都會重新拉取並整段重算`stock_price_daily`的`adj_*`欄位。

### 2.4 `stock_price_intraday`(盤中分K)

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | BIGINT PK | |
| `ticker` | VARCHAR(10) FK → stocks.ticker | |
| `timeframe` | VARCHAR(10) | `1m`/`2m`/`5m`/`15m`/`60m` |
| `bar_time` | DATETIME | 該K棒起始時間 |
| `open` / `high` / `low` / `close` | DECIMAL(10,2) | |
| `volume` | BIGINT | |

索引:`UNIQUE (ticker, timeframe, bar_time)`。此表資料量成長較快,後續可依需求規劃資料保留期限(例如僅保留近N個月供爆量比對使用)或改用時間序列導向的儲存策略。

### 2.5 `condition_catalog`(條件庫清單)

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | VARCHAR(50) PK | 條件代碼,對應後端 `conditions/registry.py` 註冊的條件 |
| `name` | VARCHAR(100) | 顯示名稱(如「EMA黃金交叉」) |
| `description` | TEXT | 說明文字 |
| `required_timeframe` | VARCHAR(10) | 該條件所需時框 |
| `update_frequency` | VARCHAR(10) | `realtime`/`daily`/`monthly` |
| `param_schema` | JSON | 參數規格(供前端動態產生輸入表單,如 `{"short_period": "int", "long_period": "int"}`) |

此表由後端啟動時依 `conditions/registry.py` 的註冊內容同步寫入,前端只讀取此表來組裝規則,不需知道條件的實際運算邏輯。

### 2.6 `watch_rules`(監控規則)

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | INT PK | |
| `name` | VARCHAR(100) | 規則名稱(使用者自訂,如「A+B組合監控」) |
| `logic_operator` | VARCHAR(5) | `AND` / `OR` |
| `is_enabled` | BOOLEAN | 是否啟用 |
| `created_at` / `updated_at` | DATETIME | |

### 2.7 `watch_rule_conditions`(規則—條件 關聯)

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | INT PK | |
| `rule_id` | INT FK → watch_rules.id | |
| `condition_id` | VARCHAR(50) FK → condition_catalog.id | |
| `params` | JSON | 該條件在此規則中的實際參數值(如 `{"short_period": 10, "long_period": 60}`) |
| `sort_order` | INT | 顯示/評估順序 |

### 2.8 `daily_condition_cache`(每日條件結果快取)

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | BIGINT PK | |
| `ticker` | VARCHAR(10) | |
| `condition_id` | VARCHAR(50) FK → condition_catalog.id | |
| `params_hash` | VARCHAR(64) | 參數內容的hash值(同一條件不同參數需分開快取) |
| `trade_date` | DATE | 計算基準日期 |
| `result` | BOOLEAN | 該日該參數組合下條件是否成立 |
| `computed_at` | DATETIME | |

索引:`UNIQUE (ticker, condition_id, params_hash, trade_date)`。供混合頻率規則於盤中即時評估時,直接查詢當天已計算好的日頻/月頻條件結果,不需重算。

### 2.9 `candidate_pool`(候選池)

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | BIGINT PK | |
| `ticker` | VARCHAR(10) | |
| `reason` | VARCHAR(255) | 入選原因(如「成交量放大3倍」) |
| `score` | DECIMAL(10,4) | 供排序/汰換依據(可選) |
| `added_at` | DATETIME | |
| `expired_at` | DATETIME | 被換出候選池的時間(NULL表示目前仍在池中) |

每次粗篩/動態換股執行時寫入新紀錄,查詢「目前候選池」即為 `expired_at IS NULL` 的資料列。

### 2.10 `holdings_watchlist`(持股觀察清單)

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | INT PK | |
| `ticker` | VARCHAR(10) | |
| `entry_price` | DECIMAL(10,2) | 進場價位(手動輸入) |
| `entry_date` | DATE | |
| `notes` | TEXT | 備註 |
| `is_active` | BOOLEAN | 是否仍在觀察中(手動移除時設為 false 而非刪除紀錄,保留歷史) |
| `created_at` / `updated_at` | DATETIME | |

### 2.11 `alerts_log`(告警歷史)

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | BIGINT PK | |
| `rule_id` | INT FK → watch_rules.id | |
| `ticker` | VARCHAR(10) | |
| `triggered_at` | DATETIME | |
| `price_at_trigger` | DECIMAL(10,2) | 觸發當下價位 |
| `message` | TEXT | 推播給Telegram的實際訊息內容 |
| `is_notified` | BOOLEAN | 是否已成功推播(可用於重試機制) |

索引:`INDEX (ticker, triggered_at)`、`INDEX (rule_id, triggered_at)`,供查詢歷史與防重複發送判斷使用。

## 3. 關聯示意

```
stocks 1───N stock_price_daily
stocks 1───N stock_price_intraday
stocks 1───N stock_dividend_events
condition_catalog 1───N watch_rule_conditions N───1 watch_rules
condition_catalog 1───N daily_condition_cache
watch_rules 1───N alerts_log
```

`candidate_pool`、`holdings_watchlist` 邏輯上皆對應 `stocks.ticker`,但不強制外鍵約束,避免掃描到主檔尚未同步的新股時寫入失敗。

## 4. 待補充項目

- `stock_price_intraday` 的資料保留策略與是否需要分表/歸檔
- 各表的實際欄位長度與型別於 SQLAlchemy model 定義時再校正
- migration 工具選擇(如 Alembic)與版本管理方式

## 觀察結果與族群

`005_watchlist_workflow.sql` 新增 stocks.sector（使用者觀察分類）、stocks.data_version（行情寫入版本）及 watchlist_evaluations。後者以 item_id + rule_id 唯一，保存 JSON 評估結果、UTC evaluated_at、data_version 及 rule_fingerprint。外鍵刪除採 CASCADE，觀察項目停用則不回傳其結果。

既有資料庫需執行一次 005 遷移，不能僅重建 backend。ALTER TABLE 為一次性操作，重跑前需檢查欄位是否已存在；新資料庫由初始化目錄依序套用。族群初始資料僅補空白值，不覆寫既有自訂分類。


## 觀察清單排程（006）

`006_watchlist_schedule.sql` 新增 watchlist_schedule_settings、watchlist_schedule_latest 及 watchlist_schedule_errors。設定及最新摘要各保存一列，錯誤歷史永久保存且以 batch_id 關聯，覆寫摘要不會刪除歷史錯誤。last_attempt_date 使用台灣交易日期；其他時間儲存 UTC。

既有 DB 需先套用 006，再重建 backend；SQL 可重複執行且不覆寫既有設定。完整流程、API 與操作命令見 [階段一交付文件](plan/02stock_tool_stage1_delivery.md)。


## 歷史回測（007）

`007_backtest.sql` 新增 backtest_latest_task（單筆任務狀態）、backtest_results（ticker + rule_id 最新成功結果）、backtest_data_coverage（已向來源查證的資料範圍）及 backtest_calendar_months（證交所交易日期快取）。結果保存統計摘要與交易／訊號 JSON，成功結果和股票進度在同一 transaction 更新。失敗保留舊結果並標記過期，整體績效只計入當次成功 batch。

既有 DB 先套用 007 再重建 backend。方法、限制與驗證見 [階段二交付文件](plan/04stock_tool_stage2_delivery.md)。

## 第三階段 Migration 008

`mysql/init/008_market_scan.sql` 為可重複部署的新增式 migration，保留既有資料。共用 `stock_price_daily` 增加 nullable `turnover DECIMAL(22,2)`，只存來源實際成交金額。

新增 `market_scan_instruments/settings/tasks/errors/coverage/candidates/indicators/publication` 八表。市場名單 active 不改使用者觀察清單；scan/initialize 最近任務各一筆；候選 unique(ticker, rule_id)，並索引 ticker、kind、rule_id、status、batch_id、price_date、close、volume、turnover。數值指標另外索引供動態條件查詢。

候選、指標、批次 metadata 與 scan 完成狀態同一 transaction 發佈，工作中不改候選；錯誤採逐股／戰法保存及分頁查詢。初始化覆蓋記錄不取代共用 OHLC、股利表。完整欄位與語意見 [階段三交付紀錄](plan/06stock_tool_stage3_delivery.md)。

## 階段四 A Migration 009

`mysql/init/009_stage4.sql` 可重複部署，新增 `market_scan_batch_coverage`：`trade_date DATE` 主鍵、`absent_tickers JSON` 保存來源確認無成交或未回傳的代號。有效列直接從日 K 判斷；無效列不寫入 absence，後續可重新補取。舊 `market_scan_coverage` 保留，但批次路徑不使用其逐檔區間記錄。

新增 `stock_price_daily.trade_date` 索引，支援按日查缺口。單日行情、還原價、股票資料版本與 coverage 同一 transaction 更新。009 不改排程設定、不新增訊號歷史／績效表；階段四 B/C 待後續實作。

## 股利完整性 Migration 010

`mysql/init/010_dividend_coverage.sql` 新增 `market_scan_dividend_coverage`：`ticker VARCHAR(10)` 主鍵、`start_date DATE`、`end_date DATE`。保存 TWSE 事件查詢成功且已具備所有預期股利事件的期間；FinMind 缺事件或來源失敗不新增完整性證明。不依既有股利列自動推定完整。可重複執行，不修改日 K、股利或排程設定。

覆蓋期間只合併重疊或相鄰範圍。日常 6 日事件核對可延長已初始化區間；跨越缺口時不宣告中間完整。全市場評估要求覆蓋戰法回看期，未覆蓋者列資料不足；觀察清單與回測未套用此限制。

## 回測成本 Migration 011

`mysql/init/011_backtest_costs.sql` 可重複執行，新增 `backtest_latest_task.context_json JSON NULL`。接受任務時保存 costSnapshot，準備基準後加入日期到 0050 還原開／收盤的映射。API 僅公開成本，不整份回傳基準快照。

既有 `backtest_results.payload/summary` 新結果包含 schemaVersion=2、costSnapshot、grossMetrics、淨 metrics 與 0050 比較欄位，交易保留 grossReturnRate/netReturnRate/grossUnrealizedReturn/netUnrealizedReturn。舊 JSON 不回填推算淨值，透過 needsRerun 標示。成本與基準準備後的每檔全部戰法結果仍同一 transaction 保存。
## 訊號績效追蹤 Migration 012

`012_signal_tracking.sql` 可重複執行，新增以下資料表，不改動排程或既有候選。

| 表 | 用途與鍵 |
|---|---|
| `market_scan_signal_history` | 首次命中快照與成本參數；唯一鍵 `(signal_date, ticker, rule_id)`，另有日期、戰法日期與股票索引 |
| `market_scan_signal_returns` | 每筆訊號各觀察期的進出場、毛／淨／0050／超額報酬與不利幅度；主鍵 `(signal_id, horizon)`，狀態為 pending／completed／unavailable，保存原因與 JSON 數值 |
| `market_scan_signal_meta` | 單例首次部署日；重複部署不改日期 |

歷史與候選在同一交易發佈；回填在發佈提交後獨立執行。歷史永久保存，不隨最新掃描任務清理。同日重跑只更新最後批次與時間，不改首次快照。


## 價格事件 Migration 013

[013_price_events.sql](../mysql/init/013_price_events.sql) 可重複執行，新增 stock_price_events 與 stock_price_event_sync，不修改既有資料、排程或完整性紀錄。既有 DB 須先套用 migration，再補齊價格事件及重新回測。

| 欄位 | 型別與用途 |
|---|---|
| id | INT 自增主鍵 |
| ticker | VARCHAR(10)，外鍵 stocks.ticker，另有股票索引 |
| event_date | DATE，恢復買賣日 |
| event_type | VARCHAR(24)，split／reverse_split／par_value_change／capital_reduction |
| before_close | DECIMAL(14,6)，來源提供的事件前收盤價 |
| reference_price | DECIMAL(14,6)，來源提供的恢復買賣參考價 |
| source | VARCHAR(32)，finmind_split／twse_twtauu／tpex_revivt |
| created_at | DATETIME，UTC 建立時間 |

唯一鍵為 ticker、event_date、event_type。新增或修正價格會在同一交易重算該股歷史 adj_*、增加 data_version 並標記 backtest_results.stale；0050 事件會讓全部舊回測過期。相同事件重送不重算；不同來源的相同事件共用唯一鍵，價格有修正時更新來源。

還原係數為 reference_price ÷ before_close，僅作用於 event_date 之前的 OHLC，volume 不調整。股利與價格事件分表儲存，同日各自套用係數。


stock_price_event_sync 單列同步紀錄：

| 欄位 | 型別與用途 |
|---|---|
| id | INT 主鍵，固定 1，CHECK 約束 |
| synced_on | DATE，台北同步日期 |
| complete | BOOLEAN，預設 false；三來源及事件寫入皆成功才設 true |

固定查詢 2011-01-01 至當天，因此不保存或比較呼叫者的 start/end。當天 complete=true 跳過全部來源，價格事件的 FinMind 每天最多 1 次；失敗保留 false，下次呼叫允許重試，不屬嚴格每日上限。MySQL advisory lock 序列化跨任務同步；失敗狀態先提交，事件與成功標記則在同一交易提交。只匯入 stocks 中已存在的 ticker，同步前確保基準 0050 主檔存在。

## 條件角色 Migration 014

[014_rule_condition_roles.sql](../mysql/init/014_rule_condition_roles.sql) 先檢查 information_schema，再新增 watch_rule_conditions.role VARCHAR(10) NOT NULL DEFAULT 'premise'，可重複執行。既有條件皆視為 premise，部署新版後端前須先套用 migration。

角色由 API 與 ORM 驗證，只接受 premise（前提）、entry（進場）、exit（出場）。前提依戰法 AND／OR 合成 premise_met 與 is_met；進場條件固定 AND、出場條件固定 OR，沒有該類條件時回傳 null。status 依前提判斷，任何角色缺少實作或戰法缺少前提都回報 error。此階段只提供新欄位，回測、全市場掃描與觀察清單尚未採用進出場觸發欄位。
