import json
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.debug import DEBUG, DebugRequests, debug, info
from app.routes import dashboard, indexer, spots

settings = get_settings()


app = FastAPI(title=settings.app_name)
if DEBUG:
    app.add_middleware(DebugRequests)
info("startup", data_dir=settings.data_dir)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL is unavailable",
        ) from exc
    return {"status": "ok", "database": "postgresql"}


@app.get("/backend-health")
def backend_health(db: Session = Depends(get_db)) -> dict[str, str]:
    return health(db)


@app.get("/runtime-debug.js")
def runtime_debug() -> Response:
    content = f"globalThis.CEM_DEBUG = {'true' if DEBUG else 'false'};\n"
    return Response(
        content=content,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@app.get("/js/config.js")
@app.get("/config.js")
def runtime_config(settings: Settings = Depends(get_settings)) -> Response:
    api_base = settings.api_base_url
    compute_frontend = settings.compute_frontend_url
    js_content = f"""(function () {{
  window.CEM_MASTER_CONFIG = {{
    API_BASE_URL: {json.dumps(api_base)} || window.location.origin,
    COMPUTE_FRONTEND_URL: {json.dumps(compute_frontend)},
  }};
}})();
"""
    return Response(
        content=js_content,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )



@app.get("/api/projects/{project_name}/snippets/{filename}")
def stream_snippet_alias(
    project_name: str,
    filename: str,
    settings: Settings = Depends(get_settings),
):
    return dashboard.stream_snippet(project_name, filename, settings)


app.include_router(spots.router)
app.include_router(dashboard.router)
app.include_router(indexer.router)

# Unified Frontend: Serve static HTML/JS/CSS assets on the same origin / port
_frontend_candidates = [
    Path(os.getenv("FRONTEND_DIR", "")),
    Path("/app/frontend"),
    Path(__file__).resolve().parent.parent.parent / "cem-master-frontend",
]
_frontend_dir = next((p for p in _frontend_candidates if p.is_dir() and (p / "index.html").is_file()), None)

if _frontend_dir:
    info("frontend.mounted", path=str(_frontend_dir))
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")

