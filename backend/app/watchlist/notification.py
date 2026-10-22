"""Plain-text daily holdings summaries from saved evaluations."""

from decimal import Decimal

from app.alerts.notification import _shorten
from app.core.notification import _pages


def _number(value, *, ma=False):
    if value is None:
        return "—"
    number = Decimal(str(value))
    text = format(number, ".1f" if ma else "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def messages(items, *, failed=0) -> list[str]:
    rows = sorted(
        (
            item for item in items
            if item[3].get("state") and (
                item[3]["state"]["state"] == "EXIT"
                or item[3].get("protectiveStop") is not None
            )
        ),
        key=lambda item: (item[0], item[2]),
    )
    if not rows:
        return []
    dates = [row[3]["dataDate"] for row in rows if row[3].get("dataDate")]
    day = max(dates)[5:10].replace("-", "/") if dates else "—"
    exited = [row for row in rows if row[3]["state"]["state"] == "EXIT"]
    near = [row for row in rows if row[3]["state"]["state"] == "NEAR_EXIT"]
    pending = [row for row in rows if row[3]["state"]["state"] not in ("EXIT", "NEAR_EXIT")]
    lines = [f"觀察清單｜{day} 收盤｜{len({row[0] for row in rows})} 檔"]
    lines.append(
        f"【出場訊號】{len({row[0] for row in exited})} 檔" if exited else "【出場訊號】今日無"
    )
    for group, label in ((exited, "出場訊號"), (near, "接近出場"), (pending, "明日觸價價位")):
        is_exit = label == "出場訊號"
        if not is_exit and (group or label == "明日觸價價位"):
            lines.append(f"【{label}】{len({row[0] for row in group})} 檔")
        for ticker, name, rule_name, result in group:
            stop = result.get("protectiveStop")
            conditions = result.get("conditionResults", [])
            # Saved condition results have no indicators; protectiveStop carries the close.
            close = stop.get("close") if stop is not None else None
            parts = [f"{ticker} {name or ''}"]
            if is_exit:
                parts.append(rule_name)
                if stop is not None:
                    parts.extend([f"收 {_number(close)}", f"月線 {_number(stop['ma'], ma=True)}"])
                parts.extend(
                    condition["reason"]
                    for condition in conditions
                    if condition.get("role") == "exit"
                    and condition.get("isMet")
                    and condition.get("reason")
                )
            else:
                parts.extend(
                    [
                        f"觸價 {_number(stop['price'])}",
                        f"月線 {_number(stop['ma'], ma=True)}",
                        f"收 {_number(close)}",
                    ]
                )
                # A stop order at this price would fire at tomorrow's open.
                if close is not None and Decimal(str(close)) < Decimal(str(stop["price"])):
                    parts.append("已低於觸價")
                if label == "接近出場":
                    parts.append(f"距觸價 {result['state']['distancePct']:.1f}%")
            # Keep a pathological reason/name from exceeding Telegram's single-page budget.
            lines.append(_shorten("｜".join(parts).replace("\n", " ").replace("\r", " "), 3900))
    if failed > 0:
        lines.append(f"處理失敗 {failed} 檔（見網頁）")
    return _pages(lines, title="觀察清單")
