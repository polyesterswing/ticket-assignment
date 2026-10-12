from fastapi import FastAPI

from clearfeed.api.routes import required_hours, shifts
from clearfeed.core.errors import register_error_handlers

app = FastAPI(title="clearfeed")
register_error_handlers(app)
app.include_router(shifts.router)
app.include_router(required_hours.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
