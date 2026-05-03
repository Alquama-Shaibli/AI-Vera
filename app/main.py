from fastapi import FastAPI
import os

app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok", "test": "minimal"}

@app.get("/v1/healthz")
def health():
    return {"healthy": True, "port": os.getenv("PORT", "8080")}
