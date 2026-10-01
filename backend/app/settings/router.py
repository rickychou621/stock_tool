from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.settings.schemas import SettingsSummarySchema, TestTelegramResultSchema
from app.settings.service import SettingsService

router = APIRouter(prefix="/settings", tags=["settings"])


def get_settings_service(settings: Settings = Depends(get_settings)) -> SettingsService:
    return SettingsService(settings)


@router.get("", response_model=SettingsSummarySchema)
def read_settings(
    service: SettingsService = Depends(get_settings_service),
) -> SettingsSummarySchema:
    return SettingsSummarySchema(**service.get_settings_summary())


@router.post("/test-telegram", response_model=TestTelegramResultSchema)
def test_telegram(
    service: SettingsService = Depends(get_settings_service),
) -> TestTelegramResultSchema:
    success, message = service.send_test_telegram_message()
    return TestTelegramResultSchema(success=success, message=message)
