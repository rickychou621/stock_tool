from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.alerts.router import router as alerts_router
from app.backtest.router import router as backtest_router
from app.backtest.service import manager as backtest_manager
from app.chart.router import router as chart_router
from app.conditions.router import router as conditions_router
from app.market_data.router import router as stocks_router
from app.market_scan.router import router as market_scan_router
from app.market_scan.service import manager as market_scan_manager
from app.rules.router import router as rules_router
from app.scheduler.router import router as schedule_router
from app.scheduler.scheduler import start_scheduler, stop_scheduler
from app.screening.router import router as screening_router
from app.settings.router import router as settings_router
from app.watchlist.router import router as watchlist_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    backtest_manager.recover()
    market_scan_manager.recover()
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()
        backtest_manager.close()
        market_scan_manager.close()


app = FastAPI(title="股票告警系統 API", lifespan=lifespan)
app.include_router(schedule_router)
app.include_router(backtest_router)
app.include_router(market_scan_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(screening_router)
app.include_router(watchlist_router)
app.include_router(rules_router)
app.include_router(alerts_router)
app.include_router(chart_router)
app.include_router(settings_router)
app.include_router(conditions_router)
app.include_router(stocks_router)
