"""
SQLAlchemy async engine y session factory para PostgreSQL 17.
- Finalidad: Configura conexion async a PostgreSQL, provee session dependency
  para FastAPI y funcion para crear tablas al arrancar.
- Consume: config.py (DATABASE_URL)
- Consumido por: models.py (Base), router.py (get_db), service.py (get_db), main.py (init_db)
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
