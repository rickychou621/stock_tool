# 後端規劃(FastAPI)

> 本文件聚焦後端實作細節,系統整體背景請參考 [overall.md](./overall.md)。此文件之後會針對開發過程持續調整。

## 1. 技術棧

- **語言/框架**:Python + FastAPI
- **ORM**:SQLAlchemy
- **資料驗證**:Pydantic(request/response schema)
- **排程**:APScheduler(於 backend process 內執行,不另開 worker 容器)
- **測試**:pytest + pytest-asyncio,搭配 `httpx.AsyncClient`/`TestClient` 做 API 整合測試,`respx`/`responses` mock 外部 HTTP 呼叫
- **程式碼品質**:Ruff(lint + format + import排序)、mypy/pyright(型別檢查)
- **容器**:`python:3-slim`(避免 alpine 造成 pandas/numpy 等科學計算套件編譯問題)

## 2. 架構風格:DDD-lite / Feature-folder

不採用完整版 DDD(不做 Aggregate Root、Domain Event、Bounded Context 這類重量級概念),但依業務領域切資料夾,取代傳統 MVC 依技術角色(model/view/controller)切資料夾的方式,讓同一功能的程式碼集中好找。

每個 feature 資料夾內部統一分工:

- `router.py`:FastAPI 路由,只負責接 request、呼叫 service、回應,不放商業邏輯
- `schemas.py`:Pydantic 的請求/回應格式
- `service.py`:商業邏輯,寫成不依賴 FastAPI/DB 的純邏輯,方便單元測試
- `models.py`:SQLAlchemy ORM 模型
- `repository.py`:包一層 DB 存取介面,對外只暴露語意化方法(如「取得某股票某區間價格」),內部才是 SQLAlchemy 實作細節

## 3. 資料夾結構

```
backend/
├── app/
│   ├── main.py                 # FastAPI 進入點
│   ├── core/                   # 共用:設定載入(pydantic-settings讀.env)、DB session、共用依賴(Depends)
│   ├── conditions/              # 條件庫:每個技術判斷的最小單位實作
│   │   ├── base.py              # 條件共同介面(抽象類別/Protocol)
│   │   ├── registry.py          # 條件註冊/查詢機制
│   │   ├── ema_cross.py         # 例:EMA黃金交叉
│   │   ├── bollinger_band.py    # 例:布林通道相關判斷
│   │   ├── kd_macd.py           # 例:KD/MACD相關判斷
│   │   └── volume_spike.py      # 例:爆量判斷
│   ├── rules/                   # 規則組合(使用者自訂的條件AND/OR組合)
│   │   ├── router.py / schemas.py / service.py / models.py / repository.py
│   ├── screening/                # 兩階段粗篩 + 候選池管理
│   │   ├── router.py / schemas.py / service.py / models.py / repository.py
│   ├── watchlist/                 # 持股觀察清單(手動維護,不受粗篩影響)
│   │   ├── router.py / schemas.py / service.py / models.py / repository.py
│   ├── alerts/                    # 告警觸發紀錄
│   │   ├── router.py / schemas.py / service.py / models.py / repository.py
│   ├── chart/                     # 線圖資料查詢(供前端畫圖用)
│   │   ├── router.py / schemas.py / service.py / repository.py
│   ├── data_source/               # 外部資料串接
│   │   ├── finmind_client.py      # FinMind API 封裝
│   │   ├── broker_client.py       # 券商即時API封裝(Shioaji/富邦)
│   │   └── notifier.py            # Telegram 推播封裝
│   ├── cache/                     # 快取抽象層(v1為記憶體實作,未來可替換為Redis)
│   │   └── cache_service.py
│   └── scheduler/                 # 排程任務註冊與執行(APScheduler)
│       ├── daily_jobs.py          # 每日粗篩、戰法二三批次評估
│       └── intraday_jobs.py       # 盤中候選池動態換股、即時規則評估
├── tests/
│   ├── unit/                      # 針對 conditions/、rules/ 的純邏輯測試,不需DB/網路
│   ├── integration/                # 針對 API endpoint、DB 讀寫的測試,需測試用DB
│   └── conftest.py                 # pytest fixture(含 dependency_overrides 設定)
├── pyproject.toml                  # Ruff/mypy/pytest 設定
└── requirements.txt (或 uv.lock)
```

## 4. 核心設計:條件庫 + 規則組合

### 4.1 條件(Condition)共同介面

每個條件需宣告:

- **所需資料規格**:時框(分K/日K/月K)、回看區間長度、更新頻率(即時/每日)
- **可調參數**:例如 EMA 週期、爆量倍數門檻、角度斜率臨界值 — 皆可由使用者於前端調整,不寫死在程式碼
- **評估邏輯**:輸入資料 → 回傳布林值或訊號(是否成立、觸發原因說明文字)

### 4.2 規則(Watch Rule)組合

規則本身是資料,不是程式碼,結構大致為:

```
規則:{
  名稱: string,
  啟用狀態: bool,
  邏輯運算子: "AND" | "OR",
  條件清單: [
    { 條件類型: string, 參數: JSON },
    ...
  ]
}
```

前端提供介面讓使用者勾選條件、設定參數、選擇邏輯運算子後存成一條規則,不需改動後端程式碼即可產生新的監控組合(例如「戰法一的EMA條件 + 戰法二的布林中軌條件」)。只有當需要全新技術指標(條件庫裡沒有的邏輯)時才需要新增程式碼。

### 4.3 混合頻率規則的評估方式

若一條規則同時包含即時類條件(如5分K的EMA交叉)與日頻條件(如日K布林中軌),則:

- 每日批次評估時,將日頻條件的判斷結果連同日期一併存入 DB(`daily_condition_cache`,詳見 [db.md](./db.md))
- 即時評估時,直接讀取當天已算好的日頻結果,與即時條件做 AND/OR 運算,不重複計算日頻邏輯

## 5. 排程任務規劃

| 任務 | 頻率 | 內容 |
|---|---|---|
| 每日粗篩 | 每日(收盤後或開盤前) | 全市場批次資料計算,產出候選池初始名單,計算所有日頻/月頻條件並寫入快取 |
| 盤中動態換股 | 可設定(預設5分鐘) | 快照輪詢全市場排行,汰換候選池中條件已失效的股票,上限可設定(預設10筆) |
| 即時規則評估 | 即時(隨券商API tick/K線推送) | 對候選池+持股清單訂閱的股票,評估所有啟用中且引用即時條件的規則 |

排程頻率、候選池上限等參數,設計為可由外部設定檔/環境變數調整,不寫死於程式碼中。

## 6. 快取抽象層

`cache/cache_service.py` 定義一個通用介面(get/set/delete,支援TTL),v1 以 process 內的 dict 實作。用途包括:

- 候選池、持股清單的即時查詢(避免即時迴圈頻繁查DB)
- 每日條件快取結果的暫存
- 告警防重複發送的標記(TTL到當天結束)

未來若 backend 擴展為多 worker 或需要 pub/sub 即時推播,替換此介面實作為 Redis 即可,不需更動呼叫端邏輯。

## 7. 測試策略

| 層級 | 測試對象 | 工具 | 是否需要真實依賴 |
|---|---|---|---|
| 單元測試 | conditions/ 的判斷邏輯、rules/ 的組合運算 | pytest | 不需要,純函式輸入輸出 |
| 整合測試 | API endpoint、DB讀寫 | pytest + TestClient/AsyncClient | 需要測試用DB(獨立測試用MySQL或SQLite) |
| 外部串接測試 | FinMind/券商API 呼叫與回應解析邏輯 | respx/responses(mock HTTP) | 不連真實外部服務 |

可測試性依賴以下設計:

- FastAPI 的 `Depends` + `app.dependency_overrides`,測試時替換 DB session、外部client
- Repository 介面讓單元測試可注入假資料,不需連真實DB
- 業務邏輯(service層)不依賴 FastAPI/DB,可直接單元測試

## 8. API 大致端點規劃(待細化)

- `GET /screening/candidates`:目前候選池
- `GET /watchlist` / `POST /watchlist` / `DELETE /watchlist/{ticker}`:持股清單CRUD
- `GET /rules` / `POST /rules` / `PUT /rules/{id}` / `DELETE /rules/{id}`:規則組合CRUD
- `GET /conditions`:條件庫清單(供前端組裝規則時選擇)
- `GET /alerts`:告警歷史紀錄
- `GET /chart/{ticker}`:線圖資料查詢

## 9. 待補充項目

- 各 API 的詳細 schema 定義
- 券商API(Shioaji/富邦)實際串接細節與訂閱數管理邏輯
- 條件庫的完整清單與參數規格

## 手動評估與通知接口

- `POST /rules/{id}/prepare?ticker=2330`：按選定戰法準備日K與股利事件。歷史範圍依參數與時框估算，上限 1000 個日曆天。更新失敗或沒有行情時回傳錯誤，前端不繼續評估。
- `GET /rules/{id}/evaluate?ticker=2330`：共用 `RuleEvaluationService.evaluate()`，回傳 `status`、`dataDate` 及各條件的 `dataSufficient`。它本身不更新行情、不發通知。
- `POST /screening/run`：掃描全部啟用規則與主檔啟用且已有行情的股票。回傳本次 `matches` 與無法評估的 `issues`，符合項目沿用當日告警去重；不呼叫 Telegram。
- `POST /alerts/notify`：接收 `alertIds`，每次最多 500 筆。僅發送資料庫已有告警，回傳 `sentIds`、`skippedIds`、`failedIds`。成功後標記 `is_notified`，後續重試略過成功項目。DB row lock 防止重疊請求同時送同一筆；外部發送成功但回應中斷或 DB commit 失敗時，仍可能在重試時重送。

新增觀察股票不下載行情、不評估；同代號已在觀察中時回傳既有項目。評估前準備行情需要已有股票主檔，未知股票回傳可讀錯誤。候選池粗篩與戰法掃描目前各自執行，並未串成兩階段管線。

## 觀察清單保存與多戰法 API

`GET /watchlist/evaluations` 回傳目前有效觀察股票的各戰法最新保存結果，含 UTC 評估時間、資料日期及 stale 標記。`POST /watchlist/{id}/evaluate` 接收 ruleIds，依最長歷史需求同步一次，呼叫既有 RuleEvaluationService 並保存各條結果，不發通知。行情同步失敗會保存失敗結果，不使用舊行情進行本次判斷。

`PATCH /watchlist/{id}` 接收 entryPrice、entryDate、notes、sector，只更新有提供的欄位；明確傳 null 可清除進場價／日期。sector 更新股票主檔，`GET /stocks/{ticker}` 同步回傳名稱與族群。

Stock.data_version 在開始寫入行情前遞增；因此行情或股利部分更新失敗時，既有結果也會失效。保存結果另外記錄戰法條件指紋；讀取時比對資料版本與條件指紋。只保存每組觀察項目／戰法的最新結果，不是完整評估歷史。
