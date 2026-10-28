"""The held-out set and its first run are pinned: changing either fails here."""

import hashlib
import json

from powerdesk.settings import ROOT

CASES_SHA256 = "7c585f2e0a3aabefe5bcc93955f593128d207089a02d736662570209f25c034b"
FIRST_RUN_SHA256 = "338fe7da9812a1f70120bd5f7fbc820cd23430f52e36d26b2b4961099c207691"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_blind_set_is_unchanged():
    assert sha(ROOT / "heldout/blind-1/cases.yaml") == CASES_SHA256


def test_first_run_is_never_rewritten():
    p = ROOT / "reports/heldout/blind-1/first_run.json"
    assert sha(p) == FIRST_RUN_SHA256
    assert json.loads(p.read_text())["cases_sha256"] == CASES_SHA256
