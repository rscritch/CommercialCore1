import os
os.environ["COMMERCIALCORE_DATABASE_URL"] = "sqlite:///./data/test_commercialcore.db"
import pytest
from fastapi.testclient import TestClient
from app.main import app, initialize
from app.db import Base, engine

@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    initialize()
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(engine)
