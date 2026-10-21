from app.watchlist.notification import messages


def result(*, exited=False, close=296, ma=279.3, price=277.5, day="2026-10-20"):
    return {
        "exitTriggered": exited,
        "dataDate": day,
        # Same shape as a saved evaluation: no condition indicators, close inside protectiveStop.
        "protectiveStop": {"close": close, "price": price, "ma": ma, "tick": 0.5, "ticks": 3},
        "conditionResults": [
            {"conditionId": "entry", "role": "entry", "isMet": True, "reason": "不要顯示"},
            {
                "conditionId": "close_below_ma_days",
                "role": "exit",
                "isMet": exited,
                "reason": "連續 2 天收盤跌破月線",
            },
        ],
    }


def test_exit_and_next_day_prices():
    assert messages(
        [
            (
                "2330",
                "台積電",
                "戰法二：布林上軌區間",
                result(exited=True, close=2405.0, ma=2492.0),
            ),
            ("1303", "南亞", "戰法二", result()),
        ],
        failed=1,
    ) == [
        "觀察清單｜10/20 收盤｜2 檔\n"
        "【出場訊號】1 檔\n"
        "2330 台積電｜戰法二：布林上軌區間｜收 2405｜月線 2492｜連續 2 天收盤跌破月線\n"
        "【明日觸價價位】1 檔\n"
        "1303 南亞｜觸價 277.5｜月線 279.3｜收 296\n"
        "處理失敗 1 檔（見網頁）"
    ]


def test_no_exits_sorted_prices_and_latest_date():
    (text,) = messages(
        [
            ("2330", "台積電", "戰法二", result(day="2026-10-19", ma=279.34)),
            ("1303", "南亞", "戰法二", result(price=277.50)),
        ]
    )
    assert text.startswith("觀察清單｜10/20 收盤｜2 檔\n【出場訊號】今日無")
    assert text.index("1303 南亞") < text.index("2330 台積電")
    assert "月線 279.3｜收 296" in text
    assert "處理失敗" not in text


def test_no_protective_stop_sends_nothing():
    assert messages([], failed=1) == []
    assert messages([("2330", "台積電", "舊戰法", {"protectiveStop": None})]) == []
    assert messages([("2330", "台積電", "舊戰法", {})]) == []


def test_multiple_rules_count_one_stock_but_keep_each_row():
    (text,) = messages(
        [
            ("2330", "台積電", "戰法甲", result(exited=True)),
            ("2330", "台積電", "戰法乙", result(exited=True)),
            ("2330", "台積電", "戰法丙", result()),
        ]
    )
    assert text.startswith("觀察清單｜10/20 收盤｜1 檔")
    assert "【出場訊號】1 檔" in text
    assert "台積電｜戰法甲" in text and "台積電｜戰法乙" in text
    assert text.count("2330 台積電") == 3


def test_long_summary_pages_preserve_complete_rows():
    items = [(str(1000 + i), "股票", "戰法二", result()) for i in range(300)]
    pages = messages(items, failed=2)
    assert len(pages) > 1
    assert all(len(page.encode("utf-16-le")) // 2 <= 4000 for page in pages)
    assert pages[1].startswith(f"觀察清單（續 2/{len(pages)}）\n")
    lines = "\n".join(pages).splitlines()
    for ticker, _, _, _ in items:
        assert lines.count(f"{ticker} 股票｜觸價 277.5｜月線 279.3｜收 296") == 1
    assert pages[-1].endswith("處理失敗 2 檔（見網頁）")


def test_close_below_stop_is_marked():
    text = messages([
        ("6274", "台燿", "戰法二", result(close=1550, ma=1595, price=1580)),
        ("1303", "南亞", "戰法二", result(close=296, ma=279.3, price=277.5)),
        ("9999", "相等", "戰法二", result(close=100, ma=101, price=100)),
    ])[0]
    assert "6274 台燿｜觸價 1580｜月線 1595｜收 1550｜已低於觸價" in text
    assert "1303 南亞｜觸價 277.5｜月線 279.3｜收 296\n" in text + "\n"
    assert "9999 相等｜觸價 100｜月線 101｜收 100" in text and "收 100｜已低於觸價" not in text


def test_rule_three_exit_without_price():
    evaluation = {
        "exitTriggered": True,
        "dataDate": "2026-10-20",
        "protectiveStop": None,
        "conditionResults": [
            {"role": "premise", "isMet": True, "reason": "不要顯示"},
            {"role": "exit", "isMet": False, "reason": "不要顯示"},
            {"role": "exit", "isMet": True, "reason": "月K DIF=-1.20，MACD訊號線=0.30"},
        ],
    }
    expected = [
        "觀察清單｜10/20 收盤｜1 檔\n"
        "【出場訊號】1 檔\n"
        "2330 台積電｜戰法三：長波佈局｜月K DIF=-1.20，MACD訊號線=0.30\n"
        "【明日觸價價位】0 檔"
    ]
    item = ("2330", "台積電", "戰法三：長波佈局", evaluation)
    assert messages([item]) == expected
    del evaluation["protectiveStop"]
    assert messages([item]) == expected
    evaluation["exitTriggered"] = False
    assert messages([item]) == []


def test_mixed_rules_count_tickers_separately_in_each_section():
    no_price = result(exited=True)
    no_price["protectiveStop"] = None
    text = messages([
        ("2330", "台積電", "戰法三", no_price),
        ("2330", "台積電", "戰法二", result()),
        ("2330", "台積電", "另一出場戰法", result(exited=True)),
    ])[0]
    assert text.startswith("觀察清單｜10/20 收盤｜1 檔")
    assert "【出場訊號】1 檔" in text
    assert "【明日觸價價位】1 檔" in text
    assert text.count("2330 台積電") == 3
