# 階段二：歷史戰法回測與績效驗證

## 完成範圍

新增獨立 `/backtest` 戰法回測頁面。使用者勾選已啟用戰法後，對當下觀察清單股票執行最近三年回測；選取與每日排程互不影響。本階段未加入每日排程，未開發全市場掃描、圖表、匯出或 Telegram 通知。

後端以背景執行緒執行，關閉瀏覽器不影響任務。同時間僅接受一個回測任務，重複啟動回傳 409；固定三檔股票並行，各股票獨立 Session。MySQL connection lock 在接受任務前取得、直到整批完成才釋放，跨後端程序亦互斥。重啟發現已失去執行者的 running 任務時標記 interrupted，不自動續跑。

## 歷史訊號與成交口徑

1. `RuleEvaluationService.evaluate_bars()` 提供歷史輸入入口，最新評估與回測共用原本的條件判斷。未增加另一套戰法公式。
2. 訊號只傳入截至當日的有效日 K。月 K 使用當時已累積的當月行情，不取月底尚未發生的收盤價；這與現有月 K 評估口徑一致。
3. 訊號還原價依現有 `apply_adjustment()` 公式，僅納入當日以前已發生的除權息事件。遇到新事件重新調整歷史前綴，其餘日追加當日原始 K 棒。
4. 成交與持倉估值統一使用回測結束日基準的還原價格。此組價格不送入訊號判斷；不另加現金股利、不另模擬股利再投入。歷史價格若被資料商事後修訂，系統仍使用目前資料庫可取得版本，並非資料商逐日封存版本。
既有 EMA 黃金交叉以日 K 近似，回測也沿用日 K；不代表原規劃的盤中分 K 戰法。未接入券商歷史盤中資料。

5. 回測區間起始時為空倉，第一個可判斷且符合的日期即產生買進訊號；暖機資料只供指標，不建立區間開始前的持倉。首次、持續、失效、再次符合由共用引擎的逐日 is_met 決定，未另外定義戰法延續規則。

訊號完成後，下一個有有效 OHLC 且成交量大於零的交易日開盤成交；持續符合不加碼。停牌、無效開盤或零成交量順延，且不在無效行情日產生新訊號。同一股票與戰法最多一筆持倉。

期末待買進標記「未成交」；已持有而待賣出者維持「持有中／賣出未成交」。持有交易日數使用證交所交易日差，不含買進當日、含賣出日；停牌期間仍計入市場交易日。期末無當日有效價格時，以最後有效收盤估值並明列估值日期，不捏造收盤價。

## 資料準備

- 回測截止日：台北時間 18:00 前以昨日為上限，18:00 後可包含今天，再取可確認的最後一個交易日。最近三年之外加上各戰法最長暖機歷史。
- 優先讀取 MySQL。以證交所 FMTQIK 月成交日期確認應有交易日，排除週末、假日及舊 seed 中非交易日資料，不刪除原資料。
- 交易日期按月保存在 DB；已完整結束的月份重用。尚未完成的月份在日期或查詢範圍更新時重新確認。首次跨多年回測需要建立多個月份的日曆，可能較久；來源失敗會回報錯誤，不假造交易日。
- 日 K 不完整或既有還原欄位未齊全時，才呼叫現有 FinMind 同步服務。同步仍沿用既有完整區間、股利與還原流程，未新增增量同步。
- 成功抓取後保存請求範圍與實際回傳日期，已確認的上市前／停牌缺口不會在同範圍重複觸發同步；原先有資料而後來消失則再補齊。
- 有完整原始及還原欄位時沿用既有股利事件；目前沒有獨立的資料商股利完整性證明。上市日不另行推定，畫面顯示實際可計算期間。資料不足以暖機時回報股票失敗。
- 回測補資料會依既有同步服務更新行情版本，因此既有觀察清單評估可能顯示需重新評估。未修改階段一的排程規則、股票處理方式或設定。

## 績效與一致性

| 指標 | 計算口徑 |
|---|---|
| 勝率 | 正報酬已完成交易數／已完成交易數；零報酬不算勝 |
| 平均報酬 | 已完成交易報酬率的算術平均 |
| 複利累積報酬 | PRODUCT(1 + 單筆報酬率) - 1 |
| 最大回撤 | 已完成交易複利曲線相對先前高點的最大跌幅，初值為 1 |
| 獲利因子 | 正報酬率總和／負報酬率絕對值總和；無虧損時以文字呈現 |

按賣出日期、股票代號、買進日期排序已完成交易，確保同日交易排序一致。跨股票複利僅為比較指標，不是可實際配置的投資組合；最大回撤未包含持倉期間浮動損益。沒有已完成交易時勝率等指標為 null，前端顯示「無資料」；少於十筆時標記樣本不足。

每個股票的所有選定戰法、明細、統計與成功進度在同一筆 DB transaction 提交。失敗保留原成功結果並標記過期，本次整體績效只讀目前 batch_id 的成功結果。最新任務只保留一列，個股與戰法只保留最新成功結果，不保存歷次完整版本。

進度 API 讀輕量 summary，不載入全部逐日訊號。明細按頁取得，附 batch_id 檢查，結果換版時回傳 409，避免摘要與明細混用不同批次。任務剛開始時舊結果即標記過期；使用者可以看到舊結果，但不會混入本次總計。

## 主要檔案與 API

- `backend/app/backtest/`：任務協調、DB-first 資料準備、歷史模擬、績效與 API。
- `backend/app/rules/evaluation.py`：抽出共用歷史 K 棒評估入口，原 `evaluate()` 呼叫方式保留。
- `frontend/src/features/backtest/`：獨立頁面，執行中每三秒輪詢，完成／失敗／中斷後停止，提供篩選排序、逐筆交易與逐日狀態。
- `backend/tests/unit/test_backtest_simulation.py`、`backend/tests/integration/test_backtest_workflow.py`：新增驗收測試。

| API | 用途 |
|---|---|
| POST /backtests | 接受 ruleIds，啟動任務，回傳 202；忙碌時 409 |
| GET /backtests/latest | 最近任務、進度、當次整體及個股績效 |
| GET /backtests/results/{id} | 逐筆交易及逐日訊號，offset / limit 分頁，expectedBatchId 防止換版混讀 |

## Migration 與啟動

沿用 SQL 遷移，新增 `007_backtest.sql`，建立 backtest_latest_task、backtest_results、backtest_data_coverage、backtest_calendar_months。只新增表，不刪除既有資料。

```sh
cd ~/dev/ricky/stock_tool/config
docker compose -f docker-compose.yaml -f docker-compose.dev.yaml exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --default-character-set=utf8mb4 -uroot "$MYSQL_DATABASE"' < ../mysql/init/007_backtest.sql
docker compose -f docker-compose.yaml -f docker-compose.dev.yaml up -d --build backend
curl -fsS http://localhost:5173/api/backtests/latest
```

前端開啟 http://localhost:5173/backtest 。本地 007 已套用，backend 已重建；階段一 10/12 的原執行摘要維持 24 成功／2 失敗。

## 驗證與待確認

後端完整測試 91 項通過，包含階段一原有 74 項與階段二新增 17 項；Ruff、前端 TypeScript、ESLint、Vite Build 通過。前端輸出 `/tmp/stock-stage2-build`，避免既有 dist 目錄權限問題。Build 約 513 kB bundle 提醒不影響成功。

測試使用隔離 SQLite 及 Mock 外部 API。另以本地 MySQL 實測跨連線單任務鎖及 Vite proxy API。瀏覽器使用攔截模擬結果驗證：每三秒輪詢、完成後停止、切頁恢復、重複按鈕防護、股票／戰法篩選、績效排序與交易明細均通過。390px 手機及 1280px 桌面無水平溢出或 pageerror；移除攔截後，本地 API 的尚無回測結果畫面正常。

尚待使用者首次對真實觀察清單執行三年完整回測，核對個股訊號、除權息附近交易及績效；本次未為測試大量抓取真實 FinMind 資料，未發送 Telegram，未修改每日排程設定。未 commit 或 push。

```sh
cd ~/dev/ricky/stock_tool/backend
DB_PASSWORD=test /tmp/stock-stage1-venv/bin/python -m pytest -q
/tmp/stock-stage1-venv/bin/ruff check .
cd ../frontend
npm run build -- --outDir /tmp/stock-stage2-build
npx eslint .
```
