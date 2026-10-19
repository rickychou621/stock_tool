# Codex 任務：實作 stock_tool 階段四 — 批次行情、候選績效追蹤與回測成本

你正在專案 `~/dev/ricky/stock_tool` 工作。**請直接完成階段四的程式、資料庫 Migration、後端測試、前端整合與文件更新，不要只給設計建議。** 本 Prompt 為需求定稿，與 repo 舊設計文件衝突時以本 Prompt 為準；不得破壞已存在的功能及未提交修改。

## 0. 目標與範圍

階段四的目標：讓每日 19:00 的全市場掃描**在合理時間內跑完**，並開始**累積可驗證的績效證據**，作為後續排序與選股的依據。本階段包含三部分：

| 部分 | 內容 |
|---|---|
| A. 批次行情 | 每日日 K 與初始化歷史日 K 改用證交所 `MI_INDEX` 全市場批次 API；除權息改由證交所 `TWT49U` 偵測，只對有事件的標的呼叫 FinMind |
| B. 候選績效追蹤 | 每次發佈的正常命中另存歷史；排程回填進場後 N 個交易日的報酬，並與 0050 比較 |
| C. 回測成本與基準 | 階段二回測加入手續費、證交稅，並加入 0050 基準與超額報酬 |

**不在本階段範圍**（不要做）：全市場回測、候選評分／排序、Telegram 推送候選前 N 名、大盤濾網、籌碼／基本面條件、上櫃股票、減資／分割還原、券商 API、自動下單。

## 1. 開工前先盤點，不要臆測現況

1. 執行 `git status`，檢視 README、`docs/overall.md`、`docs/plan/06stock_tool_stage3_delivery.md`。
2. 確認以下程式的實際行為，再決定修改點：
   - `backend/app/market_scan/data.py`：`prepare()`、`sync_ranges()`、`missing_ranges()`、coverage 記錄方式。目前掃描模式對每檔股票逐檔呼叫 FinMind 補基準日及前 5 個交易日，另外逐檔查股利。
   - `backend/app/market_data/service.py` 的 `sync_daily_prices()`（含 `start_date/end_date/fetch_prices`）、`price_adjustment.py` 的還原算法、`validation.py` 的 `valid_ohlcv()`。
   - `backend/app/market_scan/publication.py`：候選原子發佈的 transaction 邊界。
   - `backend/app/backtest/simulation.py`：`returnRate`、績效統計的計算位置。
   - 現有證交所呼叫：`scheduler/calendar.py`、`backtest/data.py`（FMTQIK）、`market_scan/universe.py`（ISIN）。
   - `core/config.py` 已有 `finmind_api_token`，但 `finmind_client.py` 尚未使用。
3. 先提供精簡實作計畫與預計異動清單，隨後直接實作。遇到無法確定的既有 schema／API，依程式實況調整，最後回報差異與風險。
4. 不得自行清空 DB、重置工作樹、覆蓋未提交變更、commit、push。Migration 要可重複部署且與現有資料相容。

## 2. 技術與邊界

- 沿用 FastAPI / Python、React / TypeScript、MySQL、Docker Compose、APScheduler、SQLAlchemy Session 模式、`mysql/init/` 順序 SQL migration。
- 共用 `MarketDataService`、還原算法、`RuleEvaluationService`。不得另寫一套戰法判斷或還原算法。
- 階段一觀察清單 18:00 排程**維持 FinMind 逐檔同步，不改**。觀察清單可能含非上市標的，`MI_INDEX` 只涵蓋上市。
- 單 backend replica、單 Uvicorn process 的部署限制不變。
- 階段三的互斥、原子發佈、409、interrupted、不補跑、不重試 FinMind 等既有規則全部維持。

## 3. A：證交所批次行情

### 3.1 資料來源（已實測 2026-10-14）

| 用途 | API | 說明 |
|---|---|---|
| 單日全市場日 K | `https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date=YYYYMMDD&type=ALLBUT0999` | 免費、免 key。可指定日期。2026-10-14 16:33 已可取得當日資料。type `ALLBUT0999` 不含權證、牛熊證，約 1,381 列 |
| 除權息事件 | `https://www.twse.com.tw/exchangeReport/TWT49U?response=json&startDate=YYYYMMDD&endDate=YYYYMMDD` | 免費、免 key。參數名稱是 `startDate`／`endDate`，**不是** `strDate`（用錯會回「查詢結束日期小於查詢開始日期」） |

**不要使用** `openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL`：它只回傳最新一天、不能指定日期。實測 10/14 16:33 仍回傳 10/13 資料，`Last-Modified` 為台北時間 10/14 05:20，19:00 掃描時可能尚未更新。

### 3.2 MI_INDEX 解析規則

- 從 `tables` 中找出 `fields` 含「證券代號」與「開盤價」的那張表，**不要依賴表格索引位置**。
- 欄位對應：成交股數 → `volume`；成交金額 → `turnover`；開盤價／最高價／最低價／收盤價 → `open/high/low/close`。成交股數與 FinMind `Trading_Volume` 同為「股」，寫入前要在測試中確認單位一致。
- 數字含千分位逗號（例如 `2,490.00`），去除後再轉 Decimal。
- 價格為 `--` 或空白表示當日無成交：**不寫入日 K**，在 coverage 記為「來源確認當日無行情」。
- 回應的 `date` 必須等於請求日期，`stat` 必須為 `OK`；否則視為來源尚未發布或無資料，不寫入任何列。
- 只寫入 `market_scan_instruments` 中 active 的普通股與 ETF。其他代號忽略。
- 每列仍須通過既有 `valid_ohlcv()` 驗證。無效列不寫入、記錄逐股錯誤，不影響其他列。

### 3.3 寫入與還原

- 寫入 `stock_price_daily` 原始 OHLCV 與 `turnover`，沿用既有 unique key 與並發安全的 upsert。已存在的有效列以證交所值覆寫前，若差異超過 0.01 元，記錄警告（作為與 FinMind 的口徑比對），仍以證交所值為準。
- 寫入後，`adj_*` 必須由既有還原算法產生。若某標的在該日之前沒有新除權息事件，可只補算新增列；若有新事件，依既有流程重算該標的的還原價。
- 單日批次寫入失敗時 rollback 該日，不寫半套。

### 3.4 除權息偵測

1. 每次需要補行情的日期範圍，先呼叫一次 `TWT49U` 取得該範圍全部除權息事件。
2. 只對「範圍內有事件，且 `stock_dividend_events` 尚未有該除權息日」的標的，呼叫既有 FinMind 股利同步（`fetch_prices=False`），取得現金股利、配股率、現增等細節，供既有還原算法使用。
3. `TWT49U` 的事件與 FinMind 結果不一致時（例如 TWT49U 有事件，但 FinMind 查無對應除息日），記錄逐股警告，該標的本次評估照常進行，警告顯示在任務錯誤列表。
4. 不改用 TWT49U 的參考價自行推算還原係數；還原算法本階段不動。

### 3.5 每日掃描流程（取代逐檔 FinMind）

1. 決定掃描基準日與前 5 個交易日（沿用現有邏輯）。
2. 對這 6 天中 coverage 尚未確認的**日期**，每日各呼叫一次 `MI_INDEX`。最多 6 次請求，正常情況只有 1 次。
3. 呼叫一次 `TWT49U` 涵蓋這 6 天，依 3.4 補股利。
4. 更新 coverage：該日來源成功回應時，active 名單中每檔標的的該日都視為已確認（有列 = 有行情，無列或 `--` = 確認無行情）。
5. 之後的戰法評估、候選發佈、Telegram 完成通知流程不變。

**基準日的 MI_INDEX 尚未發布或請求失敗**：不自動重試、不改用 FinMind 逐檔備援。任務照常評估，使用既有資料，套用既有「最多落後 5 個交易日」與 `olderQuote` 規則；任務警告寫明「證交所當日行情尚未取得」。使用者可稍後手動掃描。

### 3.6 初始化流程

- 歷史日 K 改為**依日期**逐日呼叫 `MI_INDEX`，取代逐檔 FinMind。所需日期範圍沿用現有 `required_days()` 動態計算；只呼叫 coverage 尚有缺口的日期。
- 股利依 3.4，`TWT49U` 以月為單位分段查詢。
- 預期耗時：3 年約 750 個交易日，每次請求間隔 3 秒，約 40 分鐘；另加 FinMind 股利呼叫。完成後於交付文件記錄實測時間。
- 已存在且有效的日 K 不重抓。初始化完成仍**不自動掃描**。

### 3.7 證交所共享節流

- 新增 `TWSE_MIN_REQUEST_INTERVAL_SECONDS`，預設 `3`，校驗為正數。寫入 `config/backend.env.example` 與 README 設定表。
- 證交所對短時間大量請求會暫時封鎖 IP。所有對 `www.twse.com.tw` 的呼叫共用同一個 process 內的 paced limiter，包含新的 MI_INDEX、TWT49U，以及既有的 FMTQIK 呼叫。`isin.twse.com.tw` 一併納入。
- 收到非 JSON（例如封鎖頁 HTML）或 HTTP 錯誤時，記錄錯誤、不重試，該日視為未取得。

### 3.8 FinMind token

- `FinMindClient` 在 `FINMIND_API_TOKEN` 非空時帶入 token（依 FinMind 官方方式），空值時維持匿名。token 不得出現在 log、警告或錯誤訊息。
- `FINMIND_SCAN_REQUESTS_PER_MINUTE` 的節流與預設值不變；README 說明有 token 時可自行調高。

## 4. B：候選績效追蹤

### 4.1 訊號歷史

- 新增 `market_scan_signal_history`。候選**原子發佈的同一個 transaction** 中，把本次 `status=normal` 的列寫入歷史；`stale`、`insufficient_history` 不寫入。
- 唯一鍵 `(signal_date, ticker, rule_id)`，`signal_date` 為掃描基準日。同一基準日再次發佈（例如手動重跑）時：已存在的列保留首次紀錄，只更新 `last_batch_id`、`last_seen_at`；新命中的列新增；本次未命中的舊列**不刪除**。
- 欄位至少包含：`signal_date`、`ticker`、`rule_id`、戰法名稱快照、`kind`、`price_date`、`older_quote`、原始收盤價、成交量、成交金額（可 null）、指標 JSON 快照、`source`（automatic/manual）、`first_batch_id`、`last_batch_id`、建立／更新時間。
- 這張表永久保存，不隨任務清理。不刪除既有 `market_scan_candidates` 的「只保留最新」語意。

### 4.2 後續報酬計算口徑

- **進場**：`signal_date` 後下一個有效交易日的開盤價。有效交易日沿用階段二定義：OHLC 有效且成交量大於零；停牌順延。
- **觀察期**：預設 `[1, 5, 10, 20]` 個交易日，以環境變數 `SIGNAL_TRACKING_HORIZONS` 設定（逗號分隔正整數，上限 60）。觀察期 N 的出場價為進場日起第 N 個市場交易日的收盤價；當日無有效收盤時，使用該日以前最後有效收盤，並記錄估值日期。
- **價格基準**：使用目前資料庫的還原價（`adj_*`），進出場同一基準，避免除權息造成假跌。
- **毛報酬** = 出場價 ÷ 進場價 − 1。
- **淨報酬**：依第 6 節共用成本模組扣除買進手續費、賣出手續費與證交稅。
- **0050 基準**：同一進場日開盤到同一出場日收盤的 0050 還原報酬。**超額報酬** = 淨報酬 − 0050 毛報酬（0050 不扣成本，作為「什麼都不做只買大盤」的參考）。
- **期間最大不利幅度**：觀察期內最低還原低價 ÷ 進場價 − 1，供日後設定停損參考。
- 尚未到期的觀察期保持 null，不得以部分期間代替。標的下市或資料缺失導致無法計算時，記錄原因，不填 0。

### 4.3 回填排程

- 新增 `market_scan_signal_returns`，鍵為 `(signal_id, horizon)`，保存進場日、進場價、出場估值日、出場價、毛／淨／0050／超額報酬、最大不利幅度、狀態（pending/completed/unavailable）與原因。
- 每次階段三掃描任務**發佈完成後**，在同一個背景任務尾端執行回填：只計算已到期且尚未 completed 的列。回填只讀 DB，不呼叫任何外部 API。
- 回填失敗不影響已發佈的候選與任務完成狀態，只追加 task warning。
- 回填改用 batch 查詢，不得逐筆 N+1 查日 K。
- 0050 日 K 需在 DB 中：0050 為上市 ETF，已在階段三名單內；若缺資料，該列標 unavailable 並註明原因。

### 4.4 API 與前端

- `GET /market-scan/signal-performance`：依「戰法 × 觀察期」彙總。參數：`ruleId`、`from`、`to`（signal_date 範圍）、`kind`、`minTurnover`、`excludeOlderQuote`。回傳每組的樣本數、淨報酬勝率（淨報酬 > 0）、平均／中位數淨報酬、平均超額報酬、超額報酬為正的比例、平均最大不利幅度。
- `GET /market-scan/signals`：訊號明細分頁，預設 50、上限 200，可依 signal_date、ticker、ruleId 篩選，回傳各觀察期報酬。
- 樣本數少於 30 時回傳 `sampleInsufficient=true`；前端標示「樣本不足」，仍顯示數字。沒有已完成樣本時指標為 null，前端顯示「無資料」，不得顯示 0%。
- 前端在「全市場掃描」頁新增「戰法績效追蹤」區塊：彙總表（列 = 戰法，欄 = 各觀察期），上方提供日期範圍、種類、最低成交金額篩選。點戰法可展開該戰法的訊號明細分頁。不做圖表、不做 CSV 匯出。
- 頁面說明文字需寫明：這是系統上線後實際記錄的訊號，起始日期為階段四部署日；樣本累積前結果不具參考性。

## 5. C：回測成本與基準

### 5.1 共用成本模組

- 新增一個共用模組（例如 `backend/app/trading_costs.py`），回測與訊號追蹤都使用它，不得兩處各寫一套。
- 預設值以環境變數設定，寫入 `.env.example` 與 README：

| 變數 | 預設 | 說明 |
|---|---|---|
| `TRADE_FEE_RATE` | `0.001425` | 買、賣各收一次 |
| `TRADE_FEE_DISCOUNT` | `1.0` | 券商折扣，例如 6 折填 `0.6`；校驗 0 < x ≤ 1 |
| `TRADE_TAX_RATE_STOCK` | `0.003` | 普通股賣出證交稅 |
| `TRADE_TAX_RATE_ETF` | `0.001` | ETF 賣出證交稅 |

- 淨報酬 = (出場價 × (1 − 手續費率 × 折扣 − 稅率)) ÷ (進場價 × (1 + 手續費率 × 折扣)) − 1。
- 不模擬最低手續費 20 元、不模擬滑價、不模擬當沖減半稅率；文件寫明這些限制。
- 標的種類（普通股／ETF）取自 `market_scan_instruments.kind`；查無種類時以普通股稅率計算並記錄。

### 5.2 回測調整

- 每筆已完成交易同時保存毛報酬與淨報酬。勝率、平均報酬、複利報酬、最大回撤、獲利因子**以淨報酬為主**，毛報酬並列顯示。
- 未平倉的未實現報酬也提供淨值版本（假設以估值價賣出）。
- **0050 基準**：
  - 每筆交易：同一買進日開盤到同一賣出日開盤的 0050 還原報酬，以及超額報酬（淨報酬 − 0050 報酬）。
  - 戰法整體：平均超額報酬；並列出「回測實際期間 0050 買進持有報酬」。
  - 0050 不在觀察清單時，回測沿用 DB 優先、缺漏才同步的既有流程補 0050 資料；0050 資料不足時基準欄位為 null 並註明，不影響戰法本身的回測。
- 回測任務保存本次使用的成本參數快照，結果頁顯示。
- 舊回測結果沒有淨報酬欄位：標示「需重新回測」，不得用毛報酬冒充淨報酬。

## 6. 資料庫 Migration

- 新增 `mysql/init/009_stage4.sql`，可重複執行，只新增表／欄位，不刪除或重設既有資料。
- 至少包含：`market_scan_signal_history`、`market_scan_signal_returns`，以及 coverage 若需區分來源所需的欄位。回測結果若以 JSON 保存，在 JSON 中新增欄位即可，不必改表。
- 索引支援：`signal_date`、`(rule_id, signal_date)`、`ticker`、`(horizon, status)`。
- 更新 `docs/db.md` 的增量章節，格式比照 006／007／008 段落。

## 7. 後端測試與驗收案例（必做）

依 repo 現有 pytest、SQLite 隔離與 respx mock 模式新增測試，至少涵蓋：

1. MI_INDEX 解析：依欄位名找表、千分位、`--` 無成交、`stat` 非 OK、`date` 不符、非 active 代號忽略、無效 OHLC 不寫入。
2. MI_INDEX 寫入：與既有列差異警告、turnover 寫入、單日 rollback、還原價正確產生。
3. TWT49U：參數名稱為 `startDate/endDate`、只對有事件且缺股利的標的呼叫 FinMind、TWT49U 與 FinMind 不一致時的警告。
4. 每日掃描：正常只打 1 次 MI_INDEX；基準日未發布時不重試、不逐檔 FinMind、olderQuote 生效；coverage 確認無行情日期不重抓。
5. 初始化：依日期補缺口、已有效日期不重抓、初始化完成不自動掃描。
6. 證交所節流：MI_INDEX、TWT49U、FMTQIK、ISIN 共用間隔；封鎖頁 HTML 不重試。
7. FinMind token：有值時帶入、空值匿名、token 不出現在錯誤訊息。
8. 訊號歷史：只寫 normal、與候選同 transaction（發佈 rollback 時歷史也 rollback）、同日重跑保留首次紀錄、未命中舊列不刪。
9. 後續報酬：下一有效交易日開盤進場、停牌順延、未到期為 null、出場日無收盤時用前一有效收盤、淨報酬公式、0050 超額報酬、最大不利幅度、下市標 unavailable。
10. 回填：只算到期列、不呼叫外部 API、失敗不影響發佈、無 N+1。
11. 成本模組：普通股與 ETF 稅率、折扣、公式數值；回測與追蹤共用同一模組。
12. 回測：淨報酬統計、毛淨並列、0050 基準與超額報酬、0050 缺資料為 null、成本參數快照、舊結果標示需重跑。
13. 彙總 API：樣本不足、無資料為 null、篩選與分頁上限。
14. 回歸：階段一 18:00、階段二回測、階段三互斥／原子發佈／interrupted／Telegram 通知全部維持。

前端執行既有 TypeScript 檢查、ESLint、build；以瀏覽器（390px 與 1280px）手動驗證績效追蹤區塊、樣本不足標示、回測頁毛淨並列與 0050 基準。不新增 Vitest。

## 8. 建議實作步驟（逐步完成並驗證）

1. 盤點現況，提出計畫與異動清單。
2. `009_stage4.sql`、共用成本模組、證交所共享節流、FinMind token。
3. MI_INDEX client／解析／寫入、TWT49U 偵測與股利補齊、coverage 更新。
4. 將每日掃描與初始化切到批次路徑，確認 FinMind 逐檔路徑只剩股利補齊。
5. 訊號歷史寫入（併入原子發佈）、後續報酬回填、彙總與明細 API。
6. 回測淨報酬、0050 基準、成本參數快照、舊結果標示。
7. 前端績效追蹤區塊與回測頁調整。
8. 測試、migration 實際套用、README／`docs/overall.md`／`docs/db.md` 更新，最後撰寫交付文件 `docs/plan/08stock_tool_stage4_delivery.md`。

## 9. 實際環境驗證（必做，與自動化測試分開）

階段三交付時未做真實全市場執行。本階段完成後請實際執行並記錄：

1. 對本地 MySQL 套用 `009`，連續套用兩次確認可重複部署。
2. 實際呼叫一次 MI_INDEX 與 TWT49U，寫入一個交易日的全市場日 K。抽查 2330、0050 及 3 檔隨機普通股，比對 FinMind 同日資料，回報差異。
3. 實際執行一次全市場手動掃描，記錄總耗時、MI_INDEX 請求數、FinMind 請求數、成功／失敗／不足數、正常命中列數。
4. 確認訊號歷史已寫入，回填任務對尚未到期的列維持 pending。
5. 不實發 Telegram（mock 或暫時清空設定），不更動使用者的自動排程設定。

## 10. 完成回報格式

- 已完成功能對照表及**未完成／與規格不同**的項目（不能將未做功能寫成已完成）。
- Migration、重要新增／修改檔案與 API 清單。
- 新增環境變數與預設值。
- 實際執行的測試／typecheck／lint／build 指令與結果；無法執行者明確列原因。
- 第 9 節實際環境驗證的數字。
- 已知限制：證交所 API 非官方 SLA、IP 封鎖風險、成本模型的簡化、訊號歷史從部署日才開始累積。
- 不自行 commit 或 push；保留使用者原有修改。

**重要：不要做全市場回測、候選評分排序、Telegram 推送候選清單、上櫃股票、大盤濾網、還原算法改寫、STOCK_DAY_ALL、MI_INDEX 失敗時改走 FinMind 逐檔備援、改動階段一的資料來源。**
