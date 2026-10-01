import json
import queue
import threading

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.gupy import coletar_e_salvar, listar_vagas_salvas

router = APIRouter(tags=["Vagas"])


class JobOut(BaseModel):
    company: str
    title: str
    url: str


class JobsResponse(BaseModel):
    jobs: list[JobOut]


def _evento(nome: str, payload: object) -> str:
    return f"event: {nome}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/jobs", response_model=JobsResponse)
def listar_vagas() -> JobsResponse:
    return JobsResponse(jobs=listar_vagas_salvas())


@router.post("/jobs/search")
def buscar_vagas() -> StreamingResponse:
    eventos: queue.Queue[tuple[str, object] | None] = queue.Queue()

    def on_status(mensagem: str) -> None:
        eventos.put(("status", mensagem))

    def worker() -> None:
        try:
            vagas = coletar_e_salvar(on_status)
            eventos.put(("done", {"jobs": vagas}))
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
