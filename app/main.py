"""
Main FastAPI Application Entrypoint.
Mounts routers, enables CORS, and serves the static frontend dashboard.
"""

from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routers.case_router import router as case_router, websocket_case_stream

app = FastAPI(
    title="Supply Chain Disruption Analyser",
    description="Adversarial Multi-Agent Judicial System for Supply Chain Exposure Analysis",
    version="1.0.0"
)

# Enable CORS for local development and dashboards
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Support both /api/ws/case/{id} and /ws/case/{id}
app.add_api_websocket_route("/ws/case/{case_id}", websocket_case_stream)

# Include API router
app.include_router(case_router)

# Mount frontend directory
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)

