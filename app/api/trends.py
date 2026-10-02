import json
import queue
import threading

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.tendencias import analisar_e_salvar, carregar_tendencias_salvas

router = APIRouter(tags=["Tendências"])


class TrendArea(BaseModel):
    name: str
    volume: str
    trend: str


class TrendsAnalysis(BaseModel):
    sourceFile: str
    totalJobs: int
    uniqueTitles: int
    market: list[TrendArea]
    development: list[TrendArea]
    warnings: list[str]
    model: str
    inputTokens: int
    cachedTokens: int
    outputTokens: int
    costUsd: float


class TrendsResponse(BaseModel):
    analysis: TrendsAnalysis | None = None


def _evento(nome: str, payload: object) -> str:
    return f"event: {nome}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _areas(itens: list[dict]) -> list[dict]:
    return [
        {
            "name": item.get("nome", ""),
            "volume": item.get("volume", ""),
            "trend": item.get("tendencia", ""),
        }
        for item in itens
    ]


def _para_saida(dados: dict) -> dict:
    return {
        "sourceFile": dados["arquivo_vagas"],
        "totalJobs": dados["total_vagas"],
        "uniqueTitles": dados["titulos_unicos"],
        "market": _areas(dados.get("onde_ha_mais_vagas", [])),
        "development": _areas(dados.get("desenvolvimento", [])),
        "warnings": dados.get("avisos", []),
        "model": dados["modelo"],
        "inputTokens": dados["entrada"],
        "cachedTokens": dados["cache"],
        "outputTokens": dados["saida"],
        "costUsd": dados["custo"],
    }


@router.get("/trends", response_model=TrendsResponse)
def obter_tendencias() -> TrendsResponse:
    dados = carregar_tendencias_salvas()
    if dados is None:
        return TrendsResponse(analysis=None)
    return TrendsResponse(analysis=TrendsAnalysis.model_validate(_para_saida(dados)))


@router.post("/trends/search")
def analisar_tendencias() -> StreamingResponse:
    eventos: queue.Queue[tuple[str, object] | None] = queue.Queue()

    def on_status(mensagem: str) -> None:
        eventos.put(("status", mensagem))

    def worker() -> None:
        try:
            dados = analisar_e_salvar(on_status)
            eventos.put(("done", {"analysis": _para_saida(dados)}))
        except Exception as exc:
            eventos.put(("error", {"detail": str(exc)}))
        finally:
            eventos.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        while True:
            item = eventos.get()
            if item is None:
                break
            nome, payload = item
            yield _evento(nome, payload)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
