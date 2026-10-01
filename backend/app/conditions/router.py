from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.conditions.repository import ConditionRepository
from app.conditions.schemas import ConditionCatalogSchema
from app.core.dependencies import get_db

router = APIRouter(prefix="/conditions", tags=["conditions"])


@router.get("", response_model=list[ConditionCatalogSchema])
def list_conditions(db: Session = Depends(get_db)) -> list[ConditionCatalogSchema]:
    repository = ConditionRepository(db)
    return [
        ConditionCatalogSchema(
            id=c.id,
            name=c.name,
            description=c.description,
            required_timeframe=c.required_timeframe,
            update_frequency=c.update_frequency,
        )
        for c in repository.list_all()
    ]
