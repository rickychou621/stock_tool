# 股票告警系統

FastAPI / React / MySQL 的台股追蹤工具。提供觀察清單評估、歷史回測及上市普通股／ETF 全市場掃描；行情使用 FinMind，交易日期與上市名單使用證交所資料。

## 啟動

開發模式使用 `config/` 下兩份 Compose 檔案。先依各 `*.env.example` 建立對應 `.env`，既有設定檔請保留。

```sh
cd config
docker compose -f docker-compose.yaml -f docker-compose.dev.yaml up -d --build
```

前端為 `http://localhost:5173`；API 一律透過 `/api` 代理。正式 Compose 使用 port 80。

新 MySQL volume 會執行 `mysql/init/`。既有 DB 不會自動執行新增 SQL；升級第三階段前，先確認 `006_watchlist_schedule.sql`、`007_backtest.sql` 已套用，再執行：

```sh
cd config
docker compose -f docker-compose.yaml -f docker-compose.dev.yaml exec -T db \
  sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --default-character-set=utf8mb4 -uroot "$MYSQL_DATABASE"' \
  < ../mysql/init/008_market_scan.sql
docker compose -f docker-compose.yaml -f docker-compose.dev.yaml up -d --build backend
```

`008` 可重複執行，新增第三階段資料表及可空的 `stock_price_daily.turnover`，保留原行情、回測與觀察清單。不要刪除 MySQL volume。

## 設定

`config/backend.env.example` 列出設定範本。DB 連線依本機環境填入；Telegram 完成通知需要 `TELEGRAM_BOT_TOKEN` 與 `TELEGRAM_CHAT_ID`。

| 變數 | 預設 | 用途 |
|---|---|---|
| `MARKET_SCAN_WORKERS` | `5` | 第三階段並行標的，正整數，最大 32 |
| `FINMIND_SCAN_REQUESTS_PER_MINUTE` | `4` | 所有第三階段 worker 共用，每次請求至少間隔 15 秒 |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | 空 | 缺少時記錄通知警告，不阻止掃描 |
| `DB_HOST/PORT/NAME/USER/PASSWORD` | 見範本 | MySQL 連線 |

階段三使用匿名 FinMind API。既有 `FINMIND_API_TOKEN` 設定尚未接入此 client，不會因為填入 token 自動提高額度。節流預設 240 次／小時；不保證涵蓋同 IP 其他程式的流量。階段一及回測可並行，實務上請錯開大量下載。

後端僅支援 **1 個 Uvicorn process、1 個 backend replica**，Compose 與 Dockerfile 已明示。節流在同一 process 共用；跨請求互斥另有 MySQL named lock。不要以多副本擴充目前排程服務。

## 操作

1. 在「全市場掃描」設定 19:00 的自動戰法與啟用開關，按儲存。預設啟用且使用所有已啟用戰法；空集合會略過。
2. 選擇本次戰法，按「初始化歷史行情」。依戰法回看期及暖機需要補缺，不會自動接著掃描。已有完整日K會重用，只補尚未確認的股利區間。
3. 按「開始全市場掃描」，或等待交易日 19:00。手動戰法不改動自動設定；關閉頁面後工作繼續。
4. 候選預設顯示正常命中；可查過期／歷史不足，並使用伺服端篩選與每頁 50 列分頁。重新整理只查 DB。

以約 1,300 檔、每檔股價及股利各一次估算，預設節流下全市場下載約需 11 小時，另加來源與運算耗時；已完整的區間會略過。5 個 worker 不會把共享額度乘以 5。初始化期間 19:00 掃描若衝突會略過，不排隊。缺歷史仍可掃描資料足夠的戰法。

觀察清單排程維持 18:00；全市場排程為 19:00，時區皆為 Asia/Taipei。依證交所實際交易日執行，不補跑；重啟只把未完成任務標成中斷。

完整實作、API、測試與限制見 [階段三交付文件](docs/plan/06stock_tool_stage3_delivery.md)。
