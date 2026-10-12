from fastapi import FastAPI

app = FastAPI(title="clearfeed")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
