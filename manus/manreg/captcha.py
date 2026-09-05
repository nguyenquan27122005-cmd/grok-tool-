"""Giải Cloudflare Turnstile cho Manus qua solver local (services/turnstile_solver).

Solver chạy ở http://127.0.0.1:5072 (console grok_tool quản): nhận url + sitekey,
mở Camoufox thật bấm checkbox rồi trả token. Client này chỉ gọi HTTP + bơm token
vào trang đang mở — không tự khởi động browser nào.
"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import quote

import requests

from manreg.log import log

DEFAULT_SOLVER_URL = "http://127.0.0.1:5072"
# Sitekey Turnstile trên manus.im/login (lấy từ HTML trang login)
MANUS_SITEKEY = "0x4AAAAAAA_sd0eRNCinWBgU"

_SITEKEY_RE = re.compile(r"(0x4[A-Za-z0-9_-]{10,})", re.I)

EXTRACT_SITEKEY_JS = r"""
(() => {
  const el = document.querySelector('[data-sitekey]');
  if (el) return el.getAttribute('data-sitekey') || '';
  const box = document.querySelector('.cf-turnstile, [class*="turnstile"]');
  if (box && box.dataset && box.dataset.sitekey) return box.dataset.sitekey;
  for (const f of document.querySelectorAll('iframe')) {
    const s = f.src || '';
    const m = s.match(/[?&]sitekey=([^&]+)/i);
    if (m) return decodeURIComponent(m[1]);
  }
  const html = document.documentElement ? document.documentElement.innerHTML : '';
  const m2 = html.match(/0x4[A-Za-z0-9_-]{10,}/);
  return m2 ? m2[0] : '';
})()
"""

# Bơm token vào input/textarea cf-turnstile-response + mọi hidden field liên quan.
# Quan trọng: nút submit của Manus bị DISABLE cho tới khi callback của widget
# Turnstile chạy (React state mới nhận token). Nên ngoài set DOM còn phải gọi
# trực tiếp onChange/onSuccess trong React props (fiber) — chỉ set DOM thì
# bấm Continue vẫn vô ích (đã gặp thật trên profile GPM).
INJECT_TOKEN_JS = r"""
(() => {
  const token = %TOKEN%;
  let n = 0, r = 0;
  const setVal = (el) => {
    if (!el) return;
    try {
      const proto = el.tagName === 'TEXTAREA'
        ? window.HTMLTextAreaElement.prototype
        : window.HTMLInputElement.prototype;
      const desc = Object.getOwnPropertyDescriptor(proto, 'value');
      const prev = el.value;
      if (desc && desc.set) desc.set.call(el, token);
      else el.value = token;
      if (el._valueTracker) try { el._valueTracker.setValue(prev); } catch (e) {}
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      n++;
    } catch (e) {}
  };
  const call = (fn) => { try { fn(token); r++; } catch (e) {} };
  document.querySelectorAll(
    'input[name="cf-turnstile-response"], textarea[name="cf-turnstile-response"]'
  ).forEach(el => {
    setVal(el);
    for (const k of Object.keys(el)) {
      if (k.startsWith('__reactProps$')) {
        const p = el[k] || {};
        if (typeof p.onChange === 'function') call(p.onChange);
      }
    }
  });
  document.querySelectorAll('input[type="hidden"]').forEach(el => {
    if (/turnstile|cf-chl|cf_clearance/i.test(el.name || '')) setVal(el);
  });
  document.querySelectorAll('.cf-turnstile, [class*="turnstile"], [data-sitekey]').forEach(box => {
    for (const k of Object.keys(box)) {
      if (!k.startsWith('__reactFiber$')) continue;
      let f = box[k];
      for (let hop = 0; f && hop < 8; hop++, f = f.return) {
        const p = f.memoizedProps;
        if (!p || typeof p !== 'object') continue;
        for (const key of [
          // 'onCaptchaChange' là callback thật của manus.im (đã soi fiber)
          'onCaptchaChange', 'onChange', 'onSuccess', 'onVerify',
          'verifyCallback', 'onToken',
        ]) {
          if (typeof p[key] === 'function') call(p[key]);
        }
      }
    }
  });
  try {
    window.dispatchEvent(new CustomEvent('cf-turnstile-response', { detail: token }));
  } catch (e) {}
  // Một số app đọc getResponse() lúc submit thay vì state — đè luôn cho khớp.
  try {
    const wt = window.turnstile;
    if (wt) {
      const g = () => token;
      try { Object.defineProperty(wt, 'getResponse', { value: g, configurable: true }); }
      catch (e) { try { wt.getResponse = g; } catch (e2) {} }
      try { Object.defineProperty(wt, 'isExpired', { value: () => false, configurable: true }); }
      catch (e) {}
    }
  } catch (e) {}
  window.__manusTurnstileToken = token;
  return n + '/' + r;
})()
"""

TOKEN_READY_JS = r"""
(() => {
  const el = document.querySelector(
    'input[name="cf-turnstile-response"], textarea[name="cf-turnstile-response"]'
  );
  const v = el ? (el.value || '') : (window.__manusTurnstileToken || '');
  return v.length > 40;
})()
"""


def probe_solver(solver_url: str = DEFAULT_SOLVER_URL, timeout: float = 2.0) -> bool:
    s = requests.Session()
    s.trust_env = False  # đừng đi theo HTTP_PROXY hệ thống cho loopback
    try:
        r = s.get(f"{(solver_url or DEFAULT_SOLVER_URL).rstrip('/')}/", timeout=timeout, allow_redirects=False)
        return r.status_code < 500
    except Exception:
        return False


def solve_turnstile(
    *,
    website: str,
    site_key: str = MANUS_SITEKEY,
    solver_url: str = DEFAULT_SOLVER_URL,
    proxy: str = "",
    timeout: int = 90,
    poll_interval: float = 2.0,
) -> str:
    """Gọi solver local lấy token — chặn đến khi có token hoặc timeout."""
    base = (solver_url or DEFAULT_SOLVER_URL).rstrip("/")
    s = requests.Session()
    s.trust_env = False
    create_url = f"{base}/turnstile?url={quote(website or 'https://manus.im/login', safe='')}&sitekey={quote(site_key, safe='')}"
    if proxy:
        create_url += f"&proxy={quote(proxy, safe='')}"
    create = s.get(create_url, timeout=30)
    create.raise_for_status()
    task_id = (create.json() or {}).get("taskId")
    if not task_id:
        raise RuntimeError(f"solver không trả taskId: {create.text[:120]}")
    log.info("[captcha] solver taskId=%s — đợi token…", task_id)

    deadline = time.time() + max(20, int(timeout or 90))
    time.sleep(4.0)
    while time.time() < deadline:
        try:
            result = s.get(f"{base}/result?id={quote(str(task_id), safe='')}", timeout=20)
            result.raise_for_status()
            payload = result.json() or {}
            token = str((payload.get("solution") or {}).get("token") or "").strip()
            if not token and payload.get("value") and len(str(payload["value"])) > 40:
                token = str(payload["value"]).strip()
            if token and token != "CAPTCHA_FAIL":
                log.info("[captcha] có token len=%s", len(token))
                return token
            if payload.get("status") in ("error", "failed"):
                raise RuntimeError(f"solver báo lỗi: {str(payload)[:160]}")
        except RuntimeError:
            raise
        except Exception as exc:  # poll văng tạm thời — thử tiếp tới deadline
            log.debug("[captcha] poll error: %s", exc)
        time.sleep(poll_interval)
    raise TimeoutError(f"solver quá {int(timeout)}s chưa có token")


def _fill(template: str, value: str) -> str:
    return template.replace("%TOKEN%", value)


async def solve_and_inject(tab: Any, config: dict[str, Any], js_fn, *, page_url: str = "", reason: str = "") -> bool:
    """Trọn gói: lấy sitekey trên tab → solve → bơm token. Trả True nếu trang sẵn sàng.

    `js_fn` là helper `_js` của manreg.browser (chạy JS qua CDP).
    """
    cfg = config or {}
    ts = dict(cfg.get("turnstile") or {})
    if str(ts.get("mode") or "").lower() in ("off", "none", "disabled"):
        return False
    solver_url = str(ts.get("solver_url") or DEFAULT_SOLVER_URL)
    timeout = int(ts.get("timeout_sec") or 90)

    try:
        raw = await js_fn(tab, EXTRACT_SITEKEY_JS)
        site_key = str(raw or "").strip()
    except Exception:
        site_key = ""
    if not site_key.startswith("0x"):
        m = _SITEKEY_RE.search(site_key or "")
        site_key = m.group(1) if m else MANUS_SITEKEY

    url = page_url or "https://manus.im/login"
    log.info("[captcha] giải Turnstile%s sitekey=%s…", f" [{reason}]" if reason else "", site_key[:20])
    if not probe_solver(solver_url):
        log.warning("[captcha] solver %s không online — bỏ qua", solver_url)
        return False

    import asyncio

    proxy = str(cfg.get("proxy") or "")
    try:
        token = await asyncio.to_thread(
            solve_turnstile,
            website=url,
            site_key=site_key,
            solver_url=solver_url,
            proxy=proxy,
            timeout=timeout,
        )
    except Exception as exc:
        log.error("[captcha] solve fail: %s", exc)
        return False

    try:
        await js_fn(tab, _fill(INJECT_TOKEN_JS, json_dumps(token)))
        ready = await js_fn(tab, TOKEN_READY_JS)
    except Exception as exc:
        log.error("[captcha] inject fail: %s", exc)
        return False
    ok = bool(ready)
    log.info("[captcha] token %s trang", "sẵn sàng trên" if ok else "CHƯA vào")
    return ok


def json_dumps(value: str) -> str:
    import json

    return json.dumps(value)
