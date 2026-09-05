"""Mint Aliyun captcha + (nếu cần) submit signup trong Chrome ẩn/CDP."""

from __future__ import annotations

import asyncio
import base64
import json
import threading
import time
from pathlib import Path
from typing import Any

from zaireg.log import log
from zaireg.paths import DATA, ROOT, ensure_grok_on_path
from zaireg.stop import raise_if_stop

SIGNUP = "https://chat.z.ai/auth?action=signup"
SOLVER_PORT = 5073

# kill_zai_chrome() giết MỌI Chrome zai — 2 luồng solve song song sẽ tự giết
# nhau (cả prefetch nền). Khoá này xếp hàng Chrome lại.
_solve_lock = threading.Lock()

# Solver chạy như service Python riêng (pattern solver :5072 grok_tool):
# CHAY_SOLVER.bat / kick ẩn → reg tool chỉ POST HTTP thuần.
_kick_lock = threading.Lock()
_kicked = False


def _solver_url(config: dict[str, Any]) -> str:
    return str(config.get("solver_url") or f"http://127.0.0.1:{SOLVER_PORT}").rstrip("/")


def _solver_alive(url: str) -> bool:
    try:
        import requests

        s = requests.Session()
        s.trust_env = False
        return s.get(f"{url}/health", timeout=2).status_code < 500
    except Exception:
        return False


def _kick_solver(config: dict[str, Any]) -> None:
    """Spawn solver python ẩn một lần — 'mở một cái python lên giải ẩn'."""
    global _kicked
    with _kick_lock:
        if _kicked:
            return
        _kicked = True
    try:
        import subprocess
        import sys

        from zaireg.paths import ROOT, ensure_grok_on_path

        ensure_grok_on_path()
        hide: dict[str, Any] = {}
        try:
            from grokreg.core import winhide

            hide = winhide.kwargs()
        except Exception:
            pass
        port = _solver_url(config).rsplit(":", 1)[-1] or str(SOLVER_PORT)
        subprocess.Popen(
            [sys.executable, str(ROOT / "zaisolver.py"),
             "--host", "127.0.0.1", "--port", port],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **hide,
        )
        log.info("[captcha] đã kick solver python ẩn :%s", port)
    except Exception as e:
        log.debug("kick solver: %s", e)


def _solve_via_service(
    config: dict[str, Any],
    *,
    email: str,
    password: str,
    username: str = "",
) -> dict[str, Any] | None:
    """Giải qua solver :5073. Trả dict kết quả khi service sống (kể cả fail
    mint — để tránh mở Chrome thứ 2 tranh nhau), None khi service không lên
    được → caller fallback tự giải in-process."""
    url = _solver_url(config)
    # Trong process solver thì giải trực tiếp — gọi lại chính nó sẽ 503 self-
    # deadlock (đã gặp thật: 4 phút chờ 503 retry)
    import os

    if os.environ.get("ZAI_SOLVER_INTERNAL") == "1":
        return None
    was_alive = _solver_alive(url)
    if not was_alive:
        _kick_solver(config)
        for _ in range(15):
            time.sleep(1)
            if _solver_alive(url):
                was_alive = True
                break
        else:
            return None
    import requests

    s = requests.Session()
    s.trust_env = False
    deadline = time.time() + 240  # solver đang giải account khác thì xếp hàng
    while True:
        try:
            r = s.post(
                f"{url}/signup",
                json={
                    "email": email,
                    "password": password,
                    "username": username,
                    "proxy": str(config.get("proxy") or ""),
                },
                timeout=300,
            )
        except Exception as e:
            if was_alive:
                # service từng sống — KHÔNG fallback in-process (kill_zai_chrome
                # sẽ giết Chrome đang giải của service)
                log.warning("[captcha] solver %s rớt giữa chừng: %s", url, str(e)[:120])
                return {"token": "", "signup_ok": False, "resp": {},
                        "detail": f"solver rớt: {str(e)[:100]}"}
            return None
        if r.status_code == 200:
            return r.json()
        if r.status_code == 503 and time.time() < deadline:
            time.sleep(5)
            continue
        blob = {"token": "", "signup_ok": False, "resp": {},
                "detail": f"solver HTTP {r.status_code}: {r.text[:120]}"}
        log.warning("[captcha] solver fail: %s", blob["detail"])
        return blob

# Gắn TRƯỚC mọi script trang — wrap initAliyunCaptcha + console.log + fetch.
HOOK_JS = r"""
(() => {
  if (window.__ZAI_HOOKED) return 'already';
  window.__ZAI_HOOKED = true;
  window.__ZAI_CAP = null;
  window.__ZAI_VERIFIED = false;
  window.__ZAI_SIGNUP = null;
  window.__ZAI_FAIL = null;

  try {
    Object.defineProperty(document, 'hidden', {get: () => false, configurable: true});
    Object.defineProperty(document, 'visibilityState', {get: () => 'visible', configurable: true});
    document.hasFocus = () => true;
    // Chrome chạy offscreen (-32000) để giải nền — Aliyun đọc screenX/Y qua JS,
    // spooft về vị trí bình thường.
    Object.defineProperty(window, 'screenX', {get: () => 60, configurable: true});
    Object.defineProperty(window, 'screenY', {get: () => 60, configurable: true});
    Object.defineProperty(window, 'screenLeft', {get: () => 60, configurable: true});
    Object.defineProperty(window, 'screenTop', {get: () => 60, configurable: true});
  } catch (e) {}

  window.__ZAI_NET = window.__ZAI_NET || [];
  const take = (e) => {
    try {
      if (e == null) return;
      window.__ZAI_CAP = (typeof e === 'string') ? e : JSON.stringify(e);
      window.__ZAI_VERIFIED = true;
    } catch (err) { window.__ZAI_CAP = String(e); }
  };
  const noteNet = (u, extra) => {
    try {
      const s = String(u || '');
      if (!/captcha|aliyun|alicdn|feilin|certify|punish|nosecure/i.test(s)) return;
      if (window.__ZAI_NET.length < 40)
        window.__ZAI_NET.push(Object.assign({url: s.slice(0, 220)}, extra || {}));
    } catch (e) {}
  };
  const grabNet = async (u, res) => {
    try {
      const s = String(u || '');
      if (!/VerifyCaptcha|verify|comm\/gateway|ncc|captcha-/i.test(s)) return;
      let body = '';
      try { body = (await res.clone().text()).slice(0, 400); } catch (e) {}
      if (window.__ZAI_NET.length < 40)
        window.__ZAI_NET.push({url: s.slice(0, 180), status: res.status, body});
    } catch (e) {}
  };

  const wrapInit = (orig) => function(opts) {
    opts = opts || {};
    const prevOk = opts.success;
    const prevFail = opts.fail;
    const prevBiz = opts.captchaVerifyCallback;
    const prevGet = opts.getInstance;
    opts.success = function(e) {
      take(e);
      if (typeof prevOk === 'function') return prevOk.apply(this, arguments);
    };
    opts.fail = function(e) {
      try { window.__ZAI_FAIL = String(e && (e.message || e)); } catch (err) {}
      if (typeof prevFail === 'function') return prevFail.apply(this, arguments);
    };
    if (typeof prevBiz === 'function') {
      opts.captchaVerifyCallback = async function(e) {
        take(e);
        return prevBiz.apply(this, arguments);
      };
    }
    opts.getInstance = function(inst) {
      window.__ZAI_INST = inst;
      if (typeof prevGet === 'function') return prevGet(inst);
    };
    return orig.apply(this, arguments);
  };

  if (typeof window.initAliyunCaptcha === 'function') {
    window.initAliyunCaptcha = wrapInit(window.initAliyunCaptcha);
  } else {
    let _fn;
    Object.defineProperty(window, 'initAliyunCaptcha', {
      configurable: true,
      set(fn) { _fn = (typeof fn === 'function') ? wrapInit(fn) : fn; },
      get() { return _fn; }
    });
  }

  const clog = console.log.bind(console);
  console.log = function() {
    try {
      const a0 = String(arguments[0] || '');
      if (a0.indexOf('滑动成功') >= 0 || a0.indexOf('captcha') >= 0 && arguments.length > 1) {
        if (arguments[1] != null && (a0.indexOf('成功') >= 0 || a0.indexOf('参数') >= 0))
          take(arguments[1]);
      }
    } catch (e) {}
    return clog.apply(console, arguments);
  };

  const grabRes = async (url, res) => {
    try {
      const u = String(url || '');
      if (!/\/auths\/(signup|signin|resend)/i.test(u)) return;
      const text = await res.clone().text();
      let body = text.slice(0, 2500);
      try { body = JSON.parse(text); } catch (e) {}
      window.__ZAI_SIGNUP = {url: u.slice(0, 180), status: res.status, body};
    } catch (e) {}
  };
  const ofetch = window.fetch;
  if (typeof ofetch === 'function') {
    window.fetch = async function() {
      const req = arguments[0];
      const u = (req && req.url) ? req.url : req;
      noteNet(u, {via: 'fetch'});
      const res = await ofetch.apply(this, arguments);
      try { grabNet(u, res); } catch (e) {}
      grabRes(u, res);
      return res;
    };
  }
  const ox = XMLHttpRequest.prototype.open;
  const os = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(m, u) {
    this.__zai_u = u;
    return ox.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function() {
    this.addEventListener('load', function() {
      try {
        const u = String(this.__zai_u || '');
        if (/\/auths\/(signup|signin|resend)/i.test(u)) {
          let body = (this.responseText || '').slice(0, 2500);
          try { body = JSON.parse(this.responseText); } catch (e) {}
          window.__ZAI_SIGNUP = {url: u.slice(0, 180), status: this.status, body};
        }
        if (/VerifyCaptcha|verify|comm\/gateway|ncc|captcha-/i.test(u)) {
          if (window.__ZAI_NET.length < 40)
            window.__ZAI_NET.push({url: u.slice(0, 180), status: this.status, body: String(this.responseText || '').slice(0, 400)});
        }
      } catch (e) {}
    });
    return os.apply(this, arguments);
  };
  return 'hooked';
})()
"""

REVEAL_JS = r"""
(() => {
  // KHÔNG position:fixed cả wrapper — puzzle 300px sẽ bị đẩy y<0.
  const el = document.getElementById('captcha-element')
    || document.getElementById('chat-captcha-element')
    || document.getElementById('aliyunCaptcha-float-wrapper');
  if (el && el.scrollIntoView) {
    try { el.scrollIntoView({block: 'center', inline: 'nearest'}); } catch (e) {}
  }
  const img = document.getElementById('aliyunCaptcha-img');
  const r = img ? img.getBoundingClientRect() : null;
  if (r && (r.y < 8 || r.bottom > innerHeight - 8)) {
    const wrap = document.getElementById('aliyunCaptcha-float-wrapper') || el;
    if (wrap && wrap.style) {
      wrap.style.setProperty('position', 'fixed', 'important');
      wrap.style.setProperty('left', '24px', 'important');
      wrap.style.setProperty('top', '320px', 'important');
      wrap.style.setProperty('z-index', '2147483646', 'important');
    }
  }
  const start = document.getElementById('aliyunCaptcha-start-icon')
    || document.getElementById('aliyunCaptcha-captcha-text-box')
    || document.getElementById('aliyunCaptcha-captcha-body');
  if (start) { try { start.click(); } catch (e) {} }
  return true;
})()
"""

PROBE_JS = r"""
(() => {
  const boxOf = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {id: el.id || el.className || '', x: r.x, y: r.y, w: r.width, h: r.height,
            tag: (el.tagName || '').toLowerCase(), cls: String(el.className || '').slice(0, 80)};
  };
  const ids = [
    'captcha-element','chat-captcha-element',
    'aliyunCaptcha-float-wrapper','aliyunCaptcha-captcha-wrapper',
    'aliyunCaptcha-captcha-body','aliyunCaptcha-sliding-slider',
    'aliyunCaptcha-slider','aliyunCaptcha-start-icon',
    'aliyunCaptcha-captcha-text-box','aliyunCaptcha-img',
    'aliyunCaptcha-puzzle','aliyunCaptcha-question'
  ];
  const boxes = [];
  ids.forEach(id => { const b = boxOf(document.getElementById(id)); if (b) boxes.push(b); });
  document.querySelectorAll(
    '#captcha-element img, #captcha-element canvas, #aliyunCaptcha-float-wrapper img, #aliyunCaptcha-float-wrapper canvas, [class*="puzzle"], [class*="imgbox"]'
  ).forEach(el => {
    const b = boxOf(el);
    if (b && b.w > 40 && b.h > 40) boxes.push(b);
  });
  document.querySelectorAll('[id*="slider"], [class*="slider"], [id*="slide"]').forEach(el => {
    const b = boxOf(el);
    if (b && b.w > 10 && b.h > 8) boxes.push(b);
  });
  const iframes = [...document.querySelectorAll('iframe')].map(f => {
    const r = f.getBoundingClientRect();
    return {src: (f.src||'').slice(0,160), x: r.x, y: r.y, w: r.width, h: r.height};
  });
  const body = document.getElementById('aliyunCaptcha-captcha-body');
  const capEl = document.getElementById('captcha-element') || document.getElementById('chat-captcha-element');
  const passed = !!(
    (body && body.classList.contains('verified')) ||
    (capEl && /passed|verified|验证通过/i.test(capEl.innerText || ''))
  );
  if (passed) window.__ZAI_VERIFIED = true;
  const imgs = [...document.querySelectorAll('#captcha-element img, #aliyunCaptcha-float-wrapper img')].map(img => {
    const r = img.getBoundingClientRect();
    return {id: img.id, cls: String(img.className||'').slice(0,60),
            src: String(img.currentSrc || img.src || '').slice(0,180),
            nw: img.naturalWidth, nh: img.naturalHeight,
            x:r.x,y:r.y,w:r.width,h:r.height};
  });
  return JSON.stringify({
    cap: window.__ZAI_CAP,
    verified: !!(window.__ZAI_VERIFIED || passed),
    fail: window.__ZAI_FAIL,
    signup: window.__ZAI_SIGNUP,
    hooked: !!window.__ZAI_HOOKED,
    hasInit: typeof window.initAliyunCaptcha,
    hasInst: !!(window.__ZAI_INST),
    failedBody: !!(body && body.classList.contains('fail')),
    boxes,
    imgs,
    net: window.__ZAI_NET || [],
    iframes,
    n_iframes: iframes.length,
    url: location.href,
    text: ((capEl && capEl.innerText) || '').slice(0, 180)
  });
})()
"""


async def _js(tab: Any, script: str) -> Any:
    for name in ("execute_script", "evaluate"):
        fn = getattr(tab, name, None)
        if not fn:
            continue
        try:
            raw = await fn(script)
        except TypeError:
            try:
                raw = await fn(script, return_by_value=True)
            except Exception:
                continue
        except Exception:
            continue
        if isinstance(raw, dict):
            inner = raw
            for _ in range(6):
                if not isinstance(inner, dict):
                    break
                if "value" in inner and ("type" in inner or "description" in inner):
                    return inner.get("value")
                if "result" in inner:
                    inner = inner["result"]
                    continue
                break
            return inner
        return raw
    return None


async def _eval_promise(tab: Any, script: str) -> Any:
    raw = await _cdp(
        tab,
        "Runtime.evaluate",
        {"expression": script, "awaitPromise": True, "returnByValue": True},
    )
    payload = raw.get("result") if isinstance(raw, dict) else raw
    if isinstance(payload, dict):
        inner = payload.get("result") if "result" in payload else payload
        if isinstance(inner, dict) and "value" in inner:
            return inner.get("value")
        return inner
    return payload


async def _inpage_signup(
    tab: Any, *, email: str, password: str, username: str, cap: str
) -> dict[str, Any]:
    """POST /auths/signup trong Chrome — cùng cookie/session với token Aliyun."""
    script = f"""
(async () => {{
  const cap = {json.dumps(cap)} || window.__ZAI_CAP || '';
  const r = await fetch('https://chat.z.ai/api/v1/auths/signup', {{
    method: 'POST',
    credentials: 'include',
    headers: {{
      'Accept': 'application/json',
      'Content-Type': 'application/json',
      'X-FE-Version': 'prod-fe-1.1.84'
    }},
    body: JSON.stringify({{
      name: {json.dumps(username)},
      email: {json.dumps(email)},
      password: {json.dumps(password)},
      profile_image_url: '',
      sso_redirect: '',
      captcha_verify_param: cap
    }})
  }});
  let body = await r.text();
  try {{ body = JSON.parse(body); }} catch (e) {{}}
  const out = {{status: r.status, http: r.status, body, url: r.url}};
  window.__ZAI_SIGNUP = out;
  return JSON.stringify(out);
}})()
"""
    raw = await _eval_promise(tab, script)
    info = _parse_probe(raw)
    if info.get("body") and isinstance(info["body"], dict):
        info["body"].setdefault("http", info.get("status") or info.get("http"))
    return info


async def _cdp(tab: Any, method: str, params: dict[str, Any] | None = None) -> Any:
    fn = getattr(tab, "_execute_command", None)
    if not fn:
        raise RuntimeError("no CDP")
    return await fn({"method": method, "params": params or {}})


async def _sleep(sec: float) -> None:
    raise_if_stop()
    await asyncio.sleep(sec)


def _port_busy(port: int) -> bool:
    try:
        import requests

        r = requests.get(f"http://127.0.0.1:{port}/json/version", timeout=0.4)
        return r.status_code < 500
    except Exception:
        return False


def kill_zai_chrome() -> int:
    import subprocess

    ps = r"""
$ErrorActionPreference='SilentlyContinue'
$n = 0
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | Where-Object {
  $_.CommandLine -and (
    $_.CommandLine -match 'zai\\chrome_runs' -or
    $_.CommandLine -match 'zai/chrome_runs' -or
    $_.CommandLine -match 'remote-debugging-port=95'
  )
} | ForEach-Object {
  try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $n++ } catch {}
}
Write-Output $n
"""
    try:
        hide = {}
        try:
            ensure_grok_on_path()
            from grokreg.core import winhide

            hide = winhide.kwargs()
        except Exception:
            pass
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=12,
            **hide,
        )
        n = int((r.stdout or "0").strip().splitlines()[-1] or 0)
        if n:
            log.info("Don Chrome Z.ai cu: killed≈%s", n)
        return n
    except Exception as e:
        log.debug("kill zai chrome: %s", e)
        return 0


def _chrome_options(config: dict[str, Any], port: int):
    from pydoll.browser.options import ChromiumOptions

    opt = ChromiumOptions()

    def add(arg: str) -> None:
        try:
            opt.add_argument(arg)
        except Exception:
            pass

    profile = ROOT / "chrome_runs" / f"run_{int(time.time())}"
    profile.mkdir(parents=True, exist_ok=True)
    add(f"--user-data-dir={profile}")
    add(f"--remote-debugging-port={port}")
    add("--disable-blink-features=AutomationControlled")
    # Chrome bị che/offscreen trên Windows bị throttle renderer → mỗi
    # Input.dispatchMouseEvent mất ~5s, kéo slider thành ~95s → Aliyun luôn
    # từ chối. Tắt hẳn occlusion/backgrounding throttling.
    add("--disable-backgrounding-occluded-windows")
    add("--disable-renderer-backgrounding")
    add("--disable-background-timer-throttling")
    add("--disable-features=CalculateNativeWinOcclusion")
    add("--window-size=560,820")
    proxy = str(config.get("proxy") or "").strip()
    if proxy:
        add(f"--proxy-server={proxy}")
    # ẩn mặc định (giải nền, không cướp màn hình); flag anti-throttle ở trên
    # giữ tốc độ drag. Nếu widget không layout thì _ensure_visible kéo ra.
    add(f"--window-position={config.get('chrome_window_position') or '-32000,-32000'}")
    return opt


async def _open_browser(config: dict[str, Any]):
    from pydoll.browser.chromium import Chrome

    kill_zai_chrome()
    await _sleep(0.5)
    port = int(config.get("chrome_debug_port") or 9554)
    if _port_busy(port):
        for cand in range(port, port + 30):
            if not _port_busy(cand):
                port = cand
                break
    last: Exception | None = None
    for attempt in range(1, 4):
        opt = _chrome_options(config, port)
        log.info("[captcha] Chrome start port=%s lan %s", port, attempt)
        try:
            browser = Chrome(options=opt, connection_port=port)
            tab = await browser.start()
            return browser, tab
        except Exception as e:
            last = e
            log.warning("[captcha] Chrome fail lan %s: %s", attempt, e)
            kill_zai_chrome()
            await _sleep(1.0)
            port += 1
    raise last or RuntimeError("Chrome start fail")


async def _close(browser: Any) -> None:
    if browser:
        for name in ("stop", "close"):
            fn = getattr(browser, name, None)
            if fn:
                try:
                    await fn()
                except Exception:
                    pass
                break
    kill_zai_chrome()


async def _install_early_hook(tab: Any) -> None:
    try:
        await _cdp(tab, "Page.addScriptToEvaluateOnNewDocument", {"source": HOOK_JS})
        log.info("[captcha] hook onNewDocument OK")
    except Exception as e:
        log.warning("[captcha] onNewDocument: %s", e)
    try:
        await _js(tab, HOOK_JS)
    except Exception:
        pass


async def _ensure_visible(tab: Any, info: dict[str, Any]) -> None:
    boxes = info.get("boxes") or []
    laid_out = any(float(b.get("w") or 0) >= 80 for b in boxes)
    if laid_out:
        return
    log.info("[captcha] widget chưa layout — kéo Chrome vào màn hình")
    try:
        raw = await _cdp(tab, "Browser.getWindowForTarget", {})
        payload = raw.get("result") if isinstance(raw, dict) else raw
        wid = (payload or {}).get("windowId") if isinstance(payload, dict) else None
        if wid is None and isinstance(raw, dict):
            wid = raw.get("windowId")
        if wid is not None:
            await _cdp(
                tab,
                "Browser.setWindowBounds",
                {
                    "windowId": wid,
                    "bounds": {
                        "left": 40,
                        "top": 40,
                        "width": 560,
                        "height": 820,
                        "windowState": "normal",
                    },
                },
            )
            return
    except Exception as e:
        log.debug("[captcha] setWindowBounds: %s", e)
    await _js(tab, "try { window.moveTo(40,40); window.resizeTo(560,820); } catch(e) {}")


async def _mouse_ev(tab: Any, typ: str, x: float, y: float, pressed: bool = False) -> None:
    from pydoll.commands.input_commands import InputCommands
    from pydoll.protocol.input.types import MouseButton, MouseEventType

    mp = {
        "mouseMoved": MouseEventType.MOUSE_MOVED,
        "mousePressed": MouseEventType.MOUSE_PRESSED,
        "mouseReleased": MouseEventType.MOUSE_RELEASED,
    }[typ]
    kw: dict[str, Any] = {"button": MouseButton.LEFT}
    if typ in ("mousePressed", "mouseReleased"):
        kw["click_count"] = 1
    cmd = InputCommands.dispatch_mouse_event(type=mp, x=int(round(x)), y=int(round(y)), **kw)
    # Aliyun cần buttons=1 khi move lúc đang giữ chuột
    if pressed or typ == "mousePressed":
        params = cmd.get("params")
        if isinstance(params, dict):
            params["buttons"] = 1
    await tab._execute_command(cmd)


async def _cdp_click(tab: Any, x: float, y: float) -> None:
    await _mouse_ev(tab, "mouseMoved", x, y)
    await _sleep(0.04)
    await _mouse_ev(tab, "mousePressed", x, y)
    await _sleep(0.06)
    await _mouse_ev(tab, "mouseReleased", x, y)


IMGS_JS = r"""
(() => {
  const toData = (img) => {
    if (!img) return '';
    const s = String(img.src || img.currentSrc || '');
    if (s.startsWith('data:image')) return s;
    try {
      const c = document.createElement('canvas');
      c.width = img.naturalWidth || img.width;
      c.height = img.naturalHeight || img.height;
      if (!c.width || !c.height) return s;
      c.getContext('2d').drawImage(img, 0, 0);
      return c.toDataURL('image/png');
    } catch (e) { return s; }
  };
  const bg = document.getElementById('aliyunCaptcha-img');
  const pc = document.getElementById('aliyunCaptcha-puzzle');
  return JSON.stringify({
    bg: toData(bg),
    piece: toData(pc),
    bw: bg ? bg.naturalWidth : 0,
    bh: bg ? bg.naturalHeight : 0,
    pw: pc ? pc.naturalWidth : 0,
    ph: pc ? pc.naturalHeight : 0
  });
})()
"""


def _decode_data_url(url: str) -> Any | None:
    if not url or not url.startswith("data:image"):
        return None
    try:
        from PIL import Image
        import io

        raw = url.split(",", 1)[1]
        return Image.open(io.BytesIO(base64.b64decode(raw)))
    except Exception as e:
        log.debug("[captcha] decode img: %s", e)
        return None


def _find_hole(bg: Any, piece: Any) -> tuple[float, float] | None:
    """Tìm lỗ cho captcha INPAINTING (z.ai dùng loại này — xem net log
    ``CaptchaType: INPAINTING``).

    Lỗ được AI tô lại nên nội dung KHÔNG khớp mảnh (match pixel/SAD/NCC đều
    lừa — bắt nhầm vật cùng tông màu). Dấu hiệu đúng: vùng lỗ mượt bất thường
    (mất biên tần số cao) so với xung quanh, mép lỗ còn seam dọc.

    Trả về (frac, alt_frac) như _match_strip, None nếu nền phẳng toàn bộ.
    """
    try:
        import numpy as np

        b = np.asarray(bg.convert("L"), float)
        p = np.asarray(piece.convert("L"), float)
        ph, pw = p.shape
        bh, bw = b.shape
        if pw < 8 or bw < pw + 12 or bh < 40:
            return None
        rows = np.where(p.std(axis=1) > 8)[0]
        if len(rows) < 20:
            return None
        r0, r1 = int(rows.min()), min(bh, int(rows.max()) + 1)
        gy, gx = np.gradient(b)
        e = np.hypot(gx, gy)[r0:r1]
        flat = b[r0:r1]
        cands: list[tuple[float, float]] = []
        for x in range(6, bw - pw - 5):
            win = flat[:, x : x + pw]
            # bỏ vùng phẳng đồng nhất (margin trắng/tường) và vùng gần-trắng
            # có phác nhạt (std đủ nhưng không phải nội dung)
            if float(win.std()) < 6 or float(win.mean()) > 230:
                continue
            inside = float(e[:, x : x + pw].mean())
            # lỗ = đảo mượt giữa vùng nhiều chi tiết: soenergy trong cửa sổ
            # với lân cận (±55px) thay vì toàn ảnh — phác nhạt trên nền trống
            # (hoa cách điệu) thì lân cận cũng trống → không thắng được
            lo = max(0, x - 55)
            hi = min(bw - pw, x + pw + 55)
            outs = [
                float(e[:, xx : xx + pw].mean())
                for xx in range(lo, hi + 1, 4)
                if abs(xx - x) > pw
            ]
            out_e = sum(outs) / len(outs) if outs else inside
            cands.append((inside / max(4.0, out_e), float(x)))
        if not cands:
            return None
        cands.sort()
        best = cands[0][1]
        alt = cands[min(1, len(cands) - 1)][1]
        # ratio gần 1 = không có ứng viên nào nổi bật (mảnh rộng/nền đều) —
        # trả None cho matcher cũ thay vì ứng viên rác
        if cands[0][0] > 0.85:
            log.info("[captcha] find_hole: không rõ (best ratio=%.2f) — fallback", cands[0][0])
            return None
        log.info(
            "[captcha] find_hole: ratio=%.2f@%d alt@%d (trong %d cửa sổ khác phẳng)",
            cands[0][0], int(best), int(alt), len(cands),
        )
        return max(0.08, min(0.92, best / bw)), max(0.08, min(0.92, alt / bw))
    except Exception as e:
        log.debug("[captcha] find_hole: %s", e)
        return None


def _match_strip(bg: Any, piece: Any) -> float:
    """Matcher cũ cho slide thường: ghép cạnh mảnh vào cột nền."""
    bg = bg.convert("RGBA")
    piece = piece.convert("RGBA")
    bw, bh = bg.size
    pw, ph = piece.size
    if pw < 4 or ph < 20 or bw < pw + 4:
        return 0.72
    bp = bg.load()
    pp = piece.load()

    def seam(x: int) -> float:
        s = 0.0
        n = 0
        # cạnh trái mảnh vs cột nền ngay trước
        if x > 0:
            for y in range(0, min(ph, bh), 2):
                pr, pg, pb, pa = pp[0, y]
                if pa < 30:
                    continue
                br, bg_, bb, _ = bp[x - 1, y]
                s += abs(pr - br) + abs(pg - bg_) + abs(pb - bb)
                n += 1
        if x + pw < bw:
            for y in range(0, min(ph, bh), 2):
                pr, pg, pb, pa = pp[pw - 1, y]
                if pa < 30:
                    continue
                br, bg_, bb, _ = bp[x + pw, y]
                s += abs(pr - br) + abs(pg - bg_) + abs(pb - bb)
                n += 1
        return s / max(1, n)

    def sad(x: int) -> float:
        s = 0.0
        n = 0
        for dx in range(pw):
            for y in range(0, min(ph, bh), 2):
                pr, pg, pb, pa = pp[dx, y]
                if pa < 30:
                    continue
                br, bg_, bb, _ = bp[x + dx, y]
                s += abs(pr - br) + abs(pg - bg_) + abs(pb - bb)
                n += 1
        return s / max(1, n)

    # bỏ mép — seam hay dồn về x≈0 hoặc x≈max
    lo, hi = 6, bw - pw - 6
    if hi <= lo:
        lo, hi = 1, max(2, bw - pw)
    best_s, best_x = 1e18, (lo + hi) // 2
    best_d, best_xd = 1e18, best_x
    for x in range(lo, hi):
        sc = seam(x)
        if sc < best_s:
            best_s, best_x = sc, x
        sd = sad(x)
        if sd < best_d:
            best_d, best_xd = sd, x
    frac_s = max(0.08, min(0.92, best_x / float(bw)))
    frac_d = max(0.08, min(0.92, best_xd / float(bw)))
    # seam rất thấp = khớp cạnh rõ (ảnh có khe). SAD tốt khi nền là ảnh đầy đủ.
    if best_s < 35:
        frac, alt = frac_s, frac_d
    elif best_d < best_s * 0.7:
        frac, alt = frac_d, frac_s
    else:
        frac, alt = frac_d, frac_s
    log.info(
        "[captcha] match strip sad=%.1f@%s (%.2f) seam=%.1f@%s (%.2f) → %.2f alt=%.2f",
        best_d, best_xd, frac_d, best_s, best_x, frac_s, frac, alt,
    )
    return frac, alt


async def _frac_from_imgs(tab: Any) -> tuple[float, float, float] | None:
    raw = _parse_probe(await _js(tab, IMGS_JS))
    bg = _decode_data_url(str(raw.get("bg") or ""))
    piece = _decode_data_url(str(raw.get("piece") or ""))
    pw = float(raw.get("pw") or 0)
    if not bg or not piece:
        log.info("[captcha] imgs missing bg=%s piece=%s", bool(bg), bool(piece))
        return None
    try:
        bg.convert("RGB").save(DATA / "last_puzzle_bg.png")
        piece.convert("RGB").save(DATA / "last_puzzle_piece.png")
    except Exception:
        pass
    pair = _find_hole(bg, piece)
    if pair is None:
        pair2 = _match_strip(bg, piece)
        pair = (float(pair2[0]), float(pair2[1])) if isinstance(pair2, tuple) else None
    if pair is None:
        return None
    return pair[0], pair[1], pw


def _gap_frac(png: Path, clip: dict[str, float] | None = None) -> float:
    """Ước lượng vị trí khe puzzle (0–1 theo chiều ngang ảnh)."""
    try:
        from PIL import Image, ImageFilter, ImageOps

        im = Image.open(png).convert("RGB")
        if clip:
            x, y = int(max(0, clip["x"])), int(max(0, clip["y"]))
            w, h = int(clip["w"]), int(clip["h"])
            im = im.crop((x, y, min(im.size[0], x + w), min(im.size[1], y + h)))
        g = ImageOps.autocontrast(im.convert("L")).filter(ImageFilter.FIND_EDGES)
        w, h = g.size
        if w < 40 or h < 20:
            return 0.82
        # khe thường nằm ở nửa trên (ảnh), không phải thanh trượt đáy
        crop = g.crop((0, 0, w, max(10, int(h * 0.78))))
        px = crop.load()
        ch = crop.size[1]
        piece = max(18, int(w * 0.11))
        best_x, best = 20, -1.0
        for x in range(int(w * 0.12), w - piece - 4):
            col = 0.0
            for xx in range(x, x + 3):
                for yy in range(0, ch, 2):
                    col += px[xx, yy]
            if col > best:
                best, best_x = col, x
        frac = max(0.22, min(0.94, best_x / float(w)))
        log.info("[captcha] gap x=%s/%s frac=%.2f", best_x, w, frac)
        return frac
    except Exception as e:
        log.debug("[captcha] gap: %s", e)
        return 0.78


async def _screenshot(tab: Any, path: Path, clip: dict[str, float] | None = None) -> bool:
    try:
        params: dict[str, Any] = {"format": "png"}
        if clip and clip.get("w") and clip.get("h"):
            params["clip"] = {
                "x": max(0.0, float(clip["x"])),
                "y": max(0.0, float(clip["y"])),
                "width": float(clip["w"]),
                "height": float(clip["h"]),
                "scale": 1,
            }
        raw = await _cdp(tab, "Page.captureScreenshot", params)
        payload = raw.get("result") if isinstance(raw, dict) else raw
        data = (payload or {}).get("data") if isinstance(payload, dict) else None
        if not data and isinstance(raw, dict):
            data = raw.get("data")
        if data:
            path.write_bytes(base64.b64decode(data))
            return True
    except Exception as e:
        log.debug("[captcha] cdp shot: %s", e)
    take = getattr(tab, "take_screenshot", None)
    if take and not clip:
        try:
            await take(str(path))
            return path.exists() and path.stat().st_size > 100
        except Exception as e:
            log.debug("[captcha] take_screenshot: %s", e)
    return False


def _parse_probe(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    if isinstance(raw, dict):
        return raw
    return {}


def _pick_slider(boxes: list[dict[str, Any]]) -> dict[str, Any] | None:
    prefer_ids = (
        "aliyunCaptcha-sliding-slider",
        "aliyunCaptcha-slider",
        "aliyunCaptcha-start-icon",
        "aliyunCaptcha-captcha-body",
        "aliyunCaptcha-captcha-wrapper",
        "aliyunCaptcha-float-wrapper",
        "captcha-element",
    )
    by_id = {str(b.get("id") or ""): b for b in boxes}
    for i in prefer_ids:
        b = by_id.get(i)
        if b and float(b.get("w") or 0) >= 8:
            return b
    wide = [b for b in boxes if float(b.get("w") or 0) >= 160]
    if wide:
        return max(wide, key=lambda b: float(b.get("w") or 0) * max(8.0, float(b.get("h") or 1)))
    return boxes[0] if boxes else None


def _pick_puzzle(boxes: list[dict[str, Any]]) -> dict[str, Any] | None:
    cands = [
        b
        for b in boxes
        if float(b.get("h") or 0) >= 80 and float(b.get("w") or 0) >= 160
        and str(b.get("tag") or "") in ("img", "canvas", "div")
        and "captcha-body" not in str(b.get("id") or "")
    ]
    if not cands:
        return None
    return max(cands, key=lambda b: float(b.get("w") or 0) * float(b.get("h") or 1))


async def _fill_form(tab: Any, email: str, password: str, username: str) -> dict[str, Any]:
    script = f"""
(() => {{
  const set = (el, val) => {{
    if (!el) return false;
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    if (desc && desc.set) desc.set.call(el, val); else el.value = val;
    el.dispatchEvent(new Event('input', {{bubbles: true}}));
    el.dispatchEvent(new Event('change', {{bubbles: true}}));
    return true;
  }};
  const name = document.querySelector('input[autocomplete="name"]')
    || document.querySelector('input[placeholder*="Name" i]');
  const email = document.querySelector('input[name="email"]')
    || document.querySelector('input[type="email"]');
  const pass = document.querySelector('input[name="new-password"]')
    || document.querySelector('input[autocomplete="new-password"]')
    || document.querySelector('input[type="password"]');
  return JSON.stringify({{
    name: set(name, {json.dumps(username)}),
    email: set(email, {json.dumps(email)}),
    pass: set(pass, {json.dumps(password)}),
    found: {{name: !!name, email: !!email, pass: !!pass}}
  }});
}})()
"""
    return _parse_probe(await _js(tab, script))


async def _submit_form(tab: Any) -> str:
    raw = await _js(
        tab,
        """
(() => {
  const btn = document.querySelector('button.ButtonCreateAccount')
    || document.querySelector('form button[type="submit"]');
  if (btn && !btn.disabled) { btn.click(); return 'click'; }
  const f = document.querySelector('form');
  if (f) {
    if (typeof f.requestSubmit === 'function') { f.requestSubmit(); return 'requestSubmit'; }
    f.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
    return 'submit';
  }
  return 'none';
})()
""",
    )
    return str(raw or "none")


def _signup_ok(info: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    sig = info.get("signup")
    if not isinstance(sig, dict):
        url = str(info.get("url") or "")
        if "/auth/verify" in url:
            return True, {"http": 200, "browser_redirect": url}
        return False, {}
    status = int(sig.get("status") or 0)
    body = sig.get("body")
    blob = body if isinstance(body, dict) else {"raw": body, "http": status}
    if isinstance(blob, dict):
        blob.setdefault("http", status)
    text = json.dumps(blob, default=str).lower()
    if status and status < 400 and "captcha" not in text and "failed" not in text:
        return True, blob if isinstance(blob, dict) else {"http": status}
    if "/auth/verify" in str(info.get("url") or ""):
        return True, blob if isinstance(blob, dict) else {"http": 200}
    return False, blob if isinstance(blob, dict) else {}


PIECE_X_JS = r"""
(() => {
  const el = document.getElementById('aliyunCaptcha-puzzle');
  if (!el) return '{}';
  const r = el.getBoundingClientRect();
  return JSON.stringify({x: r.x});
})()
"""


async def _cdp_drag_to(
    tab: Any, x0: float, y0: float, piece_x0: float, target_px: float
) -> float:
    """Kéo VÒNG ĐÓNG: giữ chuột, đọc vị trí mảnh giữa chừng qua CDP và nhả
    đúng lúc mảnh tới mục tiêu. Hệ số mảnh/thumb đổi theo TỪNG puzzle (pw
    mới mỗi lượt) nên closed-loop là cách duy nhất kéo准确 không cần model.
    Trả về khoảng đã kéo."""
    import random

    await _mouse_ev(tab, "mouseMoved", x0, y0)
    await _sleep(0.06)
    await _mouse_ev(tab, "mousePressed", x0, y0)
    await _sleep(0.12)
    moved = 0.0
    for i in range(40):
        step = max(6.0, target_px / 12.0)
        moved += step * random.uniform(0.7, 1.3)
        await _mouse_ev(
            tab, "mouseMoved", x0 + moved, y0 + random.uniform(-1.2, 1.2), pressed=True
        )
        await _sleep(0.045)
        raw = _parse_probe(await _js(tab, PIECE_X_JS))
        px = raw.get("x")
        if px is not None:
            pd = float(px) - piece_x0
            if pd >= target_px - 2:
                break
            # gần đích thì bước nhỏ lại để đổ chính xác ±2px
            if pd >= target_px - 25:
                moved -= step * 0.55
        if moved >= target_px * 1.9:
            break
    await _sleep(0.08)
    await _mouse_ev(tab, "mouseReleased", x0 + moved, y0)
    return moved


async def _drag_once(tab: Any, info: dict[str, Any], target_px: float) -> dict[str, Any]:
    boxes = list(info.get("boxes") or [])
    slider = _pick_slider(boxes)
    frames = [
        f
        for f in (info.get("iframes") or [])
        if float(f.get("w") or 0) >= 80
    ]
    target = slider
    if not target and frames:
        target = max(frames, key=lambda f: float(f.get("w") or 0))
    if not target:
        raise RuntimeError("không thấy slider Aliyun")

    w, h = float(target["w"]), float(target["h"])
    tid = str(target.get("id") or "")
    puzzle = _pick_puzzle(boxes)
    img = next((b for b in boxes if b.get("id") == "aliyunCaptcha-img"), None)
    puzzle = puzzle or img
    slide = next((b for b in boxes if b.get("id") == "aliyunCaptcha-sliding-slider"), None)
    if slide and float(slide.get("w") or 0) >= 8:
        target = slide
        w, h = float(target["w"]), float(target["h"])
        tid = str(target.get("id") or "")

    # start-icon / thanh 40px = "Click to start" — chỉ click, không kéo
    if "sliding" not in tid and "slider" not in tid.lower():
        click = next(
            (b for b in boxes if b.get("id") in ("aliyunCaptcha-start-icon", "aliyunCaptcha-captcha-text-box")),
            target,
        )
        x0 = float(click["x"]) + float(click["w"]) / 2
        y0 = float(click["y"]) + float(click["h"]) / 2
        log.info("[captcha] click start (%.0f,%.0f) id=%s", x0, y0, str(click.get("id") or "")[:30])
        await _cdp_click(tab, x0, y0)
        return

    track_w = float((img or puzzle or {}).get("w") or 0) or 300.0
    x0 = float(target["x"]) + w / 2
    y0 = float(target["y"]) + h / 2
    target_px = max(12.0, min(float(track_w) - 20.0, target_px))

    log.info(
        "[captcha] drag tới mảnh %.0fpx (track=%.0f) id=%s", target_px, track_w, tid[:40],
    )
    pos_js = r"""
(() => {
  const box = (id) => {
    const el = document.getElementById(id);
    if (!el) return {};
    const r = el.getBoundingClientRect();
    return {x:r.x,y:r.y,w:r.width,h:r.height};
  };
  return JSON.stringify({
    pz: box('aliyunCaptcha-puzzle'),
    sl: box('aliyunCaptcha-sliding-slider'),
    cap: window.__ZAI_CAP,
    ver: !!window.__ZAI_VERIFIED
  });
})()
"""
    before = _parse_probe(await _js(tab, pos_js))
    pz0 = float((before.get("pz") or {}).get("x") or 0)
    if pz0 <= 0:
        pz0 = float((img or puzzle or {}).get("x") or 114)
    t0 = time.time()
    moved = await _cdp_drag_to(tab, x0, y0, pz0, target_px)
    await _sleep(1.1)
    after = _parse_probe(await _js(tab, pos_js))
    drag_s = time.time() - t0
    pz1 = float((after.get("pz") or {}).get("x") or 0)
    log.info(
        "[captcha] kéo %.0fpx → mảnh %.0f→%.0f cap=%s drag=%.1fs%s",
        moved, pz0, pz1, bool(after.get("cap")), drag_s,
        " ← CDP chậm bất thường (bị throttle/che cửa sổ?)" if drag_s > 6 else "",
    )
    return {
        "puzzle_delta": abs(pz1 - pz0),
        "cmd": float(moved),
        "cap": bool(after.get("cap")),
    }


async def _solve_async(
    config: dict[str, Any],
    *,
    email: str = "",
    password: str = "",
    username: str = "",
    submit: bool = False,
) -> dict[str, Any]:
    DATA.mkdir(parents=True, exist_ok=True)
    browser = None
    out: dict[str, Any] = {"token": "", "signup_ok": False, "resp": {}, "detail": ""}
    try:
        browser, tab = await _open_browser(config)
        await _install_early_hook(tab)
        go = getattr(tab, "go_to", None) or getattr(tab, "goto", None)
        if go:
            await go(SIGNUP)
        else:
            await _js(tab, f"location.href={json.dumps(SIGNUP)}")
        await _sleep(2.8)
        await _js(tab, HOOK_JS)

        if email and password:
            filled = await _fill_form(tab, email, password, username or email.split("@")[0])
            log.info("[captcha] fill form %s", filled.get("found") or filled)

        await _js(tab, REVEAL_JS)
        await _sleep(1.2)

        last_info: dict[str, Any] = {}
        fallback: list[float] = []
        pw = 0.0
        missing_streak = 0
        for i in range(12):
            raise_if_stop()
            info = _parse_probe(await _js(tab, PROBE_JS))
            last_info = info
            cap = info.get("cap")
            if cap:
                out["token"] = str(cap)
            ok, resp = _signup_ok(info)
            if ok:
                out["signup_ok"] = True
                out["resp"] = resp
                log.info("[captcha] signup OK qua trang (http=%s)", resp.get("http"))
                break
            if info.get("verified") and out["token"] and not submit:
                break
            if info.get("verified") and submit and email:
                how = await _submit_form(tab)
                log.info("[captcha] submit form (%s) token_len=%s", how, len(out["token"]))
                await _sleep(2.0)
                info = _parse_probe(await _js(tab, PROBE_JS))
                last_info = info
                ok, resp = _signup_ok(info)
                if ok:
                    out["signup_ok"] = True
                    out["resp"] = resp
                    break
                if out["token"]:
                    break

            if i == 0:
                log.info(
                    "[captcha] probe hooked=%s init=%s inst=%s imgs=%s net=%s text=%s",
                    info.get("hooked"),
                    info.get("hasInit"),
                    info.get("hasInst"),
                    (info.get("imgs") or [])[:6],
                    (info.get("net") or [])[:6],
                    (info.get("text") or "")[:80],
                )
                await _ensure_visible(tab, info)
                img = next((b for b in (info.get("boxes") or []) if b.get("id") == "aliyunCaptcha-img"), None)
                if img and float(img.get("y") or 0) >= 0:
                    await _screenshot(tab, DATA / "last_captcha.png", img)

            if not info.get("verified"):
                # widget không render puzzle liên tục = Aliyun throttle — bỏ
                # sớm, kéo tiếp chỉ tốn giờ không có vé nào
                if info.get("boxes"):
                    missing_streak = 0
                elif i >= 3:
                    missing_streak += 1
                    if missing_streak >= 4:
                        raise RuntimeError("widget không render puzzle (throttle?) — thử lại sau")
                if info.get("failedBody"):
                    await _js(
                        tab,
                        "(() => { try { window.__ZAI_INST && window.__ZAI_INST.reset && window.__ZAI_INST.reset(); } catch(e) {}"
                        " const b=document.getElementById('aliyunCaptcha-captcha-body');"
                        " if (b) { try { b.click(); } catch(e) {} } return 1; })()",
                    )
                    await _sleep(0.8)
                    info = _parse_probe(await _js(tab, PROBE_JS))
                    last_info = info
                if i == 0:
                    await _js(tab, REVEAL_JS)
                    await _sleep(0.5)
                    info = _parse_probe(await _js(tab, PROBE_JS))
                    last_info = info
                # MỖI drag là một puzzle MỚI (ảnh mới, lỗ mới) — sau verify-fail
                # widget xoá ảnh, phải click start (REVEAL) để puzzle mới render
                # rồi mới detect lỗ trên CHÍNH puzzle đó; detector hụt mới rơi
                # về vị trí quét (vẫn là vé độc lập).
                tgt: float | None = None
                for _try in range(3):
                    pair = await _frac_from_imgs(tab)
                    if pair:
                        pw = float(pair[2] or 0)
                        tgt = pair[0] * 300.0
                        break
                    await _js(tab, REVEAL_JS)
                    await _sleep(0.6)
                if tgt is None:
                    if not fallback:
                        reach = max(60.0, 285.0 - (pw or 30.0))
                        lo, hi = 28.0, min(reach, 260.0)
                        fallback = [round(lo + i * (hi - lo) / 11) for i in range(12)]
                    tgt = float(fallback.pop(0)) if fallback else 150.0
                try:
                    # kéo vòng đóng tới đúng vị trí mảnh
                    await _drag_once(tab, info, tgt)
                except Exception as e:
                    log.warning("[captcha] drag: %s", e)
            await _sleep(1.3)

        if not out["token"] and last_info.get("cap"):
            out["token"] = str(last_info["cap"])
        if not out["signup_ok"]:
            ok, resp = _signup_ok(last_info)
            if ok:
                out["signup_ok"] = True
                out["resp"] = resp

        if out["token"] and email and password and not out["signup_ok"]:
            try:
                sig = await _inpage_signup(
                    tab,
                    email=email,
                    password=password,
                    username=username or email.split("@")[0],
                    cap=out["token"],
                )
                last_info["signup"] = sig
                ok, resp = _signup_ok({"signup": sig, "url": str(sig.get("url") or "")})
                out["resp"] = resp or sig
                if ok:
                    out["signup_ok"] = True
                    log.info("[captcha] in-page signup http=%s", (resp or sig).get("http") or sig.get("status"))
                else:
                    log.warning("[captcha] in-page signup fail %s", str(sig)[:180])
            except Exception as e:
                log.warning("[captcha] in-page signup: %s", e)

        if not out["token"] and not out["signup_ok"]:
            try:
                html = await _js(
                    tab,
                    "((document.getElementById('captcha-element')||document.body).innerHTML||'').slice(0,12000)",
                )
                (DATA / "last_captcha.html").write_text(str(html or ""), encoding="utf-8")
                (DATA / "last_captcha_net.json").write_text(
                    json.dumps(last_info.get("net") or [], ensure_ascii=False, default=str)[:8000],
                    encoding="utf-8",
                )
                await _screenshot(tab, DATA / "last_captcha.png")
            except Exception:
                pass
            out["detail"] = "không lấy được captcha_verify_param (slider/Aliyun)"
            raise RuntimeError(out["detail"])

        log.info(
            "[captcha] mint OK len=%s signup_ok=%s",
            len(out["token"]),
            out["signup_ok"],
        )
        return out
    finally:
        await _close(browser)


def solve_and_signup(
    config: dict[str, Any],
    *,
    email: str,
    password: str,
    username: str = "",
    submit: bool = False,
) -> dict[str, Any]:
    """Chrome: slide Aliyun, lấy token. submit=True thì bấm Create Account trên trang."""
    log.info("[captcha] mint Aliyun%s…", " + submit form" if submit else "")
    if not submit:
        out = _solve_via_service(config, email=email, password=password, username=username)
        if out is not None:
            return out
        log.info("[captcha] solver không lên — tự giải in-process (Chrome ẩn)")
    with _solve_lock:
        return asyncio.run(
            _solve_async(
                config,
                email=email,
                password=password,
                username=username,
                submit=submit,
            )
        )


def mint_aliyun_token(config: dict[str, Any]) -> str:
    """Blocking helper — chỉ lấy captcha_verify_param."""
    log.info("[captcha] mint Aliyun (solver)…")
    out = _solve_via_service(config, email="", password="", username="")
    if out is not None and out.get("token"):
        return str(out["token"])
    log.info("[captcha] solver không lên — tự giải in-process (Chrome ẩn)")
    with _solve_lock:
        out = asyncio.run(_solve_async(config, submit=False))
    tok = str(out.get("token") or "")
    if not tok:
        raise RuntimeError(out.get("detail") or "mint captcha fail")
    return tok
