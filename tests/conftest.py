import os

os.environ.setdefault("POWERDESK_DEV_SECRET", "test-secret-for-dev-tokens-0123456789abcdef")
os.environ.setdefault("POWERDESK_IDENTITY_KEY", "test-identity-key-0123456789abcdef0123456789")
os.environ.pop("POWERDESK_ENV", None)
os.environ.pop("POWERDESK_MODEL", None)

import pytest

from powerdesk.desk import Desk, build_desk


@pytest.fixture(scope="session")
def desk() -> Desk:
    return build_desk()


@pytest.fixture(scope="session")
def gateway(desk):
    return desk.gateway
