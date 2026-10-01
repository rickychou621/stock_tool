# 資料庫規劃(MySQL)

> 本文件聚焦資料表設計,系統整體背景請參考 [overall.md](./overall.md)。此文件之後會隨開發過程持續調整,實際型別/長度以 SQLAlchemy migration 為準。

## 1. 資料表總覽

| 資料表 | 用途 |
|---|---|
| `stocks` | 上市櫃股票基本資料(主檔) |
| `stock_price_daily` | 日K價量資料(原始股價 + 自算的還原股價) |
| `stock_price_intraday` | 盤中分K價量資料(供左側爆量城牆K等歷史比對用) |
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
