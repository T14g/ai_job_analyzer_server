from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.avaliar import avaliar_area

router = APIRouter(tags=["Avaliar"])


class EvaluateIn(BaseModel):
    area: str


class MatchOut(BaseModel):
    company: str
    title: str
    url: str


class EvaluateResponse(BaseModel):
    area: str
    matches: list[MatchOut]


@router.post("/evaluate", response_model=EvaluateResponse)
def avaliar(corpo: EvaluateIn) -> EvaluateResponse:
    try:
        dados = avaliar_area(corpo.area)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return EvaluateResponse.model_validate(dados)
