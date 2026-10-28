"""Who is calling. In AWS: OpenID Connect tokens (the firm's identity provider, through Amazon
Cognito or Entra ID) checked against the issuer's JWKS. On a laptop and in CI: short-lived dev
tokens signed with a local secret. Either way the desk user comes from the token, never from a
request body or a model.

Between the AgentCore Gateway interceptor and the tool Lambdas, identity travels as a small
envelope signed with a key only those two hold, so a model cannot forge it by adding arguments.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt

from powerdesk.settings import org

DEV_ISSUER = "powerdesk-dev"
AUDIENCE = os.environ.get("POWERDESK_OIDC_AUDIENCE", "power-desk-agent-platform")
USER_CLAIM = os.environ.get("POWERDESK_USER_CLAIM", "desk_user")


class Unauthorized(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    user: str
    issuer: str


def _dev_secret() -> str:
    secret = os.environ.get("POWERDESK_DEV_SECRET", "")
    if len(secret) < 32:
        raise Unauthorized("dev tokens need POWERDESK_DEV_SECRET of at least 32 characters")
    return secret


def mint_dev_token(user: str, minutes: int = 60) -> str:
    if user not in org().users:
        raise ValueError(f"unknown user {user}")
    now = int(time.time())
    return jwt.encode({"iss": DEV_ISSUER, "aud": AUDIENCE, "sub": user, USER_CLAIM: user, "iat": now, "exp": now + minutes * 60}, _dev_secret(), algorithm="HS256")


@lru_cache
def _jwks() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(os.environ["POWERDESK_OIDC_JWKS_URL"], cache_keys=True)


def verify(token: str) -> Principal:
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") == "HS256":
            if os.environ.get("POWERDESK_ENV", "dev") == "prod":
                raise Unauthorized("dev tokens are not accepted in production")
            claims: dict[str, Any] = jwt.decode(token, _dev_secret(), algorithms=["HS256"], audience=AUDIENCE, issuer=DEV_ISSUER)
        else:
            key = _jwks().get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256", "ES256"], audience=AUDIENCE, issuer=os.environ["POWERDESK_OIDC_ISSUER"])
    except (jwt.PyJWTError, KeyError) as e:
        raise Unauthorized(str(e)) from e
    user = str(claims.get(USER_CLAIM, ""))
    if user not in org().users:
        raise Unauthorized("token names no desk user")
    return Principal(user, str(claims["iss"]))


# --- the identity envelope between the gateway interceptor and the tool Lambdas -----------------

ENVELOPE_KEY = "_desk_identity"


@lru_cache
def _secret(arn: str) -> str:
    import boto3

    return str(boto3.client("secretsmanager").get_secret_value(SecretId=arn)["SecretString"])


def _identity_key() -> bytes:
    arn = os.environ.get("POWERDESK_IDENTITY_KEY_SECRET_ARN", "")
    key = _secret(arn) if arn else os.environ.get("POWERDESK_IDENTITY_KEY", "")
    if len(key) < 32:
        raise Unauthorized("POWERDESK_IDENTITY_KEY must be at least 32 characters")
    return key.encode()


def seal(user: str, surface: str, ttl_s: int = 120) -> str:
    body = json.dumps({"user": user, "surface": surface, "exp": int(time.time()) + ttl_s}, sort_keys=True).encode()
    sig = hmac.new(_identity_key(), body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(body).decode() + "." + base64.urlsafe_b64encode(sig).decode()


def unseal(envelope: str) -> tuple[str, str]:
    try:
        b64body, b64sig = envelope.split(".")
        body = base64.urlsafe_b64decode(b64body)
        sig = base64.urlsafe_b64decode(b64sig)
    except ValueError as e:
        raise Unauthorized("malformed identity envelope") from e
    if not hmac.compare_digest(sig, hmac.new(_identity_key(), body, hashlib.sha256).digest()):
        raise Unauthorized("identity envelope signature does not match")
    data = json.loads(body)
    if data["exp"] < time.time():
        raise Unauthorized("identity envelope expired")
    if data["user"] not in org().users:
        raise Unauthorized("unknown user in identity envelope")
    return data["user"], data["surface"]
