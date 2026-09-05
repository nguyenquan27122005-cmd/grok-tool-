"""Solve HeyGen Turnstile via grok_tool local solver :5072 and inject into the SPA."""

from __future__ import annotations

from typing import Any

from heyreg.log import log

SITEKEY = "0x4AAAAAAB59VlMqoRanWuKq"
SIGNUP_URL = "https://auth.heygen.com/signup"

HOOK_JS = r"""
(() => {
  const TOKEN = %TOKEN%;
  window.__heygenTs = TOKEN;
  const patchBody = (body) => {
    if (typeof body !== 'string' || !body) return body;
    try {
      const j = JSON.parse(body);
      if (j && typeof j === 'object') {
        j.turnstile_token = window.__heygenTs;
        return JSON.stringify(j);
      }
    } catch (e) {}
    return body;
  };
  if (!window.__heygenFetchHooked) {
    window.__heygenFetchHooked = true;
    const orig = window.fetch.bind(window);
    window.fetch = function (input, init) {
      init = init || {};
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      if (/pacific|api2\.heygen/.test(url) && init.body) {
        init = Object.assign({}, init, { body: patchBody(init.body) });
      }
      return orig(input, init);
    };
    const XO = XMLHttpRequest.prototype.open;
    const XS = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (m, u) {
      this.__u = String(u || '');
      return XO.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function (body) {
      if (/pacific|api2\.heygen/.test(this.__u || '')) body = patchBody(body);
      return XS.call(this, body);
    };
  }
  let n = 0;
  const setVal = (el) => {
    if (!el) return;
    try {
      const proto = el.tagName === 'TEXTAREA'
        ? window.HTMLTextAreaElement.prototype
        : window.HTMLInputElement.prototype;
      const desc = Object.getOwnPropertyDescriptor(proto, 'value');
      if (desc && desc.set) desc.set.call(el, TOKEN);
      else el.value = TOKEN;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      n++;
    } catch (e) {}
  };
  document.querySelectorAll(
    'input[name="cf-turnstile-response"], textarea[name="cf-turnstile-response"]'
  ).forEach(setVal);
  if (!document.querySelector('input[name="cf-turnstile-response"]')) {
    const inp = document.createElement('input');
    inp.type = 'hidden';
    inp.name = 'cf-turnstile-response';
    inp.value = TOKEN;
    document.body.appendChild(inp);
    n++;
  }
  try {
    window.dispatchEvent(new CustomEvent('cf-turnstile-response', { detail: TOKEN }));
  } catch (e) {}
  return n;
})()
"""


def kick_solver(config: dict[str, Any]) -> None:
    try:
        from heyreg.paths import ensure_grok_on_path

        ensure_grok_on_path()
        from services.solver_manager import start_async

        start_async(config)
        log.info("Turnstile solver: auto-start :5072")
    except Exception as e:
        log.debug("solver start: %s", e)


def solve_token(config: dict[str, Any]) -> str:
    from heyreg.paths import ensure_grok_on_path

    ensure_grok_on_path()
    from grokreg.captcha.turnstile_solver_client import ExternalTurnstileSolver

    ts = dict(config.get("turnstile") or {})
    ts.setdefault("solver_url", "http://127.0.0.1:5072")
    ts.setdefault("sitekey", SITEKEY)
    solver = ExternalTurnstileSolver.from_config({"turnstile": ts, **config})
    if not solver.available():
        kick_solver(config)
        import time

        for _ in range(25):
            time.sleep(1)
            if solver.available():
                break
    if not solver.available():
        raise RuntimeError("Turnstile solver offline — bat CHAY_SOLVER.bat (:5072)")
    log.info("Turnstile solve sitekey=%s url=%s", SITEKEY[:20], SIGNUP_URL)
    token = solver.solve(url=SIGNUP_URL, site_key=SITEKEY)
    if not token or len(token) < 20:
        raise RuntimeError("Turnstile empty token")
    log.info("Turnstile token len=%s", len(token))
    return token


async def inject_token(tab: Any, token: str, exec_js) -> bool:
    script = HOOK_JS.replace("%TOKEN%", json_dumps(token))
    n = await exec_js(tab, script)
    log.info("Turnstile hook+inject fields=%s", n)
    return bool(token)


def json_dumps(s: str) -> str:
    import json

    return json.dumps(s)
