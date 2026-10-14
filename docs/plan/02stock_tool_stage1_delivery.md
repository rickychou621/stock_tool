# 階段一：觀察清單每日自動更新與評估

## 功能與流程

Asia/Taipei 交易日 18:00，後端 APScheduler 執行 `run_daily_watchlist()`。不呼叫全市場掃描或 Telegram，不保存每日戰法快照。

1. 讀取 DB 設定，停用或當日已嘗試則略過。查證交所 FMTQIK 當月實際交易日期；週末及未列入的日期不執行、不新增執行紀錄。
2. 鎖定設定列，再次確認啟用與日期，保存當日執行資格、最新摘要，並取得當下觀察清單及所選且啟用的戰法。初始 NULL 選擇表示所有已啟用戰法；使用者儲存空陣列代表只同步行情。
3. 最多 3 檔股票並行，每檔獨立 Session。重用行情服務同步完整歷史與股利並重算還原價格，歷史長度採所選戰法最大需求。未選戰法同步 365 天行情；股利沿用既有服務至少 730 天的範圍。
4. 驗證最新日 K 日期、全部原始及還原 OHLC 有效性、成交量非負，再透過唯一 RuleEvaluationService 執行判斷。任一條件資料不足，即使 OR 規則另一條件符合，也不覆寫該戰法的既有結果。
5. 成功結果寫入既有 watchlist_evaluations。失敗保留 JSON 與評估時間，以 data_version=-1 標記過期；理由保存錯誤歷史並顯示於最新摘要。無舊結果時維持尚未評估，不偽造未通過結果。

單檔有任一失敗即算失敗股票；其他可執行戰法仍可成功保存。未選戰法不覆寫，其舊結果仍可能因行情版本變動而過期。成功數表示更新及評估完成，不代表通過戰法。

## 排程可靠性

- 原有 Scheduler 骨架由 FastAPI lifespan 註冊、啟動與關閉。每日 cron 使用台北時區、max_instances=1、misfire_grace_time=30，入口另檢查僅 18:00 這一分鐘可執行。重啟後不排入過去工作。
- 設定列 last_attempt_date 在外部 API 與 Worker 開始前提交，防止同日重複處理，包括失敗後再次觸發。
- MySQL GET_LOCK 保護整批工作；不同後端程序不會同時執行。後端正常關閉會等候工作完成；非正常中斷時，重啟取得鎖後將 running 摘要標記失敗、追加批次錯誤，不補跑。
- FinMind 限流、網路錯誤與交易日來源錯誤不重試。交易日查詢失敗時記錄整批失敗，不猜測是否開市。
- 交易日依據：https://www.twse.com.tw/exchangeReport/FMTQIK?response=json&date=20261001 。已實際確認民國年日期格式；使用實際成交日可反映臨時休市，無需逐年手動維護假日。
- 限制：依賴證交所 18:00 前發布當日統計；若來源成功回應但尚未列出當天，當天將略過且不補跑。此來源不提供未來交易日預測。
- 無跨手動／排程的額外互斥，不更動戰法判斷。僅移除歷史區間原有 1000 天截斷，避免自訂長週期永遠無法取得足量資料。

## 資料庫遷移

沿用專案 mysql/init 順序 SQL，新增 `006_watchlist_schedule.sql`。實際專案未使用 Alembic。

| 資料表 | 用途 |
|---|---|
| watchlist_schedule_settings | 單列啟用狀態、戰法選擇與最後嘗試日期 |
| watchlist_schedule_latest | 僅一筆可覆寫的執行摘要及批次 ID |
| watchlist_schedule_errors | 永久保存錯誤、時間、股票與批次 ID；不依附 latest 外鍵 |

SQL 只建立新表及 INSERT IGNORE 初始設定，可重複執行，不刪除或重設原資料。已有 DB 必須先套用 006，單純重建 backend 不會重跑初始化 SQL。

```sh
cd ~/dev/ricky/stock_tool/config
docker compose -f docker-compose.yaml -f docker-compose.dev.yaml exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --default-character-set=utf8mb4 -uroot "$MYSQL_DATABASE"' < ../mysql/init/006_watchlist_schedule.sql
docker compose -f docker-compose.yaml -f docker-compose.dev.yaml up -d --build backend
curl -fsS http://localhost:5173/api/watchlist-schedule/settings
curl -fsS http://localhost:5173/api/watchlist-schedule/latest
```

## API 與前端

- `GET/PUT /watchlist-schedule/settings`：持久化設定。儲存時拒絕不存在或停用的戰法；排程開始前再次過濾已停用／刪除的戰法。
- `GET /watchlist-schedule/latest`：最近摘要，錯誤只查當次 batch_id。
- `GET /watchlist-schedule/errors?before_id=...&limit=50`：歷史錯誤，以 ID 游標往前查，每頁最多 200 筆。

觀察清單上方新增排程設定及最近摘要。畫面編輯值與已儲存值分開；只有 API 成功才更新已儲存狀態，失敗保留選擇。排程選取與現有手動評估選取分開，避免只想手動試驗卻修改每日設定。無輪詢、WebSocket；重新整理讀取執行結果。歷史錯誤以 API 查詢，本階段未新增歷史錯誤專頁。

## 驗證

2026-10-12 完成驗證：

- 後端完整 pytest：74 passed，包含原有 54 項與本次新增 20 項。Ruff 通過。測試使用隔離 SQLite、Mock API；HTTP 測試停用背景 Scheduler，避免接觸開發 DB。
- 前端 TypeScript、ESLint、Vite Build 通過。既有 dist 權限不足，改輸出 `/tmp/stock-stage1-build`；保留原 dist。Build 有約 504 kB bundle 提醒，非建置失敗。
- 瀏覽器檢查 390px 與 1280px：無水平溢出、無 pageerror；模擬 PUT 503 後選擇保留，成功儲存後重新整理設定維持。
- 本地 MySQL 已套用 006，重建及重啟 backend 後設定仍為 enabled=true、ruleIds=[1,2]。實際驗證兩個連線的 MySQL coordinator lock 互斥，以及 Vite proxy 的設定 API。
- 交易日期 API 已做一次真實唯讀查詢；未手動觸發排程，不更新股票或發 Telegram。尚待第一個交易日 18:00 的自然執行，屆時可由觀察清單查看摘要。

測試環境位於 `/tmp/stock-stage1-venv`；未建立專案 `.venv`。未 commit 或 push。

```sh
cd ~/dev/ricky/stock_tool/backend
DB_PASSWORD=test /tmp/stock-stage1-venv/bin/python -m pytest -q
/tmp/stock-stage1-venv/bin/ruff check .
cd ../frontend
npm run build -- --outDir /tmp/stock-stage1-build
npx eslint .
```
