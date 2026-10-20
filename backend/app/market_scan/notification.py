"""Plain-text summaries for one published market scan."""

import json
import re
from itertools import groupby
from zoneinfo import ZoneInfo

from app.alerts.notification import MESSAGE_LIMIT, _shorten, _text_size


def _pages(lines):
    # Reserve enough room for every possible continuation heading before packing.
    reserve = _text_size(f"全市場掃描結果（續 {len(lines)}/{len(lines)}）\n")
    pages, current, size = [], [], 0
    for line in lines:
        added = _text_size(line) + bool(current)
        if current and size + added > MESSAGE_LIMIT - (reserve if pages else 0):
            pages.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += _text_size(line) + (len(current) > 1)
    if current:
        pages.append("\n".join(current))
    return [
        page if i == 1 else f"全市場掃描結果（續 {i}/{len(pages)}）\n{page}"
        for i, page in enumerate(pages, 1)
    ]


def _turnover(value):
    # Below 100 million, "0.0 億" hides the difference between 5 million and 50 million.
    if value is None:
        return "—"
    if value >= 100_000_000:
        return f"{value / 100_000_000:.1f} 億"
    return f"{value / 10_000:,.0f} 萬"


def _reason(text):
    # Exception class names mean nothing to the reader of a Telegram message.
    return _shorten(re.sub(r"^\w+(Error|Exception): ", "", " ".join(text.splitlines())), 120)


def messages(task, candidates, errors, continuing):
    baseline = str(task.baseline) if task.baseline else "—"
    finished = (
        task.finished_at.replace(tzinfo=ZoneInfo("UTC"))
        .astimezone(ZoneInfo("Asia/Taipei"))
        .strftime("%H:%M")
    )
    timing = f"基準日 {baseline}｜完成 {finished}（台北）"
    result = []
    if task.status in ("completed", "partial_completed"):
        label = "全市場掃描完成"
        if task.status == "partial_completed":
            label += "（部分失敗，明細見下一則）"
        lines = [
            f"{label}｜{timing}",
            f"進場事件 {len(candidates)} 筆（延續中 {continuing} 筆未列入）",
        ]
        if not candidates:
            lines.append("今日沒有進場事件")
        ordered = sorted(
            candidates,
            key=lambda c: (c.rule_id, c.turnover is None, -(c.turnover or 0), c.ticker),
        )
        for _, group in groupby(ordered, key=lambda c: c.rule_id):
            rows = list(group)
            lines.extend(["", f"【{rows[0].rule_name}】{len(rows)} 筆"])
            for row in rows:
                close = (
                    format(row.close, "f").rstrip("0").rstrip(".")
                    if "." in format(row.close, "f")
                    else str(row.close)
                )
                turnover = _turnover(row.turnover)
                parts = [f"{row.ticker} {row.stock_name}", f"收 {close}", f"成交 {turnover}"]
                evidence = row.reason + json.dumps(row.indicators, ensure_ascii=False)
                parts.extend(
                    label
                    for label, original in (
                        ("突破上軌", "突破布林上軌"),
                        ("觸及上軌", "觸及布林上軌"),
                    )
                    if label in evidence or original in evidence
                )
                if row.older_quote:
                    parts.append(f"較舊行情 {row.price_date:%m/%d}")
                lines.append("｜".join(parts))
        result.extend(_pages(lines))

    failures = {}
    insufficient = set()
    for error in errors:
        if error.status in ("stale", "failed"):
            failures.setdefault(error.ticker, error.reason)
        elif error.status == "insufficient_history" and error.ticker:
            insufficient.add(error.ticker)
    if failures or task.status == "failed":
        lines = [
            f"全市場掃描失敗｜{timing}"
            if task.status == "failed"
            else f"處理失敗 {sum(ticker is not None for ticker in failures)} 檔｜基準日 {baseline}"
        ]
        # Task-level errors have no ticker and still need a visible explanation.
        if None in failures:
            lines.append(_reason(failures[None]))
        stocks = [(ticker, reason) for ticker, reason in failures.items() if ticker is not None]
        lines.extend(
            f"{ticker} {_reason(reason)}"
            for ticker, reason in stocks[:20]
        )
        if len(stocks) > 20:
            lines.append(f"其餘 {len(stocks) - 20} 檔見網頁錯誤列表")
        if insufficient:
            lines.append(f"資料不足 {len(insufficient)} 檔（未逐一列出，見網頁錯誤列表）")
        result.append("\n".join(lines))
    return result
