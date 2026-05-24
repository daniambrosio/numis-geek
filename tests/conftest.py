import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Disable APScheduler in tests so app.lifespan doesn't spin up a real
# thread that could interfere with TestClient or leak across tests.
os.environ.setdefault("DISABLE_SCHEDULER", "true")

from numis_geek.db.base import Base

# Import all models here so Base.metadata knows about every table
import numis_geek.models  # noqa: F401


@pytest.fixture(scope="session")
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture
def db(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.rollback()
    session.close()
