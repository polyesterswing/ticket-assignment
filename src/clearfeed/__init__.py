def main() -> None:
    import uvicorn

    uvicorn.run("clearfeed.app:app", host="127.0.0.1", port=8000)
