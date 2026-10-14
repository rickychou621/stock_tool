"""通知只接受既有告警 ID，將符合戰法的結果分批摘要發送。"""

from dataclasses import dataclass, field
from time import sleep

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import AlertLog
from app.core.config import get_settings
from app.data_source.notifier import TelegramNotifier
from app.market_data.models import Stock

BATCH_SIZE = 50
# Conservative UTF-16 budget, including the heading, below Telegram's 4096 limit.
MESSAGE_LIMIT = 4000


def _text_size(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _shorten(text: str, limit: int) -> str:
    if _text_size(text) <= limit:
        return text
    return text.encode("utf-16-le")[: (limit - 1) * 2].decode("utf-16-le", errors="ignore") + "…"


def _entry(alert: AlertLog, name: str | None) -> str:
    prefix = f"{alert.ticker} "
    named_prefix = f"{alert.ticker} {name} "
    if name and alert.message.startswith(prefix) and not alert.message.startswith(named_prefix):
        alert.message = named_prefix + alert.message[len(prefix) :]
    lines = alert.message.splitlines()
    # Keep the historical rule name and quote date, rather than today's rule settings.
    title = lines[0] if lines and lines[0].startswith(prefix) else f"{alert.ticker} {name or ''}"
    quote = next((line for line in lines[1:] if line.startswith("行情日期：")), None)
    if quote is None:
        quote = f"參考價：{alert.price_at_trigger if alert.price_at_trigger is not None else '—'}"
    marks = [
        label
        for label, original in (("突破上軌", "突破布林上軌"), ("觸及上軌", "觸及布林上軌"))
        if label in alert.message or original in alert.message
    ]
    return "｜".join([_shorten(title, 500), _shorten(quote, 300), *marks])


@dataclass
class NotificationSummary:
    sent_ids: list[int] = field(default_factory=list)
    skipped_ids: list[int] = field(default_factory=list)
    failed_ids: list[int] = field(default_factory=list)


class AlertNotificationService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._notifier = TelegramNotifier(get_settings())

    def notify(self, alert_ids: list[int]) -> NotificationSummary:
        summary = NotificationSummary()
        remaining = sorted(set(alert_ids))
        attempted = False
        while remaining:
            if attempted:
                # Space requests to the same chat; do not hold DB locks while waiting.
                sleep(1)
            ids = remaining[:BATCH_SIZE]
            batch: list[AlertLog] = []
            batch_ids: list[int] = []
            consumed: set[int] = set()
            try:
                # Reacquire and refresh after each commit: other requests may have sent
                # the leftover rows while our length-limited batch was in flight.
                alerts = list(
                    self._db.scalars(
                        select(AlertLog)
                        .where(AlertLog.id.in_(ids))
                        .order_by(AlertLog.id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                )
                found = {alert.id for alert in alerts}
                missing = set(ids) - found
                summary.failed_ids.extend(sorted(missing))
                consumed.update(missing)
                pending = []
                for alert in alerts:
                    if alert.is_notified:
                        summary.skipped_ids.append(alert.id)
                        consumed.add(alert.id)
                    else:
                        pending.append(alert)
                names = (
                    dict(
                        self._db.execute(
                            select(Stock.ticker, Stock.name).where(
                                Stock.ticker.in_({alert.ticker for alert in pending})
                            )
                        ).all()
                    )
                    if pending
                    else {}
                )
                entries: list[str] = []
                size = 80  # Reserve heading and separators.
                for alert in pending:
                    entry = _entry(alert, names.get(alert.ticker))
                    if size + _text_size(entry) + 1 > MESSAGE_LIMIT:
                        break
                    entries.append(entry)
                    size += _text_size(entry) + 1
                    batch.append(alert)
                if batch:
                    attempted = True
                    batch_ids = [alert.id for alert in batch]
                    consumed.update(batch_ids)
                    self._notifier.send_alert(
                        f"符合戰法摘要（本則 {len(batch)} 筆）\n" + "\n".join(entries)
                    )
                    for alert in batch:
                        alert.is_notified = True
                    self._db.commit()
                    summary.sent_ids.extend(batch_ids)
                else:
                    self._db.rollback()
            except Exception:  # noqa: BLE001 - preserve failures for an explicit retry
                # Only the attempted message failed. Unsent length-overflow rows are
                # still processed separately, and successful earlier batches stay sent.
                failed = (
                    batch_ids
                    if batch_ids
                    else [alert_id for alert_id in ids if alert_id not in consumed]
                )
                self._db.rollback()
                summary.failed_ids.extend(failed)
                consumed.update(failed)
            remaining = [alert_id for alert_id in remaining if alert_id not in consumed]
        return summary
