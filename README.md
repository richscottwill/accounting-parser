# accounting-parser

SaaS accounting document parser for solo-practice CPAs. Ingests vendor-native accounting documents (QuickBooks, Xero, NetSuite exports; IRS form PDFs; bank statements; interchange formats) and produces exporter-ready artifacts for downstream tax and engagement systems (CCH Axcess Engagement, UltraTax CS + AdvanceFlow, Lacerte TB Utility, QuickBooks IIF).

**Target user:** Ex-RSM US LLP tax senior going solo. Middle-market client complexity without the staff. The system replaces the staff, not the tools.

**Status:** Task 1 scaffolding. See `.kiro/specs/accounting-document-parser/tasks.md` (parent repo) for the 31-task implementation plan.

---

## Repository layout

```
accounting-parser/
├── backend/           # Python 3.12 + FastAPI + Celery
├── frontend/          # React + TypeScript + Vite
├── infra/             # Terraform + AWS CDK
│   ├── terraform/
│   └── cdk/
├── tests/             # Pytest + Hypothesis + Playwright
│   ├── fixtures/      # Synthetic accounting documents
│   ├── integration/
│   └── playwright/
├── docs/              # Generated from spec
├── .github/
│   └── workflows/     # CI pipelines
├── docker-compose.yml # Local dev infra: Postgres 16 + Redis 7 + LocalStack
└── README.md
```

## Prerequisites

| Tool            | Version            | Install                                                |
| --------------- | ------------------ | ------------------------------------------------------ |
| Python          | 3.12+              | https://www.python.org/downloads/                      |
| Node.js         | 20+                | https://nodejs.org/                                    |
| Poetry          | 2.x                | `pipx install poetry`                                  |
| pnpm            | 9+                 | `npm install -g pnpm`                                  |
| Docker Desktop  | 4.x+               | https://www.docker.com/products/docker-desktop/        |
| Git             | 2.40+              | https://git-scm.com/                                   |

## Run locally (15-minute bootstrap)

```bash
# 1. Clone
git clone https://github.com/richscottwill/accounting-parser.git
cd accounting-parser

# 2. Install backend deps
cd backend
poetry install
cd ..

# 3. Install frontend deps
cd frontend
pnpm install
cd ..

# 4. Start infra
docker compose up -d
# This brings up Postgres 16 (port 5432), Redis 7 (port 6379), LocalStack (port 4566)

# 5. Run backend tests (no app code yet — just scaffolding)
cd backend
poetry run pytest
cd ..

# 6. Run frontend tests
cd frontend
pnpm test
cd ..

# 7. (Optional) Start API + UI dev servers
cd backend && poetry run uvicorn accounting_parser.main:app --reload --port 8000 &
cd frontend && pnpm dev  # http://localhost:3000
```

When Task 1 scaffolding is green, all of the above should exit clean with no application code yet.

## Development workflow

- **Branches:** work on feature branches; never push to `main` directly. PRs go through GitHub.
- **Pre-commit:** hooks run black, isort, mypy, ruff (backend) and eslint, prettier (frontend) on staged files.
- **CI:** GitHub Actions runs lint, type-check, unit tests, Hypothesis tests, frontend build, and container build on every PR.
- **Traceability:** every feature connects back to a requirement ID in `.kiro/specs/accounting-document-parser/requirements.md`.

## Spec

The full spec (requirements, design, tasks) lives in the parent-workspace Kiro directory at `.kiro/specs/accounting-document-parser/`:
- `requirements.md` — 24 EARS-notated requirements, 28 correctness properties
- `design.md` — modular monolith on AWS
- `tasks.md` — 31-task implementation plan

## License

TBD.
