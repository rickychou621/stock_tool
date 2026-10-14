# 階段三交付紀錄

本次依 `stock_tool_three_stage_roadmap_final.md` 及 `05stock_tool_stage3_codex_prompt_final.md` 實作全市場掃描。階段一、二既有未提交修改保留，未 commit / push。舊今日符合戰法與候選池頁面、API 均保留；新頁面位於 `/market-scan`。

## 功能對照

| 規格 | 實作 |
|---|---|
| 上市普通股與 ETF | 證交所 ISIN 名單，分類與 CFI code 雙重辨識；含上市創新板普通股，排除上櫃、特別股、權證、ETN、TDR、REIT |
| 更新與 fallback | 每次初始化／手動／自動任務更新；新增 upsert、離開有效名單者標 inactive；來源失敗沿用最近名單，空名單則失敗 |
| 初始化 | 獨立背景任務；共用 `history_days` 動態回看＋暖機；既有價格重用，僅補缺漏價格／股利覆蓋；不自動接掃描 |
| 日常更新 | 只查掃描基準日及前 5 個交易日的未完整區間，不補更舊歷史；已確認停牌／上市前無資料區間不反覆下載 |
| 排程／設定 | DB 持久化，預設啟用、所有 enabled 戰法；TWSE 交易日 19:00；空選擇 skipped，失敗不重試、不補跑 |
| 互斥／併行 | 第三階段工作中的初始化、自動、手動共用 named lock；API 衝突 409；預設 5 worker 各自 Session；回測另有獨立鎖，可並行 |
| 行情／評估 | 正且合理 OHLC、有限數字、非負量；零量可評估；最多落後 5 個實際交易日；直接使用原規則引擎，逐股票×戰法隔離 |
| 候選發佈 | 執行中舊清單可讀；完成後單次 transaction 更新候選、指標索引、metadata 及任務完成狀態 |
| 候選查詢 | 每頁預設 50，上限 200；代碼／名稱、種類、戰法、日期、價格、技術指標、量、實際金額、狀態，排序與分頁均由 DB 執行 |
| Telegram | 成功／部分失敗／全失敗完成簡訊；含台北完成時間，無逐股明細；未設定／發送失敗只記 task warning |
| 前端 | 單頁自動設定、初始化、手動戰法、進度、摘要、候選、錯誤；3 秒輪詢；完成刷新保留 filters/sort/page；無 CSV 或加入觀察清單按鈕 |
| 中斷 | 啟動時取得鎖後將 running/pending 標 interrupted，候選與已成功下載行情保留；不續跑 |

## 名單與交易日期

名單來源：[TWSE ISIN 上市有價證券](https://isin.twse.com.tw/isin/C_public.jsp?strMode=2)。Big5/CP950 HTML 依「股票／創新板＋ES」及「ETF＋CE」辨識，市場須為上市，上市日期不晚於基準日期。下載樣本解析為 1,085 檔普通股及 241 檔 ETF，共 1,326 檔；這是本次來源樣本，日後以每次有效名單為準。

完整性檢查要求股票、ETF、ETN 分類均存在，普通股至少 800、ETF 至少 100，任一種類不得比舊有效名單驟降超過 10%。未通過就 rollback 名單更新、沿用舊名單並顯示警告。這是可見的保守保護；未來若交易所正式重編大批分類，需要調整門檻。

`market_scan_instruments.active` 表示第三階段有效名單，不改使用者觀察清單及其主檔 `is_active`。下市標的歷史行情保留；既有候選標過期並註明已不在有效名單。

交易日期沿用 [TWSE FMTQIK 實際成交日期](https://www.twse.com.tw/exchangeReport/FMTQIK?response=json&date=20261001)，包含颱風等臨時休市。共用已存在的月份快取；階段三允許當月尚無成交日，回溯前月有效日，舊回測預設行為不變。19:00 排程會先直接確認當日是否有交易。手動 18:00 前採前一日以前的最後交易日，18:00 後採當日以前最後交易日，以已公布日K為準。

## 行情、節流與共用邊界

- `MarketDataService.sync_daily_prices()` 新增可選 `start_date/end_date/fetch_prices`，既有 `days=` 呼叫保持原行為。第三階段才啟用嚴格範圍、先抓完並驗證再原子寫入的路徑。
- 複用 FinMind client、行情 repository、股利及還原算法。原始 `Trading_money` 寫入 nullable turnover；未提供時不推估，已存在金額也不因缺值被覆蓋。
- 股利查詢日期依 FinMind 的權利分派基準日，與除息日不同。第三階段以所需區間前後各 31 日查詢，再以實際除息日限定寫入；未來除息事件不套入目前價格。本次以 2330、0050 實際 API 回應核對，配息事件均可取得。欄位定義見 [FinMind 股利政策表](https://finmind.github.io/tutor/TaiwanMarket/Fundamental/)。
- 新輸入無效或還原後產生無效正價，整個範圍寫入 rollback。MySQL deadlock/lock timeout 最多重送寫入 transaction 3 次，使用已抓回的資料；不重試 FinMind。共享行情 unique key 保持不重複。
- 覆蓋紀錄包含已查區間及來源存在的日期，已確認沒有日K的停牌／上市前缺口不會每次重抓；來源成功但省略的日期視為來源確認無資料。來源事後修正已確認的舊缺口，目前沒有強制重抓入口。資料列被刪或變無效可再次初始化修復。
- 初始化使用 shared `history_days`：依各條件參數，月K最長週期加 3 個月及日曆換算；日K各期間總和乘 3，至少 180 日。無固定 3/5 年；新戰法需沿用可描述回看需求的 condition 介面。
- 指標值直接由既有 condition 的 `ConditionResult.indicators` 輸出，engine 原樣傳遞；指標鍵採 `condition_id.metric`。MA／布林、EMA、KD、MACD、量比均有值，不解析中文 reason、不在前端重算。

`FINMIND_SCAN_REQUESTS_PER_MINUTE=4`，所有第三階段對 FinMind 的價格與股利 API 共用 paced limiter，沒有 burst，預設相隔至少 15 秒。`MARKET_SCAN_WORKERS=5`。冷啟動先保留一個間隔，避免瞬間突發。此 budget 不包含階段一、二及同 IP 其他工具，遇來源配額限制記錄逐股失敗，下一任務才處理。

部署限制為單 backend replica、單 Uvicorn process；Dockerfile 明示 `--workers 1`，Compose replicas=1。MySQL `stock_tool_market_scan` named lock 在接受請求前取得，整個任務持有，進度／發佈前檢查仍持有；避免 auto/manual/init 競態。Stage2 使用另一個 `stock_tool_backtest`，不建立跨階段互斥。

## 發佈、狀態與計數

候選每列為 ticker×rule_id，正常命中之外不製造新候選。成功評估移除舊命中及未選戰法列，再寫入目前命中；不符合則不寫回。失敗或資料不足只保留該股票×戰法的舊列，分別標 `stale`、`insufficient_history`。整股沒有成功戰法時，舊未選戰法列也保留但標 stale。

全部計算、來源請求在發佈 transaction 外。發佈同時更新候選、供伺服端查詢的數值指標表、最新批次 metadata、scan task 完成狀態；任何 SQL／JSON 錯誤 rollback，不暴露半成品。批次 fatal error 或進程被終止，不改已發佈候選。逐股全失敗且任務正常收尾時，仍發佈失敗批次，把相關舊列改異常。

正常本次命中可以帶 `olderQuote=true`，表示實際有效日K落後 1–5 個交易日。這與「本次沒成功評估而沿用舊結果」的 stale 不同。預設 status=normal；摘要 normalCount/abnormalCount 分開。

`succeeded` 為本次至少成功評估一個戰法的不同標的數；`failed`、`insufficient` 分別計算至少一個戰法失敗／不足的不同標的數。三者可能重疊，不能相加當總數；UI 有說明。`processed` 每股只加一次，候選命中列數獨立統計。

只有最新 scan 與 initialize 兩筆任務；每次啟動清掉該類別舊錯誤，不保留完整任務歷史。初始化成功／部分／失敗依下載後可用戰法的評估結果判定；新上市而月K不足會列不足，不假裝已具備長週期資料。

## 資料表與檔案

Migration：`mysql/init/008_market_scan.sql`，可重複執行。新增 `stock_price_daily.turnover DECIMAL(22,2) NULL`。

| 表 | 用途 |
|---|---|
| `market_scan_instruments` | TWSE 種類、上市日、active 名單 |
| `market_scan_settings` | 單筆自動設定與當日 attempt claim |
| `market_scan_tasks` | scan / initialize 最近任務各一筆 |
| `market_scan_errors` | 最近任務逐股／逐戰法錯誤，查詢有分頁 |
| `market_scan_coverage` | 各標的已確認區間、實際資料日期 |
| `market_scan_candidates` | 最新命中／異常舊列；ticker/rule unique 與必要索引 |
| `market_scan_indicators` | candidate×指標名稱的數值索引；一般新增 condition 指標不需改 schema |
| `market_scan_publication` | 最新已發佈批次 metadata |

主要程式：`backend/app/market_scan/` 的 universe/data/rate_limit/worker/service/publication/router/schemas/models/coordination；共用 FinMind、market_data、conditions、rules/evaluation 增量延伸；scheduler/main 接入；frontend `features/market-scan/`、路由、導覽、CSS。沒有修改舊候選粗篩邏輯來代替新掃描。

## API

實際 backend 路徑如下，瀏覽器經 Vite/Nginx 加 `/api` 前綴；camelCase schema 可在 OpenAPI 查閱。

| 方法／路徑 | 行為 |
|---|---|
| GET / PUT `/market-scan/settings` | enabled、ruleIds，可保存空集合；回傳 worker／額度 |
| POST `/market-scan/initialize` | `{ruleIds:[...]}`，202 batchId，互斥 409 |
| POST `/market-scan/run` | 同上，空手動集合 422；省略 ruleIds 採已保存設定 |
| GET `/market-scan/tasks` | 最新 scan / initialize，時間、進度、警告 |
| GET `/market-scan/summary` | 最新發佈 metadata，尚無資料回 null |
| GET `/market-scan/candidates` | page/pageSize，預設 1/50，上限 page 10000、pageSize 200 |
| GET `/market-scan/errors` | kind=scan/initialize，page/pageSize，上限同上 |
| GET `/market-scan/indicators` | 已存在的指標名稱，供篩選下拉選單 |

候選 query：`search, kind, ruleId, priceDate, minPrice, maxPrice, minVolume, minTurnover, indicator, indicatorMin, indicatorMax, status, sort, direction`。`sort` 為白名單：ticker/stockName/kind/ruleId/close/priceDate/volume/turnover/scannedAt/status/indicator；指標排序必須選 indicator。無量能／金額預設門檻。缺成交金額回 null，若設定 minTurnover 則排除 null，不推估。

## 啟動、通知與測試

操作及 migration 指令見根目錄 README。變數範本為 `config/backend.env.example`。`008` 已在本地 MySQL 套用兩次驗證重複部署；後端已重建，本地 Vite API 代理確認 7 個 GET 端點皆 200。

通知的 Bot/Chat ID 沿用既有環境。全成功「全市場掃描完成」；部分「掃描完成，部分資料處理失敗」；全失敗「全市場掃描失敗」，均含台北完成時間。不包含股票列；發送失敗只追加 task warning，避免把含 Bot token 的 HTTP URL 寫進警告。

實際驗證紀錄：

| 檢查 | 結果 |
|---|---|
| `DB_PASSWORD=test /tmp/stock-stage1-venv/bin/python -m pytest -q`，cwd backend | 129 passed，涵蓋階段一、二回歸與新增 Stage3 情境 |
| `/tmp/stock-stage1-venv/bin/ruff check backend` | 通過 |
| `npm run build -- --outDir /tmp/stock-stage3-build`，cwd frontend | tsc -b、Vite build 通過；既有大 bundle 警告仍在 |
| `npx eslint .`，cwd frontend | 通過 |
| 手機 390px／桌面 1280px Playwright 實際瀏覽器 | 無畫面橫向溢出、無 JS error；空戰法／busy 禁用、3 秒輪詢後停止、舊結果可讀、完成刷新與重新整理保留篩選排序頁碼，手動不保存自動設定 |
| MySQL temporary-table 原生 SQL 檢查 | 範圍同步、還原價、原始成交金額、null 不覆蓋、無效行情 rollback、候選原子發佈與 rollback 通過；不更動持久資料 |

MySQL 檢查腳本保留於 `backend/tests/manual/check_market_scan_mysql.py`，可在 backend 環境以 `PYTHONPATH=. python tests/manual/check_market_scan_mysql.py` 執行。它只建立連線內 temporary tables，結束連線即釋放。

Pytest 使用暫存 SQLite 與 Mock/RESpx；TestClient 在目前 sandbox 會阻塞，已於獲准的 sandbox 外執行。前端未新增 Vitest，瀏覽器驗證腳本置於 `/tmp/stock-stage3-browser.cjs`，使用 mock 掃描 API，未觸發實際批次或 Telegram。

## 尚未實際驗證與已知限制

本階段指定的掃描工作流程已接線；本次未執行 1,326 檔真實完整初始化／掃描，也未實發 Telegram 或等到真實 19:00 排程。完整外部資料品質與耗時仍需第一次實際執行觀察。官方名單下載與解析、MySQL migration、原生 SQL、Vite API、排程／通知控制流程均已驗證。

預設 4 req/min 下，整個市場每股兩次 API 約 11 小時；首次初始化可能更久，視缺口段數而定。這是共享額度的預期結果；使用者可依實際來源額度調整變數。API quota 失敗不自動重試。

既有還原算法處理股利與增資；ETF 分割／反分割、減資等其他企業行動尚未納入。第三階段依需求共用此算法，沒有另外建立另一套還原邏輯；包含此類事件期間的長週期指標仍有資料口徑限制，後續需另行擴充共用行情模組。

歷史來源成功省略日期視為無行情，目前不提供強制刷新已確認的歷史空白；若供應商事後修訂舊資料，需要維護性重置該標的 coverage 再初始化，不能刪除股價歷史。未來擴充多 backend process/replica 必須先換分散式 rate limiter 與獨立 scheduler，目前不支援。

WSL 的 Windows Docker credential helper 此次不可用；改用僅本次建置的 `/tmp/stock-stage3-docker/config.json` 空 auths 設定匿名拉取公開映像，未改原本 Docker 設定。
