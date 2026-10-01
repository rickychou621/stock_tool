from fastapi import FastAPI

from app.alerts.router import router as alerts_router
from app.chart.router import router as chart_router
from app.conditions.router import router as conditions_router
from app.market_data.router import router as stocks_router
from app.rules.router import router as rules_router
from app.screening.router import router as screening_router
from app.settings.router import router as settings_router
from app.watchlist.router import router as watchlist_router

app = FastAPI(title="股票告警系統 API")


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
