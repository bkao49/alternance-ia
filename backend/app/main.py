from fastapi import FastAPI

app = FastAPI(title="Assistant alternance", docs_url=None, redoc_url=None)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
