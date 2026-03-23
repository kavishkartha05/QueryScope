from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


def _make_database_url(url: str) -> str:
    """
    Adapter swap demo (see CLAUDE.md and docs/mysql-adapter.md).

    SQLAlchemy uses the URL scheme to select the DBAPI driver.  We normalise
    bare "postgresql://" and "mysql://" URLs to their async-capable variants so
    callers only need to change the host/credentials in DATABASE_URL, not the
    driver fragment.

    - postgresql → postgresql+asyncpg   (asyncpg is the async Postgres driver)
    - mysql       → mysql+aiomysql      (aiomysql is the async MySQL driver)

    Any URL that already includes a driver fragment (e.g. "+asyncpg") is
    returned unchanged, so explicit overrides are always respected.
    """
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("mysql://"):
        return url.replace("mysql://", "mysql+aiomysql://", 1)
    # postgresql+asyncpg://, mysql+aiomysql://, sqlite+aiosqlite://, etc.
    return url


# pool_pre_ping detects stale connections before use
engine = create_async_engine(
    _make_database_url(settings.database_url),
    pool_pre_ping=True,
    echo=settings.debug,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # keep attributes accessible after commit
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """FastAPI dependency that yields a database session."""
    async with AsyncSessionLocal() as session:
        yield session
