"""FastAPI application entry point.

This is a scaffolding stub. Task 5 introduces auth; Task 6 introduces ingestion.
"""

from fastapi import FastAPI

from accounting_parser import __version__

app = FastAPI(
    title="accounting-parser",
    version=__version__,
    description="Accounting document parser for solo-practice CPAs",
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "version": __version__}
