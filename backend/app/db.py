from collections.abc import Callable

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


SessionFactory = Callable[[], Session]


def create_database(database_url: str) -> tuple[Engine, sessionmaker[Session]]:
    connect_args = {'check_same_thread': False} if database_url.startswith('sqlite') else {}
    engine_kwargs: dict[str, object] = {'connect_args': connect_args, 'future': True}
    if ':memory:' in database_url:
        engine_kwargs['poolclass'] = StaticPool
    engine = create_engine(database_url, **engine_kwargs)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return engine, factory
