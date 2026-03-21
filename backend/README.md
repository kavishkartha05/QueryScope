# QueryScope Backend

FastAPI backend for the QueryScope developer observability tool.

## Setup

```bash
# Install dependencies
poetry install

# Copy and configure environment
cp .env.example .env

# Run database migrations
alembic upgrade head

# Start development server
uvicorn app.main:app --reload
```

## Structure

```
app/
├── api/        # Route handlers
├── core/       # config.py, db.py
├── models/     # SQLAlchemy ORM models
├── schemas/    # Pydantic request/response models
├── services/   # Business logic
└── main.py     # App factory
```
