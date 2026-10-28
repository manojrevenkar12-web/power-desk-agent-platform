import time

import jwt
import pytest

from powerdesk import auth


def test_dev_token_roundtrip():
    assert auth.verify(auth.mint_dev_token("lena")).user == "lena"


def test_dev_tokens_refused_in_production(monkeypatch):
    tok = auth.mint_dev_token("lena")
    monkeypatch.setenv("POWERDESK_ENV", "prod")
    with pytest.raises(auth.Unauthorized):
        auth.verify(tok)


@pytest.mark.parametrize("claims", [{"aud": "someone-else"}, {"exp": int(time.time()) - 10}, {"desk_user": "mallory"}, {"iss": "elsewhere"}])
def test_bad_tokens(claims):
    now = int(time.time())
    base = {"iss": auth.DEV_ISSUER, "aud": auth.AUDIENCE, "sub": "lena", "desk_user": "lena", "iat": now, "exp": now + 60}
    tok = jwt.encode(base | claims, auth._dev_secret(), algorithm="HS256")
    with pytest.raises(auth.Unauthorized):
        auth.verify(tok)


def test_none_algorithm_refused():
    tok = jwt.encode({"desk_user": "lena"}, key=None, algorithm="none")
    with pytest.raises(auth.Unauthorized):
        auth.verify(tok)


def test_envelope_roundtrip_and_tamper():
    env = auth.seal("ravi", "desk_agent")
    assert auth.unseal(env) == ("ravi", "desk_agent")
    _, sig = env.split(".")
    import base64
    import json

    forged = base64.urlsafe_b64encode(json.dumps({"user": "lena", "surface": "desk_agent", "exp": int(time.time()) + 60}).encode()).decode()
    with pytest.raises(auth.Unauthorized):
        auth.unseal(forged + "." + sig)


def test_envelope_expires():
    with pytest.raises(auth.Unauthorized):
        auth.unseal(auth.seal("ravi", "desk_agent", ttl_s=-1))
