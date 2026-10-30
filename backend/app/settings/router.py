from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.dependencies import get_db
from app.market_scan.service import excluded_etf_categories, large_stop_distance_pct, settings_row
from app.settings.schemas import (
    EtfExclusionSchema,
    SettingsSummarySchema,
    StopDistanceSchema,
    TestTelegramResultSchema,
)
from app.settings.service import SettingsService

router = APIRouter(prefix="/settings", tags=["settings"])


def get_settings_service(settings: Settings = Depends(get_settings)) -> SettingsService:
    return SettingsService(settings)


@router.get("", response_model=SettingsSummarySchema)
def read_settings(
    db: Session = Depends(get_db),
    service: SettingsService = Depends(get_settings_service),
) -> SettingsSummarySchema:
    return SettingsSummarySchema(
        **service.get_settings_summary(),
        excluded_etf_categories=sorted(excluded_etf_categories(db)),
        large_stop_distance_pct=large_stop_distance_pct(db),
    )


@router.post("/test-telegram", response_model=TestTelegramResultSchema)
def test_telegram(
    service: SettingsService = Depends(get_settings_service),
) -> TestTelegramResultSchema:
    success, message = service.send_test_telegram_message()
    return TestTelegramResultSchema(success=success, message=message)


@router.put("/etf-exclusion", response_model=EtfExclusionSchema)
def update_etf_exclusion(body: EtfExclusionSchema, db: Session = Depends(get_db)):
    row = settings_row(db)
    row.excluded_etf_categories = sorted(set(body.categories))
    db.commit()
    return EtfExclusionSchema(categories=row.excluded_etf_categories)


@router.put("/stop-distance", response_model=StopDistanceSchema)
def update_stop_distance(body: StopDistanceSchema, db: Session = Depends(get_db)):
    row = settings_row(db)
    row.large_stop_distance_pct = body.large_stop_distance_pct
    db.commit()
    return StopDistanceSchema(large_stop_distance_pct=row.large_stop_distance_pct)
