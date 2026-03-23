# MySQL Adapter Swap Demo

QueryScope uses SQLAlchemy's async engine, which makes swapping the underlying
database a matter of changing `DATABASE_URL` in `.env`.  This document explains
how to point QueryScope at MySQL instead of PostgreSQL.

> **Note:** Per `CLAUDE.md`, this is an adapter swap *demo*.  PostgreSQL with
> asyncpg is the production driver.  MySQL support is illustrative.

## How to swap

1. Change `DATABASE_URL` in `backend/.env`:

   ```
   DATABASE_URL=mysql+aiomysql://user:password@host:3306/queryscope
   ```

   A bare `mysql://` URL also works — `app/core/db.py` rewrites it to
   `mysql+aiomysql://` automatically.

2. Run migrations:

   ```bash
   cd backend && alembic upgrade head
   ```

3. Start the server normally:

   ```bash
   uvicorn app.main:app --reload
   ```

No code changes required.

## URL format

```
mysql+aiomysql://<user>:<password>@<host>:<port>/<dbname>
```

Example:

```
mysql+aiomysql://queryscope:secret@localhost:3306/queryscope
```

## Cross-database design decisions

### `JSON` instead of `ARRAY` for latencies

The `metrics.latencies` column uses `sa.JSON` rather than
`sqlalchemy.dialects.postgresql.ARRAY`.  Both PostgreSQL and MySQL support a
native JSON column type, so the schema migrates and operates correctly on either
database.  SQLAlchemy deserialises the column as a Python `list[float]`
automatically, and numpy can operate on that list directly.

### Enum type

The `run_status` enum uses `sa.Enum` with `create_type=True`.  Alembic detects
the dialect at migration time:

- **PostgreSQL** — emits `CREATE TYPE run_status AS ENUM (...)` before the table.
- **MySQL** — emits `ENUM('pending','running','done','failed')` inline on the
  column, with no separate type object.

No manual changes are needed when switching dialects.

## What works on MySQL

- All `runs` table operations (create, read, update status)
- All `metrics` table operations including `latencies` storage via JSON
- Alembic migrations (`alembic upgrade head` / `alembic downgrade`)
- Every API endpoint: `/health`, `/benchmark`, `/runs`, `/diagnose`

## Remaining limitations

- **Azure AI Search / OpenAI** — these depend on external services, not the
  database, and are unaffected by the adapter swap.
- **UUID primary keys** — MySQL 5.7 stores UUIDs as `CHAR(32)`; MySQL 8+ and
  MariaDB support native `UUID`.  SQLAlchemy's `Uuid` type handles this
  transparently, but query performance on large tables may differ from
  PostgreSQL's native `uuid` type.
