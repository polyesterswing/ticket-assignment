from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from clearfeed.api.routes import (
    agents,
    assignment_log,
    companies,
    coverage,
    required_hours,
    shifts,
    tickets,
)
from clearfeed.core.errors import register_error_handlers

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="clearfeed")
register_error_handlers(app)
app.include_router(companies.router)
app.include_router(agents.router)
app.include_router(shifts.router)
app.include_router(required_hours.router)
app.include_router(coverage.router)
app.include_router(tickets.router)
app.include_router(assignment_log.router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """The UI: a static page that calls the JSON API."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
