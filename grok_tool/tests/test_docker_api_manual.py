# -*- coding: utf-8 -*-
"""Auto-test /api/docker endpoints trên web console :8787."""
import json
import time
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8787/api/docker"


def call(method="GET", payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


def summary(st):
    return {
        "installed": st.get("installed"),
        "daemon": st.get("daemon_running"),
        "version": st.get("version", "")[:40],
        "containers": [
            f"{c['name']}={c['state']}" for c in st.get("containers", [])
        ],
    }


ok = lambda b, msg: print(("PASS" if b else "FAIL"), "-", msg)

print("=" * 60)
print("[1] GET /api/docker - trang thai hien tai")
code, st = call()
ok(code == 200, f"HTTP {code}")
print(json.dumps(summary(st), ensure_ascii=False, indent=2))
daemon_before = st.get("daemon_running")

print("-" * 60)
print("[2] GET khi chua co action - truong bat buoc ton tai")
for k in ("installed", "daemon_running", "containers"):
    ok(k in st, f"co truong '{k}'")

print("-" * 60)
print("[3] POST action sai -> phai tra loi 400")
code, res = call("POST", {"action": "reboot"})
ok(code == 400 and "start_daemon" in str(res), f"HTTP {code}: {res}")

print("-" * 60)
print("[4] POST start/stop/restart thieu name -> phai tra loi 400")
code, res = call("POST", {"action": "restart"})
ok(code == 400, f"HTTP {code}: {res}")

print("-" * 60)
print("[5] POST start_daemon (Docker Desktop da chay -> khong hai)")
code, res = call("POST", {"action": "start_daemon"})
ok(code == 200 and res.get("ok") is True, f"HTTP {code}: {res.get('message', '')}")
print("   cho 10s roi kiem tra lai daemon...")
time.sleep(10)
code, st = call()
ok(st.get("daemon_running") is True, f"daemon van chay sau start_daemon: {st.get('daemon_running')}")

print("-" * 60)
redis_name = next(
    (c["name"] for c in st.get("containers", []) if "redis" in c["name"]), None
)
if not redis_name:
    print("SKIP - khong thay container redis de test restart")
else:
    print(f"[6] POST restart {redis_name} (container nho, ~5-10s)")
    code, res = call("POST", {"action": "restart", "name": redis_name})
    ok(code == 200 and res.get("ok") is True, f"HTTP {code}: {res.get('message', '')}")
    print("   cho 12s roi kiem tra redis quay lai running...")
    deadline = time.time() + 25
    back = False
    while time.time() < deadline:
        time.sleep(3)
        _, s2 = call()
        c2 = next((c for c in s2.get("containers", []) if c["name"] == redis_name), None)
        if c2 and c2["state"] == "running":
            back = True
            break
    ok(back, f"{redis_name} running lai sau restart (status: {c2['status'] if c2 else '?'})")

print("-" * 60)
print("[7] GET cuoi cung - tong quat")
_, st = call()
s = summary(st)
print(json.dumps(s, ensure_ascii=False, indent=2))
ok(s["installed"] and s["daemon"], "docker installed + daemon running")
running_cnt = sum(1 for c in st.get("containers", []) if c["state"] == "running")
ok(running_cnt >= len(st.get("containers", [])) - 1, f"{running_cnt}/{len(st.get('containers', []))} container dang up")

print("=" * 60)
print("DONE")
