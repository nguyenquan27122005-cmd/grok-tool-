"""Self-check prefetch stash — chạy: ../grok_tool/venv/Scripts/python.exe tmp_zai_prefetch_test.py"""
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import zaireg.captcha as captcha_mod
import zaireg.mail as mail_mod
import zaireg.prefetch as pf


class FakeSession:
    address = "fake123@guerrillamailblock.com"
    provider = "fake"


def _fake_acquire(config):
    return (FakeSession(), None, None)


def _fake_solve(config, **kw):
    time.sleep(0.2)
    assert kw.get("email") == "fake123@guerrillamailblock.com", kw
    assert kw.get("submit") is False
    return {"signup_ok": True, "resp": {"http": 200, "fake": True}}


mail_mod.acquire_email = _fake_acquire
captcha_mod.solve_and_signup = _fake_solve

# 1. pop trên stash rỗng → None, không ném
assert pf.pop() is None

# 2. kick → thread nền fill stash → pop đủ email/password/mail
pf.kick({"fixed_password": "X@123", "email_provider": "guerrilla"})
for _ in range(50):
    time.sleep(0.1)
    entry = pf.pop()
    if entry:
        break
assert entry, "stash không được fill sau 5s"
assert entry["email"] == "fake123@guerrillamailblock.com"
assert entry["password"], "password rỗng"
assert entry["mail"][0].address == "fake123@guerrillamailblock.com"
assert pf.pop() is None, "stash phải rỗng sau khi pop"

# 3. signup fail → không vào stash
captcha_mod.solve_and_signup = lambda config, **kw: {"signup_ok": False, "detail": "nope"}
pf.kick({"email_provider": "guerrilla"})
time.sleep(1.0)
assert pf.pop() is None, "signup fail không được vào stash"

# 4. _working được reset → kick lại chạy được
captcha_mod.solve_and_signup = _fake_solve
pf.kick({"email_provider": "guerrilla"})
for _ in range(50):
    time.sleep(0.1)
    entry = pf.pop()
    if entry:
        break
assert entry, "kick thứ hai phải chạy lại được"

print("prefetch self-check: OK")
