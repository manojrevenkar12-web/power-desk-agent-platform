"""Imported first by every probe (run with -I in the candidate's own virtualenv). Records and
blocks every outbound connection that is not to the local desk MCP server, so "what does this
framework do on the network" is measured, not assumed."""

import json
import os
import socket
import sys
import time

ALLOWED = {("127.0.0.1", int(os.environ.get("DESK_MCP_PORT", "0")))}
ATTEMPTS: list[str] = []
_connect = socket.socket.connect
_getaddrinfo = socket.getaddrinfo


def _addr(a):
    return (a[0], int(a[1])) if isinstance(a, tuple) and len(a) >= 2 else (str(a), 0)


def connect(self, address):
    if _addr(address) in ALLOWED or self.family == getattr(socket, "AF_UNIX", -1):
        return _connect(self, address)
    ATTEMPTS.append(f"connect {address}")
    raise OSError("network blocked by connector fitness probe")


def getaddrinfo(host, *a, **k):
    if host not in ("127.0.0.1", "localhost", None):
        ATTEMPTS.append(f"dns {host}")
        raise socket.gaierror("network blocked by connector fitness probe")
    return _getaddrinfo(host, *a, **k)


socket.socket.connect = connect  # type: ignore[method-assign]
socket.getaddrinfo = getaddrinfo


def timed_import(stmt: str) -> float:
    t0 = time.perf_counter()
    exec(stmt, {})
    return round((time.perf_counter() - t0) * 1000, 1)


def emit(result: dict) -> None:
    result["network_attempts"] = ATTEMPTS
    sys.stdout.write("\n@@RESULT@@" + json.dumps(result, default=str) + "\n")
    sys.stdout.flush()
