# 階段四交付：批次行情、訊號追蹤與回測成本

首批依使用者縮限範圍實作 07 規格的 A，後續依指示完成 C（見下節）。B 候選績效追蹤已完成程式與本機部署，驗證見交付文件末節。全市場自動排程保持關閉；18:00 觀察清單排程與其 FinMind 資料來源維持原狀。

## 已完成

- MI_INDEX 依欄位名找表，驗證來源日期、OHLCV、成交金額，成交量單位為股。無成交與無效列分開處理。
- 每日最多下載近 6 個交易日；初始化依戰法回看期按日期補缺，已有有效列重用。工作程序只讀 DB 評估，不逐檔下載價格。
- TWT49U 日常查一次、初始化按月查詢；只對缺股利事件的標的呼叫 FinMind，事件不一致列逐股警告。
- 單日行情、還原價、資料版本與 coverage 同一交易。沿用原還原算法；新事件或歷史修正重算該股票歷史，單純追加日期只算新增列。
- 所有 TWSE／ISIN 共用間隔，預設 3 秒；FinMind token 使用 Bearer header，空值維持匿名。來源錯誤不重試，不改用 FinMind 逐檔行情備援。

## 主要檔案與部署

`data_source/twse_client.py` 是共用 HTTP 與解析入口；`market_scan/batch_data.py` 協調股利、日期下載與 coverage；`MarketDataService.import_market_day()` 負責原子寫入與還原；`MarketScanManager` 在 worker 前完成批次準備。既有任務 API、鎖、原子候選發佈與通知流程維持。

`mysql/init/009_stage4.sql` 新增 `market_scan_batch_coverage` 及 `stock_price_daily.trade_date` 索引，不修改排程開關。已在本地 MySQL 連續套用兩次成功，並重建 backend。

新增 `TWSE_MIN_REQUEST_INTERVAL_SECONDS=3`，必須為有限正數。`FINMIND_SCAN_REQUESTS_PER_MINUTE=4` 不變；已有 `FINMIND_API_TOKEN` 現在使用 [FinMind 官方 Bearer header 方式](https://finmind.github.io/login/)。額度由使用者依實際方案調整。

## 驗證

後端 `DB_PASSWORD=test /tmp/stock-stage1-venv/bin/python -m pytest -q --disable-warnings`：146 passed。新增 12 個案例涵蓋解析、股數單位、逐日補缺、確認無行情、無效列重補、單日 rollback、還原計算、舊行情評估、事件差異、共享節流及 token。

`ruff check backend`、前端 `npx tsc -b`、`npx eslint .`、`npm run build -- --outDir /tmp/stock-stage4-build` 通過。Build 有既存 bundle 超過 500 kB 提示，沒有編譯失敗。此次前端僅更新初始化說明，未新增 Vitest 或績效介面，未另外做 390px／1280px 瀏覽器人工驗證。

2026-10-15 本地真實手動掃描，基準日 2026-10-14，batch `d39fb337-dad9-48a9-a53e-e689fb0baeff`。使用現有 `MarketScanManager` 與 MySQL 任務鎖，通知器替換成 Mock，未實發 Telegram。

| 項目 | 實測 |
|---|---|
| 上市普通股／ETF | 1,326 檔，全數處理 |
| 總耗時 | 318.7 秒，含交易日／名單準備與評估 |
| 批次資料階段 | 183.0 秒 |
| MI_INDEX／TWT49U／FinMind | 6／1／12 次；FinMind 僅股利 |
| 成功／失敗／資料不足 | 23／4／1,305；依每檔各戰法狀態計數，可重疊，不可相加當總數 |
| 正常命中 | 19 筆股票 × 戰法 |
| 任務狀態 | partial_completed |
| 自動排程 | enabled=false，未修改 |

6 個日期為 10/06、10/07、10/08、10/12、10/13、10/14，已寫入行情與 coverage。2330、0050 與固定亂數抽取普通股 2062、1342、3094 的 10/14 OHLC、volume、turnover 共六欄，與 FinMind 逐欄差異皆為 0；這 5 次抽查請求另外計算，不包含掃描的 12 次股利請求。

失敗原因：00625K、00707R、1589 沒有有效日 K；2317 於 2025-07-30 有既有無效歷史行情。大量資料不足來自尚未完整初始化，本次日常掃描依規格只補近 6 個交易日，不自行補全歷史。沒有來源失敗或股利不一致警告。


## 限制

尚未執行完整三年初始化；約 40 分鐘只代表 750 日乘上 3 秒的行情節流估算，未包含股利 API、HTTP 與資料庫時間。也未啟用或驗證真實 19:00 自動排程。初始化完成仍須自行按掃描。

TWSE 無本專案可依賴的 SLA，可能回傳 HTML 封鎖頁或未發布資料；記警告後沿用最多落後 5 個交易日的規則。同一基準日再次掃描會重用有效行情，不自動偵測來源事後修訂。未處理減資／分割還原，也未新增上櫃行情。績效追蹤後續已完成，見末節。

本次未 commit、push，未更動排程設定。

## 2026-10-15：拆分初始化與股利整段查詢

使用者中斷首次初始化後，改成兩個獨立操作：

1. 「下載歷史行情」：`POST /market-scan/initialize`，`mode: "prices"`（預設）。只依日期補 MI_INDEX，不呼叫 TWT49U／FinMind 股利。
2. 「補齊歷史股利」：同一 API，`mode: "dividends"`。先按月查 TWT49U，彙整各股票所有缺漏事件，再每檔一次查最早至最晚缺漏日；保留原有前後 31 日重疊。完成後重算該股票還原價，不補行情、不啟動掃描。

兩者共用原初始化任務槽、互斥鎖與錯誤列表；不自動重啟初始化或開啟全市場排程。未提供 mode 的舊呼叫現在只下載行情。掃描仍補近 6 個交易日行情與股利，但股利也按股票合併查詢。

新增 010 migration 與 `DividendCoverage`。所有 TWSE 月份查詢成功且預期事件齊全的股票才寫入核對期間；缺事件的股票保留未完整狀態。全市場 worker 要求核對期間涵蓋本次所選戰法回看期，否則回傳 `insufficient_history`／「還原資料未完整」，不產生正常命中。既有股利資料可重用，但沒有完整性紀錄仍需手動核對。此限制沒有改動觀察清單與回測。

行情初始化的成功代表行情資料準備完成，不代表戰法通過。來源錯誤、股利缺漏列在錯誤／警告，初始化狀態可為 partial_completed；股票評估只在掃描操作執行。進度以「股利補齊 N/M 檔」呈現，避免只看評估計數 0/1326。

這次調整解決同一檔按月重複呼叫的問題，並沒有取消 FinMind 每分鐘 4 次節流。若有 1,000 檔缺股利，仍約需 4 小時 10 分鐘加網路、核對及還原時間。使用者需自行決定何時執行兩項初始化。

本地驗證：010 已連續套用兩次成功，backend 已重建，經 Vite proxy 的 tasks API 回傳 200；初始化仍為 interrupted、全市場排程仍為 false，沒有啟動長任務。抽查 2330：2024-04-28～2026-10-14 的證交所事件共 10 筆，FinMind 單次整段查詢回傳對應 10 筆，最早 2024-06-13、最晚 2026-09-16，缺漏 0。此為單一標的抽查，不保證全部標的無差異，因此正式流程仍逐一核對事件日期。

前端 TypeScript、ESLint、build 及後端 Ruff 通過。新增測試涵蓋純行情不查股利、跨月合併為單檔一次請求、缺股利不發佈正常命中，以及來源失敗／FinMind 缺事件不能寫完整性紀錄。未實發 Telegram、未重新啟動全市場初始化或修改自動排程。

本次調整後最終後端回歸：`DB_PASSWORD=test /tmp/stock-stage1-venv/bin/python -m pytest -q --disable-warnings`，151 passed（27.96 秒）。

## 2026-10-15：階段四 C 回測成本與 0050 基準

已完成共用 TradingCosts 模組、成本設定、回測淨值主統計與毛值並列、未平倉假設賣出淨值、0050 逐筆基準／平均超額／實際期間買進持有報酬，以及成本快照與舊結果相容處理。此為 C 交付當時紀錄；B 後續已完成，見末節。

淨報酬扣買賣各一次手續費與賣出稅；普通股／ETF 稅率由 market_scan_instruments.kind 決定，未知採普通股並顯示警告。所有成本由接受任務時的快照決定。0050 整批只準備一次，即使不在觀察清單也可使用，沿用 DB 優先補缺流程；失敗回傳空基準，不中止策略回測。逐筆基準需相同日期開盤資料，買進持有需實際起訖日開／收盤，缺失回傳 null，不順延日期。

`011_backtest_costs.sql` 新增 task.context_json；結果仍使用既有 JSON，schemaVersion=2。舊結果顯示「需重新回測」，不混入淨績效彙總。淨勝率、平均、複利、最大回撤及獲利因子使用相同原有交易排序，只將報酬改為淨值。毛指標另外保存；0050 不扣成本。跨股票複利不代表資金配置或實際投資組合績效。

新增設定：TRADE_FEE_RATE=0.001425、TRADE_FEE_DISCOUNT=1.0、TRADE_TAX_RATE_STOCK=0.003、TRADE_TAX_RATE_ETF=0.001。折扣需大於 0 且小於等於 1，各比例須為有限非負且小於 1，合計賣出成本不能達 100%。未模擬最低手續費 20 元、滑價、當沖減半稅率或股利再投入。原有減資／分割還原限制仍存在，可能影響含分割期間的 0050 基準。

前端顯示成本快照、毛／淨績效、逐筆 0050／超額報酬，以及實際期間 0050 買進持有值。未新增 Vitest。此環境沒有瀏覽器工具，本次未執行 390px／1280px 瀏覽器人工驗證；以 TypeScript、ESLint 與 build 驗證。

C 驗證結果：後端完整 pytest 163 passed（27.91 秒），Ruff、前端 TypeScript／ESLint／build 通過；build 仍有既存超過 500 kB bundle 提示。成本測試涵蓋股票／ETF、折扣、非法比例、毛正淨負、未平倉估值、0050 同日對齊與缺資料、整批僅準備一次基準、快照保存及舊結果不混入淨彙總。011 在本地 MySQL 連續套用兩次成功，backend 已重建，Vite proxy 的 `/api/backtests/latest` 回傳 200。未啟動真實長時間回測；初始化保持 interrupted、全市場自動排程保持 false。未實發 Telegram，未 commit／push。
## 2026-10-15：階段四 B 與交付收尾

A、B、C 程式已完成並部署本機。完整外部資料驗證仍由背景流程執行，不能把本節的自動化測試通過解讀為全部資料已補齊。

| 項目 | 結果 |
|---|---|
| 訊號保存 | 正常命中與候選同交易發佈；首次快照不被同日重跑覆寫，非命中不刪歷史 |
| 後續報酬 | 預設 1／5／10／20 交易日，下一有效日開盤進場，成本快照、0050、超額與最大不利幅度；只讀 DB 分批回填 |
| API／前端 | 彙總與分頁明細、日期／種類／成交金額／較舊行情篩選、樣本不足與無資料顯示 |
| Migration | 012 在本機 MySQL 連續套用兩次成功，backend 已重建；部署日為 2026-10-15，API 經 Vite proxy 回傳 200 |
| 設定 | 補上 `SIGNAL_TRACKING_HORIZONS=1,5,10,20` 範本；調整只影響新訊號 |

補齊過程修正三個問題：績效明細 JSX 多一個右括號造成前端無法編譯；設定測試繼承真實 Telegram 環境變數；行情重算把未變動的兩位小數價格當成浮點差異再次寫入。還原價現在依 NUMERIC(10, 2) 精度比較，並略過補入日之後沒有已知除權息事件的缺漏日重算。已有列的修正與會影響除權息係數的補值仍重算，沒有替換還原公式。

最終後端以一次性 Compose 容器掛載工作目錄驗證，明確設定 `TELEGRAM_BOT_TOKEN=`、`TELEGRAM_CHAT_ID=`、`DB_HOST=127.0.0.1`、`DB_PASSWORD=test`，避免接觸真實通知與開發 DB。`python -m pytest -q --disable-warnings`：179 passed，96.84 秒；`ruff check .` 通過。新增回歸案例涵蓋相同精度不重寫、歷史補值有／無後續股利的價格正確性。首次未清空通知設定的測試曾實發一次測試 Telegram；之後已修正測試設定隔離，不得將本次所有驗證描述為零外部通知。

前端 `npx tsc -b`、`npx eslint .`、`npm run build -- --outDir /tmp/stock-stage4-build` 通過；仍有既存 bundle 大於 500 kB 提示。Playwright 已驗證 390px 與 1280px：真實空樣本、以瀏覽器暫存 fixture 顯示績效與樣本不足、展開明細、下一頁、篩選後回到第一頁，以及真實回測成本頁。無 pageerror、無整頁橫向溢出。瀏覽器使用 Docker 唯讀代理載入前端，因宿主機 localhost 轉發埠會重設連線；fixture 未寫入 DB。截圖在宿主機 `/tmp/stock-stage4-browser/`。

真實回測批次 `4c0ce372-3ecf-40a8-ba60-7e7f9a1bc241` 已跑完 26 檔，23 成功、3 失敗，產生 46 筆股票 × 戰法結果。3711、2317、2330 因同時執行全市場歷史初始化而遇到 MySQL 1205 鎖等待逾時。此結果僅證明真實回測路徑已執行，不能記為全部通過。後續驗證改為依序執行，避免競爭相同行情列。

背景驗證流程先補缺漏行情，再補股利，接著以替代通知器執行手動掃描，最後重跑觀察清單回測。全市場自動排程維持 `enabled=false`；沒有為驗證開啟 19:00 排程。流程不重試失敗來源，失敗或中斷會保存原因；部分成功仍會保存逐股問題供後續判讀。不能藉由增加節流額度把股利補齊時間估成純行情下載時間。

本機 backend 容器內 `/tmp/stock-stage4-validation.json` 每 30 秒保存當前階段、任務進度與已結束步驟，完成後保存訊號筆數、各報酬狀態、回測結果與前後排程設定。讀取方式：

```sh
cd config
docker compose -f docker-compose.yaml -f docker-compose.dev.yaml exec -T backend \
  cat /tmp/stock-stage4-validation.json
```

這是本次驗證的單次背景流程，容器重建後不自動恢復。行情與股利的已提交資料仍保留，可從缺漏處另行啟動。未 commit／push。ETF 分割／反分割、減資、滑價與最低手續費仍不在本階段範圍。

## 2026-10-19：觀察期定義修正

觀察期 N 改為進場日之後第 N 個市場交易日收盤，即進場日 index + N。觀察期 1 為進場當日開盤買、下一個市場交易日收盤賣；停牌仍沿用到期日以前最後有效收盤，最大不利幅度仍涵蓋進場日到出場估值日。前端、README 與整體文件已同步。

日曆不完整時仍先計算各列狀態：pending 保留原原因，其餘結果改為 unavailable「交易日曆不完整」，不保存報酬值。測試涵蓋跨週末出場、未到期與等待進場、缺日曆、已到期且有／無 0050 行情，以及補齊後恢復計算；已完成結果仍不重算。未修改 migration、排程或既有 DB 資料。

驗證使用 `/tmp/stock-venv`，以 `python3 -m venv /tmp/stock-venv` 建立，並在 backend 執行 `/tmp/stock-venv/bin/pip install -r requirements-dev.txt` 安裝依賴。修正前觀察期案例 2 failed、日曆案例 3 failed，均重現目標問題。修正後在 backend 執行 `DB_PASSWORD=test TELEGRAM_BOT_TOKEN= TELEGRAM_CHAT_ID= /tmp/stock-venv/bin/python -m pytest -q --disable-warnings`：183 passed，4078 warnings，27.87 秒；`/tmp/stock-venv/bin/ruff check .` 通過。在 frontend 執行 `npx tsc -b && npx eslint .` 通過。
