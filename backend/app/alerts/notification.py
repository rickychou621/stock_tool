"""通知只接受既有告警 ID，不接受客戶端自填股票或通知文字。"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import AlertLog
from app.core.config import get_settings
from app.data_source.notifier import TelegramNotifier
from app.market_data.models import Stock


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
        # Consistent lock order serializes overlapping sends from double clicks/tabs.
        for alert_id in sorted(set(alert_ids)):
            alert = self._db.scalar(
                select(AlertLog).where(AlertLog.id == alert_id).with_for_update()
            )
            if alert is None:
                summary.failed_ids.append(alert_id)
                self._db.rollback()
                continue
            if alert.is_notified:
                summary.skipped_ids.append(alert_id)
                self._db.rollback()
                continue
            try:
                name = self._db.scalar(select(Stock.name).where(Stock.ticker == alert.ticker))
                prefix = f"{alert.ticker} "
                named_prefix = f"{alert.ticker} {name} "
                if name and alert.message.startswith(prefix) and not alert.message.startswith(
                    named_prefix
                ):
                    alert.message = named_prefix + alert.message[len(prefix):]
                self._notifier.send_alert(alert.message)
                alert.is_notified = True
                self._db.commit()
                summary.sent_ids.append(alert_id)
            except Exception:  # noqa: BLE001 - preserve failures for an explicit retry
                self._db.rollback()
                summary.failed_ids.append(alert_id)
        return summary
