import re
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.indexer import rollups, source
from app.indexer.writer import prune_project, write

router = APIRouter(prefix="/api/v1/indexer", tags=["indexer"])

_PROJECT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")


def _require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
        )


def _safe_project(project: str) -> str:
    if not isinstance(project, str) or not _PROJECT_RE.match(project) or ".." in project:
        raise HTTPException(
            status_code=400,
            detail="Invalid project name. Use one safe path component.",
        )
    return project


@router.post("/projects/{project}", dependencies=[Depends(_require_api_key)])
def index_project(
    project: str,
    body: dict[str, Any] | None = Body(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    project = _safe_project(project)
    if settings.data_dir is None:
        raise HTTPException(status_code=500, detail="DATA_DIR is not configured.")

    data_dir = settings.data_dir
    if not (data_dir / "projects").is_dir():
        raise HTTPException(
            status_code=500,
            detail=f"DATA_DIR does not contain projects/: {data_dir}",
        )

    body = body or {}
    dry_run = bool(body.get("dry_run", False))

    try:
        if not source.is_project_public(data_dir, project):
            removed = prune_project(db, project)
            if dry_run:
                db.rollback()
            else:
                db.commit()
            return {
                "status": "dry_run" if dry_run else "pruned",
                "project": project,
                "data_dir": str(data_dir),
                "detail": "Project is marked private in DATA_DIR and was removed from the public catalog.",
                "spots_removed": removed,
            }
        detections = source.read_aggregate(data_dir, project)
        coords = source.read_geo(data_dir, project)
        audio_counts = source.count_audio_files(data_dir, project)
        jobs = source.list_jobs(data_dir, project)
        verdicts, pooled = source.read_migratory(data_dir, project)
        indices = source.read_acoustic_indices(data_dir, project)
    except source.SourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if detections.empty:
        raise HTTPException(
            status_code=422,
            detail="Project has no detections in dataset/aggregate.csv; nothing can be published.",
        )

    computed = rollups.build(detections, audio_counts=audio_counts)
    report = write(
        db,
        project,
        computed,
        coords,
        jobs=jobs,
        verdicts=verdicts,
        indices=indices,
        pooled_verdicts=pooled,
    )

    if dry_run:
        db.rollback()
    else:
        db.commit()

    return {
        "status": "dry_run" if dry_run else "indexed",
        "project": project,
        "data_dir": str(data_dir),
        "summary": report.summary(),
        "report": asdict(report),
    }
