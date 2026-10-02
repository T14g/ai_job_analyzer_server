from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.jobs import router as jobs_router
from app.api.trends import router as trends_router

app = FastAPI(
    title="AI Job Analyzer",
    description="API do AI Job Analyzer.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router)
app.include_router(trends_router)


@app.get("/hello", tags=["Hello"])
def hello() -> dict[str, str]:
    return {"message": "Hello, world"}
