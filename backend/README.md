# backend

Python 3.12 + FastAPI + Celery backend for accounting-parser.

## Dev loop

```bash
poetry install
poetry run pytest
poetry run uvicorn accounting_parser.main:app --reload --port 8000
```

## Layout

```
backend/
├── src/accounting_parser/   # application package
├── tests/                   # pytest + Hypothesis
├── pyproject.toml
└── README.md
```
