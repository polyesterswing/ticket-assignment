from fastapi import FastAPI

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

app = FastAPI(title="clearfeed")
register_error_handlers(app)
app.include_router(companies.router)
app.include_router(agents.router)
app.include_router(shifts.router)
app.include_router(required_hours.router)
app.include_router(coverage.router)
app.include_router(tickets.router)
app.include_router(assignment_log.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
