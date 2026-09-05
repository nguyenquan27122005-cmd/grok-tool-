#!/usr/bin/env python3
"""Add Grok accounts to Sub2API via full manual OAuth UI flow (pydoll)."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from pydoll.browser.chromium import Chrome
from pydoll.browser.options import ChromiumOptions

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.json"

# UI labels: EN / ZH / VI
LABELS = {
    "create_account": [
        "Create Account",
        "创建账号",
        "创建账户",
        "Tạo tài khoản",
        "新建账号",
    ],
    "next": ["Next", "下一步", "Kế tiếp", "继续"],
    "manual_auth": [
        "Manual Authorization",
        "手动授权",
        "Ủy quyền thủ công",
    ],
    "generate_url": [
        "Generate Auth URL",
        "生成授权 URL",
        "生成授权链接",
        "Tạo URL xác thực",
    ],
    "complete_auth": [
        "Complete Authorization",
        "完成授权",
        "Ủy quyền hoàn chỉnh",
        "验证并创建",
    ],
    "test_connection": [
        "Test Connection",
        "Test Account",
        "测试连接",
        "测试账号",
        "Kiểm tra kết nối",
        "检查连接",
    ],
    "start_test": [
        "Start Test",
        "开始测试",
        "Bắt đầu kiểm tra",
        "Retry",
        "重试",
    ],
    "allow": ["Allow", "允许", "Authorize", "授权", "Continue", "继续", "Approve"],
    "login": ["Log in", "Sign in", "Login", "登录", "Đăng nhập", "Continue", "Next", "下一步"],
    "close": ["Close", "关闭", "Đóng", "Cancel", "取消"],
}


# ---------------------------------------------------------------------------
# logging / config / accounts
# ---------------------------------------------------------------------------


def setup_logger(log_file: str | Path) -> logging.Logger:
    logger = logging.getLogger("sub2api_oauth")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    path = Path(log_file)
    if not path.is_absolute():
        path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


log = logging.getLogger("sub2api_oauth")


@dataclass
class Account:
    email: str
    password: str
    status: str
    line_index: int = -1
    raw: str = ""


@dataclass
class ImportResult:
    email: str
    name: str
    ok: bool
    stage: str
    message: str


def load_config(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def resolve_path(p: str | Path, base: Path = ROOT) -> Path:
    path = Path(p)
    if not path.is_absolute():
        path = (base / path).resolve()
    return path


def parse_account_line(line: str, idx: int = -1) -> Optional[Account]:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    parts = line.split("|")
    if len(parts) < 3:
        return None
    email, password, status = parts[0].strip(), parts[1].strip(), parts[2].strip()
    if not email or not password:
        return None
    return Account(email=email, password=password, status=status, line_index=idx, raw=line)


def load_success_accounts(path: Path) -> list[Account]:
    if not path.exists():
        raise FileNotFoundError(f"accounts file not found: {path}")
    out: list[Account] = []
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        acc = parse_account_line(line, i)
        if not acc:
            continue
        st = acc.status.strip().lower()
        if st == "success":
            out.append(acc)
    return out


def update_account_status(path: Path, email: str, password: str, new_status: str) -> None:
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    out: list[str] = []
    done = False
    for line in lines:
        acc = parse_account_line(line)
        if acc and not done and acc.email.lower() == email.lower() and acc.password == password:
            out.append(f"{acc.email}|{acc.password}|{new_status}")
            done = True
        else:
            out.append(line)
    if done:
        path.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")


def format_name(prefix: str, number: int) -> str:
    return f"{prefix.strip()} {number:03d}"


# ---------------------------------------------------------------------------
# JS helpers (pydoll)
# ---------------------------------------------------------------------------


def _unwrap_js(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    try:
        inner = result
        for _ in range(8):
            if not isinstance(inner, dict):
                break
            if "type" in inner and ("value" in inner or inner.get("type") == "undefined"):
                val = inner.get("value")
                if isinstance(val, str):
                    s = val.strip()
                    if (s.startswith("{") and s.endswith("}")) or (
                        s.startswith("[") and s.endswith("]")
                    ):
                        try:
                            return json.loads(s)
                        except Exception:
                            pass
                return val
            if "result" in inner:
                inner = inner["result"]
                continue
            if "value" in inner and len(inner) <= 3:
                return inner["value"]
            break
        return result
    except Exception:
        return result


async def js(tab: Any, script: str) -> Any:
    script_stripped = script.strip()
    candidates = [script_stripped]
    if script_stripped.startswith("(()") or script_stripped.startswith("(function"):
        candidates.append(
            f"(() => {{ const __r = ({script_stripped}); "
            f"try {{ return JSON.stringify(__r); }} catch (e) {{ return String(__r); }} }})()"
        )
    for method_name in ("execute_script", "evaluate"):
        if not hasattr(tab, method_name):
            continue
        fn = getattr(tab, method_name)
        for sc in candidates:
            try:
                try:
                    raw = await fn(sc, return_by_value=True)
                except TypeError:
                    raw = await fn(sc)
                val = _unwrap_js(raw)
                if isinstance(val, dict) and set(val.keys()) <= {
                    "id",
                    "result",
                    "type",
                    "className",
                    "description",
                    "objectId",
                }:
                    continue
                return val
            except Exception:
                continue
    return None


async def sleep(sec: float) -> None:
    await asyncio.sleep(sec)


async def current_url(tab: Any) -> str:
    try:
        if hasattr(tab, "current_url"):
            u = tab.current_url
            if asyncio.iscoroutine(u):
                u = await u
            if u:
                return str(u)
    except Exception:
        pass
    val = await js(tab, "location.href")
    return str(val or "")


async def wait_until(
    predicate,
    timeout: float,
    interval: float = 0.5,
    desc: str = "condition",
) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if await predicate():
                return True
        except Exception:
            pass
        await sleep(interval)
    log.warning("timeout waiting for: %s (%.0fs)", desc, timeout)
    return False


# ---------------------------------------------------------------------------
# DOM actions
# ---------------------------------------------------------------------------


async def click_text(tab: Any, labels: list[str], *, role: str = "") -> bool:
    labels_json = json.dumps(labels)
    role_json = json.dumps(role)
    script = f"""
    (() => {{
      const labels = {labels_json}.map(s => s.toLowerCase());
      const roleWant = {role_json};
      const nodes = [...document.querySelectorAll(
        'button, a, [role=button], label, input[type=submit], input[type=button], div[role=button], span'
      )];
      const score = (el) => {{
        const t = ((el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || '') + '')
          .replace(/\\s+/g, ' ').trim().toLowerCase();
        if (!t) return -1;
        for (const lab of labels) {{
          if (t === lab) return 100;
          if (t.includes(lab)) return 50 + Math.min(lab.length, 20);
        }}
        return -1;
      }};
      let best = null, bestScore = -1;
      for (const el of nodes) {{
        if (el.disabled || el.getAttribute('aria-disabled') === 'true') continue;
        const r = (el.getAttribute('role') || el.tagName || '').toLowerCase();
        if (roleWant && !r.includes(roleWant) && el.tagName.toLowerCase() !== roleWant) continue;
        const s = score(el);
        if (s > bestScore) {{ bestScore = s; best = el; }}
      }}
      if (!best || bestScore < 0) return false;
      best.scrollIntoView({{block:'center'}});
      best.click();
      return true;
    }})()
    """
    return bool(await js(tab, script))


async def set_input_value(tab: Any, selector: str, value: str) -> bool:
    script = f"""
    (() => {{
      const el = document.querySelector({json.dumps(selector)});
      if (!el) return false;
      el.focus();
      const proto = el.tagName === 'TEXTAREA'
        ? window.HTMLTextAreaElement.prototype
        : window.HTMLInputElement.prototype;
      const desc = Object.getOwnPropertyDescriptor(proto, 'value');
      if (desc && desc.set) desc.set.call(el, {json.dumps(value)});
      else el.value = {json.dumps(value)};
      el.dispatchEvent(new Event('input', {{bubbles:true}}));
      el.dispatchEvent(new Event('change', {{bubbles:true}}));
      el.dispatchEvent(new KeyboardEvent('keyup', {{bubbles:true}}));
      return true;
    }})()
    """
    return bool(await js(tab, script))


async def click_selector(tab: Any, selector: str) -> bool:
    script = f"""
    (() => {{
      const el = document.querySelector({json.dumps(selector)});
      if (!el) return false;
      el.scrollIntoView({{block:'center'}});
      el.click();
      return true;
    }})()
    """
    return bool(await js(tab, script))


async def fill_by_label_or_selector(
    tab: Any,
    selectors: list[str],
    value: str,
    label_hints: list[str] | None = None,
) -> bool:
    for sel in selectors:
        if await set_input_value(tab, sel, value):
            return True
    if label_hints:
        hints = json.dumps([h.lower() for h in label_hints])
        script = f"""
        (() => {{
          const hints = {hints};
          const inputs = [...document.querySelectorAll('input, textarea')];
          for (const el of inputs) {{
            const id = el.id || '';
            let lab = '';
            if (id) {{
              const l = document.querySelector('label[for=\"' + id + '\"]');
              if (l) lab = (l.innerText || '').toLowerCase();
            }}
            const ph = (el.placeholder || '').toLowerCase();
            const name = (el.name || '').toLowerCase();
            const aria = (el.getAttribute('aria-label') || '').toLowerCase();
            const blob = lab + ' ' + ph + ' ' + name + ' ' + aria;
            if (!hints.some(h => blob.includes(h))) continue;
            el.focus();
            const proto = el.tagName === 'TEXTAREA'
              ? window.HTMLTextAreaElement.prototype
              : window.HTMLInputElement.prototype;
            const desc = Object.getOwnPropertyDescriptor(proto, 'value');
            if (desc && desc.set) desc.set.call(el, {json.dumps(value)});
            else el.value = {json.dumps(value)};
            el.dispatchEvent(new Event('input', {{bubbles:true}}));
            el.dispatchEvent(new Event('change', {{bubbles:true}}));
            return true;
          }}
          return false;
        }})()
        """
        if await js(tab, script):
            return True
    return False


async def select_platform_grok(tab: Any) -> bool:
    # Prefer data-tour platform buttons containing text Grok
    script = """
    (() => {
      const root = document.querySelector('[data-tour="account-form-platform"]') || document;
      const btns = [...root.querySelectorAll('button')];
      const grok = btns.find(b => /\\bgrok\\b/i.test((b.innerText || b.textContent || '').trim()));
      if (!grok) return false;
      grok.click();
      return true;
    })()
    """
    return bool(await js(tab, script))


async def select_type_oauth(tab: Any) -> bool:
    script = """
    (() => {
      // radio oauth
      const radios = [...document.querySelectorAll('input[type=radio]')];
      for (const r of radios) {
        if ((r.value || '').toLowerCase() === 'oauth') {
          r.click();
          return 'radio';
        }
      }
      // button cards with OAuth text
      const nodes = [...document.querySelectorAll('button, label, div')];
      for (const el of nodes) {
        const t = ((el.innerText || '') + '').replace(/\\s+/g, ' ').trim();
        if (/^OAuth$/i.test(t) || /\\bOAuth\\b/i.test(t) && t.length < 40) {
          el.click();
          return 'btn';
        }
      }
      return false;
    })()
    """
    return bool(await js(tab, script))


async def select_group(tab: Any, group_name: str) -> bool:
    name = group_name.strip()
    script = f"""
    (() => {{
      const want = {json.dumps(name)}.toLowerCase();
      const root = document.querySelector('[data-tour="account-form-groups"]') || document;
      // search box if present
      const search = root.querySelector('input[type=text], input:not([type])');
      if (search) {{
        search.focus();
        const desc = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
        if (desc && desc.set) desc.set.call(search, {json.dumps(name)});
        else search.value = {json.dumps(name)};
        search.dispatchEvent(new Event('input', {{bubbles:true}}));
        search.dispatchEvent(new Event('change', {{bubbles:true}}));
      }}
      const labels = [...root.querySelectorAll('label')];
      for (const lab of labels) {{
        const t = ((lab.innerText || lab.textContent || '') + '').replace(/\\s+/g, ' ').trim().toLowerCase();
        if (!t.includes(want)) continue;
        const cb = lab.querySelector('input[type=checkbox]');
        if (cb) {{
          if (!cb.checked) {{
            cb.click();
          }}
          return true;
        }}
        lab.click();
        return true;
      }}
      // fallback whole document
      for (const lab of document.querySelectorAll('label')) {{
        const t = ((lab.innerText || '') + '').toLowerCase();
        if (!t.includes(want)) continue;
        const cb = lab.querySelector('input[type=checkbox]');
        if (cb) {{
          if (!cb.checked) cb.click();
          return true;
        }}
      }}
      return false;
    }})()
    """
    # allow search filter to update DOM
    ok = bool(await js(tab, script))
    if not ok:
        await sleep(0.6)
        ok = bool(await js(tab, script))
    return ok


async def read_auth_url_from_ui(tab: Any) -> str:
    script = """
    (() => {
      const inputs = [...document.querySelectorAll('input[readonly], input.font-mono, input')];
      for (const el of inputs) {
        const v = (el.value || '').trim();
        if (/^https?:\\/\\//i.test(v) && (/oauth|x\\.ai|accounts/i.test(v))) return v;
      }
      const links = [...document.querySelectorAll('a[href]')];
      for (const a of links) {
        const h = a.href || '';
        if (/oauth|x\\.ai/i.test(h) && h.startsWith('http')) return h;
      }
      // any mono text that looks like url
      const nodes = [...document.querySelectorAll('input, textarea, code, pre')];
      for (const el of nodes) {
        const v = (el.value || el.innerText || '').trim();
        if (/^https?:\\/\\//i.test(v) && v.length > 30) return v.split(/\\s/)[0];
      }
      return '';
    })()
    """
    val = await js(tab, script)
    return str(val or "").strip()


async def extract_code_from_url(url: str) -> tuple[str, str]:
    """Return (code, full_callback_or_code)."""
    if not url:
        return "", ""
    url = url.strip()
    # bare code
    if "://" not in url and "code=" not in url and len(url) > 10:
        return url, url
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        code = (qs.get("code") or [""])[0]
        if code:
            return code, url
        # hash fragment
        if parsed.fragment:
            fqs = parse_qs(parsed.fragment.lstrip("?"))
            code = (fqs.get("code") or [""])[0]
            if code:
                return code, url
    except Exception:
        pass
    m = re.search(r"[?&#]code=([^&\\s]+)", url)
    if m:
        return m.group(1), url
    return "", url


def is_callback_url(url: str) -> bool:
    if not url:
        return False
    u = url.lower()
    return (
        "code=" in u
        and (
            "127.0.0.1" in u
            or "localhost" in u
            or "/callback" in u
            or "auth/callback" in u
        )
    ) or bool(re.search(r"[?&]code=[A-Za-z0-9._\\-]+", url))


# ---------------------------------------------------------------------------
# Browser bootstrap
# ---------------------------------------------------------------------------


def build_chrome_options(cfg: dict[str, Any]) -> ChromiumOptions:
    options = ChromiumOptions()
    if cfg.get("headless"):
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1400,960")
    options.add_argument("--disable-blink-features=AutomationControlled")
    proxy = (cfg.get("proxy") or "").strip()
    if proxy:
        options.add_argument(f"--proxy-server={proxy}")
    profile = (cfg.get("chrome_user_data_dir") or "").strip()
    if profile:
        p = resolve_path(profile)
        p.mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--user-data-dir={str(p)}")
    port = cfg.get("chrome_debug_port")
    if port:
        options.add_argument(f"--remote-debugging-port={int(port)}")
    return options


async def start_browser(cfg: dict[str, Any]) -> tuple[Any, Any]:
    options = build_chrome_options(cfg)
    port = int(cfg.get("chrome_debug_port") or 9340)
    browser = Chrome(options=options, connection_port=port)
    tab = await browser.start()
    if tab is None:
        if hasattr(browser, "get_tab"):
            tab = await browser.get_tab()
        elif hasattr(browser, "new_tab"):
            tab = await browser.new_tab()
    if tab is None:
        raise RuntimeError("failed to start browser tab")
    return browser, tab


async def new_tab(browser: Any, url: str = "") -> Any:
    if hasattr(browser, "new_tab"):
        try:
            t = await browser.new_tab(url) if url else await browser.new_tab()
            if t:
                return t
        except TypeError:
            t = await browser.new_tab()
            if url:
                await t.go_to(url)
            return t
    raise RuntimeError("browser.new_tab not available")


# ---------------------------------------------------------------------------
# Sub2API login + create flow
# ---------------------------------------------------------------------------


async def ensure_sub2api_login(tab: Any, cfg: dict[str, Any]) -> None:
    base = cfg["sub2api_url"].rstrip("/")
    user = (cfg.get("sub2api_user") or "").strip()
    password = (cfg.get("sub2api_pass") or "").strip()

    log.info("[sub2api] open %s/admin/accounts", base)
    await tab.go_to(f"{base}/admin/accounts")
    await sleep(2)

    url = await current_url(tab)
    has_login_form = bool(
        await js(
            tab,
            "!!document.querySelector('input[type=password], input[name=password]')",
        )
    )
    already_admin = "/admin" in url and "/login" not in url and not has_login_form
    if already_admin:
        log.info("[sub2api] already authenticated")
        return

    if not user or not password:
        raise RuntimeError("need sub2api_user/sub2api_pass (not logged in)")

    log.info("[sub2api] login as %s", user)
    await tab.go_to(f"{base}/login")
    await sleep(1.5)
    filled_email = await fill_by_label_or_selector(
        tab,
        [
            'input[type="email"]',
            'input[name="email"]',
            'input[autocomplete="username"]',
            'input[name="username"]',
            'input[type="text"]',
        ],
        user,
        ["email", "邮箱", "user", "账号"],
    )
    filled_pw = await fill_by_label_or_selector(
        tab,
        [
            'input[type="password"]',
            'input[name="password"]',
            'input[autocomplete="current-password"]',
        ],
        password,
        ["password", "密码", "mật khẩu"],
    )
    if not filled_email or not filled_pw:
        raise RuntimeError("sub2api login form not found / not filled")
    clicked = await click_text(tab, LABELS["login"])
    if not clicked:
        await click_selector(tab, 'button[type="submit"]')
    await sleep(2.5)
    await tab.go_to(f"{base}/admin/accounts")
    await sleep(2)

    url = await current_url(tab)
    if "/login" in url:
        raise RuntimeError("sub2api login failed — check sub2api_user/sub2api_pass")
    log.info("[sub2api] on accounts page: %s", url)


async def open_create_account_modal(tab: Any) -> None:
    log.info("[sub2api] open Create Account modal")
    ok = await click_text(tab, LABELS["create_account"])
    if not ok:
        # try header buttons with plus
        ok = bool(
            await js(
                tab,
                """
                (() => {
                  const btns = [...document.querySelectorAll('button')];
                  const b = btns.find(x => /create|新建|创建|tạo/i.test(x.innerText||''));
                  if (b) { b.click(); return true; }
                  return false;
                })()
                """,
            )
        )
    if not ok:
        raise RuntimeError("cannot click Create Account")
    await sleep(1.2)
    # wait name input
    ok = await wait_until(
        lambda: js(tab, "!!document.querySelector('[data-tour=\"account-form-name\"], input.input')"),
        10,
        desc="create account form",
    )
    if not ok:
        raise RuntimeError("create account form not visible")


async def fill_step1(
    tab: Any,
    account_name: str,
    group_name: str,
) -> None:
    log.info("[sub2api] step1 name=%s group=%s platform=Grok type=OAuth", account_name, group_name)

    filled = await fill_by_label_or_selector(
        tab,
        ['[data-tour="account-form-name"]', 'input[data-tour="account-form-name"]'],
        account_name,
        ["account name", "名称", "tên tài khoản", "name"],
    )
    if not filled:
        # first text input in modal
        filled = await set_input_value(tab, "form#create-account-form input.input", account_name)
    if not filled:
        raise RuntimeError("cannot fill account name")

    if not await select_platform_grok(tab):
        raise RuntimeError("cannot select platform Grok")
    await sleep(0.4)

    # OAuth default for Grok; still try select
    await select_type_oauth(tab)
    await sleep(0.3)

    if not await select_group(tab, group_name):
        raise RuntimeError(f'cannot select group "{group_name}"')
    await sleep(0.3)

    # Next
    log.info("[sub2api] click Next")
    clicked = await click_selector(tab, '[data-tour="account-form-submit"]')
    if not clicked:
        clicked = await click_text(tab, LABELS["next"])
    if not clicked:
        raise RuntimeError("cannot click Next")
    await sleep(1.5)


async def choose_manual_auth(tab: Any) -> None:
    log.info("[sub2api] choose Manual Authorization")
    # radio value=manual
    ok = bool(
        await js(
            tab,
            """
            (() => {
              const radios = [...document.querySelectorAll('input[type=radio]')];
              for (const r of radios) {
                if ((r.value||'').toLowerCase() === 'manual') {
                  r.click();
                  return true;
                }
              }
              return false;
            })()
            """,
        )
    )
    if not ok:
        ok = await click_text(tab, LABELS["manual_auth"])
    if not ok:
        log.warning("manual auth radio not found — assume already selected")
    await sleep(0.6)


async def generate_auth_url(tab: Any, timeout: float = 30) -> str:
    log.info("[sub2api] Generate Auth URL")
    # if already has url, read it
    existing = await read_auth_url_from_ui(tab)
    if existing:
        log.info("[sub2api] auth url already present")
        return existing

    clicked = await click_text(tab, LABELS["generate_url"])
    if not clicked:
        raise RuntimeError("cannot click Generate Auth URL")

    async def _has_url() -> bool:
        u = await read_auth_url_from_ui(tab)
        return bool(u)

    ok = await wait_until(_has_url, timeout, desc="auth url generated")
    if not ok:
        raise RuntimeError("auth url not generated")
    url = await read_auth_url_from_ui(tab)
    log.info("[sub2api] auth_url=%s", url[:120] + ("..." if len(url) > 120 else ""))
    return url


async def paste_code_and_complete(tab: Any, callback_or_code: str) -> None:
    log.info("[sub2api] paste auth code/url and Complete Authorization")
    filled = await fill_by_label_or_selector(
        tab,
        [
            "textarea.input",
            "textarea.font-mono",
            "textarea",
        ],
        callback_or_code,
        [
            "authorization",
            "auth code",
            "code",
            "callback",
            "授权",
            "验证",
            "url hoặc mã",
            "mã xác thực",
        ],
    )
    if not filled:
        # last textarea in dialog
        ok = bool(
            await js(
                tab,
                f"""
                (() => {{
                  const areas = [...document.querySelectorAll('textarea')];
                  if (!areas.length) return false;
                  const el = areas[areas.length - 1];
                  el.focus();
                  const desc = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value');
                  if (desc && desc.set) desc.set.call(el, {json.dumps(callback_or_code)});
                  else el.value = {json.dumps(callback_or_code)};
                  el.dispatchEvent(new Event('input', {{bubbles:true}}));
                  el.dispatchEvent(new Event('change', {{bubbles:true}}));
                  return true;
                }})()
                """,
            )
        )
        if not ok:
            raise RuntimeError("cannot fill auth code textarea")

    await sleep(0.4)
    clicked = await click_text(tab, LABELS["complete_auth"])
    if not clicked:
        # primary button in footer
        clicked = bool(
            await js(
                tab,
                """
                (() => {
                  const btns = [...document.querySelectorAll('button.btn-primary, button')];
                  const re = /complete|authorization|完成授权|ủy quyền|验证/i;
                  const b = btns.find(x => re.test((x.innerText||'').trim()) && !x.disabled);
                  if (b) { b.click(); return true; }
                  return false;
                })()
                """,
            )
        )
    if not clicked:
        raise RuntimeError("cannot click Complete Authorization")

    # wait modal close or success toast
    async def _done() -> bool:
        # form gone
        has_form = await js(
            tab,
            "!!document.querySelector('[data-tour=\"account-form-name\"]')",
        )
        if not has_form:
            return True
        # error visible
        err = await js(
            tab,
            """
            (() => {
              const el = document.querySelector('.text-red-600, .text-red-400, [class*=\"error\"]');
              if (!el) return '';
              return (el.innerText || '').trim().slice(0, 200);
            })()
            """,
        )
        if err and len(str(err)) > 5:
            raise RuntimeError(f"complete auth error: {err}")
        return False

    ok = await wait_until(_done, 60, desc="account created / modal closed")
    if not ok:
        # check still loading
        raise RuntimeError("timeout after Complete Authorization")
    log.info("[sub2api] account create flow finished")


# ---------------------------------------------------------------------------
# Grok OAuth in browser
# ---------------------------------------------------------------------------


async def grok_oauth_login_and_allow(
    browser: Any,
    auth_url: str,
    email: str,
    password: str,
    timeout: float,
) -> str:
    """
    Open OAuth URL, login, Allow, return callback URL or code.
    """
    log.info("[oauth] open auth url for %s", email)
    tab = await new_tab(browser, auth_url)
    await sleep(2)

    deadline = time.time() + timeout
    last_url = ""
    password_filled = False
    email_filled = False
    allow_clicked = False

    while time.time() < deadline:
        url = await current_url(tab)
        if url != last_url:
            log.info("[oauth] url=%s", url[:160])
            last_url = url

        if is_callback_url(url):
            code, full = await extract_code_from_url(url)
            if code or full:
                log.info("[oauth] got callback code")
                try:
                    # close oauth tab if possible
                    if hasattr(tab, "close"):
                        await tab.close()
                except Exception:
                    pass
                return full if full else code

        # fill email
        if not email_filled:
            email_filled = await fill_by_label_or_selector(
                tab,
                [
                    'input[type="email"]',
                    'input[name="email"]',
                    'input[autocomplete="username"]',
                    'input[autocomplete="email"]',
                    'input[type="text"]',
                ],
                email,
                ["email", "邮箱"],
            )
            if email_filled:
                log.info("[oauth] email filled")
                await sleep(0.4)
                await click_text(tab, LABELS["login"]) or await click_selector(
                    tab, 'button[type="submit"]'
                )
                await sleep(1.2)

        # fill password
        if not password_filled:
            password_filled = await fill_by_label_or_selector(
                tab,
                [
                    'input[type="password"]',
                    'input[name="password"]',
                    'input[autocomplete="current-password"]',
                ],
                password,
                ["password", "密码"],
            )
            if password_filled:
                log.info("[oauth] password filled")
                await sleep(0.3)
                await click_text(tab, LABELS["login"]) or await click_selector(
                    tab, 'button[type="submit"]'
                )
                await sleep(1.5)

        # consent Allow
        if not allow_clicked:
            # common consent page
            page_text = str(
                await js(tab, "document.body ? (document.body.innerText||'').slice(0,2000) : ''")
                or ""
            )
            if re.search(r"allow|authorize|同意|允许|permission|access", page_text, re.I):
                if await click_text(tab, LABELS["allow"]):
                    allow_clicked = True
                    log.info("[oauth] clicked Allow")
                    await sleep(1.5)

        # page may show code text
        body = str(await js(tab, "document.body ? (document.body.innerText||'') : ''") or "")
        m = re.search(
            r"(?:authorization\s*code|auth\s*code|code)\s*[:：]?\s*([A-Za-z0-9._\-]{12,})",
            body,
            re.I,
        )
        if m:
            code = m.group(1)
            log.info("[oauth] code found on page")
            try:
                if hasattr(tab, "close"):
                    await tab.close()
            except Exception:
                pass
            return code

        # connection refused on callback still has URL in address bar — already handled
        await sleep(0.8)

    raise RuntimeError(f"oauth timeout for {email} (no code/callback within {timeout}s)")


# ---------------------------------------------------------------------------
# Test connection
# ---------------------------------------------------------------------------


async def test_account_connection(
    tab: Any,
    account_name: str,
    model_name: str,
    timeout: float,
) -> tuple[bool, str]:
    log.info("[test] open Test Connection for %s model=%s", account_name, model_name)
    base_url = await current_url(tab)
    # ensure accounts list
    if "/admin/accounts" not in base_url:
        # navigate if needed handled by caller
        pass

    # search account if search box exists
    await fill_by_label_or_selector(
        tab,
        [
            'input[type="search"]',
            'input[placeholder*="Search"]',
            'input[placeholder*="搜索"]',
            'input[placeholder*="Tìm"]',
        ],
        account_name,
        ["search", "搜索", "tìm"],
    )
    await sleep(1.0)

    # find row with account name, click test menu
    script = f"""
    (() => {{
      const want = {json.dumps(account_name)}.toLowerCase();
      const rows = [...document.querySelectorAll('tr, [class*=\"card\"], div')];
      let row = null;
      for (const r of rows) {{
        const t = ((r.innerText || '') + '').replace(/\\s+/g, ' ').trim();
        if (t.toLowerCase().includes(want) && t.length < 500) {{
          row = r;
          break;
        }}
      }}
      if (!row) return 'row_not_found';
      // open actions menu
      const more = row.querySelector('button[aria-haspopup], button[aria-label*=\"menu\" i], button');
      const buttons = [...row.querySelectorAll('button, a')];
      // direct test button
      for (const b of buttons) {{
        const tx = (b.innerText || b.getAttribute('title') || b.getAttribute('aria-label') || '');
        if (/test|测试|kiểm tra|连接/i.test(tx)) {{
          b.click();
          return 'clicked_test';
        }}
      }}
      // click last action button (kebab)
      if (buttons.length) {{
        buttons[buttons.length - 1].click();
        return 'opened_menu';
      }}
      return 'no_action';
    }})()
    """
    res = await js(tab, script)
    log.info("[test] row action: %s", res)
    await sleep(0.8)

    if res == "opened_menu":
        await click_text(tab, LABELS["test_connection"])
        await sleep(1.0)
    elif res == "row_not_found":
        # try global text click
        if not await click_text(tab, [account_name]):
            return False, f"account row not found: {account_name}"
        await sleep(0.5)
        await click_text(tab, LABELS["test_connection"])

    await sleep(1.0)

    # select model — custom Select component
    model_selected = bool(
        await js(
            tab,
            f"""
            (() => {{
              const want = {json.dumps(model_name)}.toLowerCase();
              // native select
              const sels = [...document.querySelectorAll('select')];
              for (const s of sels) {{
                for (const opt of s.options) {{
                  const t = (opt.text || opt.value || '').toLowerCase();
                  if (t.includes(want) || want.includes(t)) {{
                    s.value = opt.value;
                    s.dispatchEvent(new Event('change', {{bubbles:true}}));
                    s.dispatchEvent(new Event('input', {{bubbles:true}}));
                    return 'native:' + opt.text;
                  }}
                }}
              }}
              // click custom dropdown trigger then option
              const triggers = [...document.querySelectorAll('button, [role=combobox], [class*=\"select\"]')];
              for (const tr of triggers) {{
                const t = (tr.innerText || '').toLowerCase();
                if (t.includes('model') || t.includes('模型') || t.includes('select') || t.includes('选择')) {{
                  tr.click();
                }}
              }}
              return 'open_custom';
            }})()
            """,
        )
    )
    await sleep(0.6)
    # click option matching model
    clicked_model = bool(
        await js(
            tab,
            f"""
            (() => {{
              const want = {json.dumps(model_name)}.toLowerCase();
              const opts = [...document.querySelectorAll(
                '[role=option], li, div, button, span'
              )];
              let best = null, bestScore = -1;
              for (const el of opts) {{
                const t = ((el.innerText || '') + '').replace(/\\s+/g, ' ').trim();
                if (!t || t.length > 80) continue;
                const low = t.toLowerCase();
                let score = -1;
                if (low === want) score = 100;
                else if (low.includes(want)) score = 80;
                else if (want.includes(low)) score = 60;
                else if (low.includes('grok') && low.includes('4.5')) score = 50;
                else if (low.includes('grok-4') || low.includes('grok 4')) score = 40;
                if (score > bestScore) {{ bestScore = score; best = el; }}
              }}
              if (best && bestScore >= 40) {{ best.click(); return best.innerText.trim(); }}
              return '';
            }})()
            """,
        )
    )
    log.info("[test] model select result=%s clicked=%s", model_selected, clicked_model)
    await sleep(0.5)

    # Start Test
    if not await click_text(tab, LABELS["start_test"]):
        await click_selector(tab, "button.bg-primary-500, button.btn-primary")
    log.info("[test] started")

    # wait success / error in terminal
    async def _result() -> Optional[tuple[bool, str]]:
        data = await js(
            tab,
            """
            (() => {
              const body = document.body ? document.body.innerText : '';
              const hasSuccess = /test completed successfully|测试完成|thành công|success/i.test(body)
                && !/failed|error|失败/i.test(body.slice(-400));
              // look terminal green/red
              const green = document.querySelector('.text-green-400, .text-green-500');
              const red = document.querySelector('.text-red-400, .text-red-500');
              const term = document.querySelector('.bg-gray-900, .font-mono');
              const termText = term ? (term.innerText || '') : '';
              if (/test completed successfully|测试完成/i.test(termText) ||
                  (/success/i.test(termText) && !/error/i.test(termText))) {
                return JSON.stringify({ok:true, msg: termText.slice(-300)});
              }
              if (red && (red.innerText || '').trim()) {
                return JSON.stringify({ok:false, msg: (red.innerText||'').trim().slice(0,300)});
              }
              if (/error:|failed|失败|HTTP error/i.test(termText)) {
                return JSON.stringify({ok:false, msg: termText.slice(-300)});
              }
              if (green && /completed|success|完成/i.test(green.innerText||'')) {
                return JSON.stringify({ok:true, msg: (green.innerText||'').trim()});
              }
              return '';
            })()
            """,
        )
        if not data:
            return None
        if isinstance(data, str) and data.startswith("{"):
            try:
                obj = json.loads(data)
                return bool(obj.get("ok")), str(obj.get("msg") or "")
            except Exception:
                return None
        if isinstance(data, dict):
            return bool(data.get("ok")), str(data.get("msg") or "")
        return None

    deadline = time.time() + timeout
    while time.time() < deadline:
        r = await _result()
        if r is not None:
            ok, msg = r
            # close modal
            await click_text(tab, LABELS["close"])
            return ok, msg or ("test ok" if ok else "test failed")
        await sleep(1.0)

    await click_text(tab, LABELS["close"])
    return False, f"test timeout after {timeout}s"


async def scan_next_number(tab: Any, prefix: str, start: int) -> int:
    """Scan accounts page text for existing 'prefix NNN' and return next number."""
    text = str(await js(tab, "document.body ? document.body.innerText : ''") or "")
    pat = re.compile(re.escape(prefix.strip()) + r"\s*(\d{1,5})", re.I)
    nums = [int(m.group(1)) for m in pat.finditer(text)]
    if not nums:
        return max(1, start)
    return max(max(nums) + 1, start)


# ---------------------------------------------------------------------------
# per-account pipeline
# ---------------------------------------------------------------------------


async def process_account(
    browser: Any,
    tab: Any,
    cfg: dict[str, Any],
    acc: Account,
    account_name: str,
) -> ImportResult:
    stage = "start"
    try:
        stage = "open_modal"
        await open_create_account_modal(tab)

        stage = "step1"
        await fill_step1(tab, account_name, cfg.get("group") or "grok free 1x")

        stage = "manual_auth"
        await choose_manual_auth(tab)

        stage = "generate_url"
        auth_url = await generate_auth_url(tab, timeout=float(cfg.get("timeout_login_sec") or 90))

        stage = "oauth"
        callback = await grok_oauth_login_and_allow(
            browser,
            auth_url,
            acc.email,
            acc.password,
            timeout=float(cfg.get("timeout_oauth_sec") or 180),
        )
        log.info("[oauth] callback/code received for %s", acc.email)

        # ensure focus back on sub2api tab
        stage = "complete"
        try:
            # navigate/focus: re-check modal still open
            has_modal = await js(
                tab,
                "!!document.querySelector('textarea, [data-tour=\"account-form-name\"]')",
            )
            if not has_modal:
                # try bring tab by going to same page is bad; re-open is worse
                log.warning("create modal may be lost — reloading accounts and aborting this acc")
                raise RuntimeError("create account modal lost after oauth")
        except RuntimeError:
            raise
        except Exception as e:
            log.warning("Bước OAuth bị lỗi (đã bỏ qua để chạy tiếp): %s", e)

        await paste_code_and_complete(tab, callback)

        stage = "test"
        ok, msg = await test_account_connection(
            tab,
            account_name,
            cfg.get("model_test") or "Grok 4.5",
            timeout=float(cfg.get("timeout_test_sec") or 120),
        )
        if not ok:
            return ImportResult(acc.email, account_name, False, stage, f"created but test failed: {msg}")
        return ImportResult(acc.email, account_name, True, stage, msg or "ok")

    except Exception as e:
        log.exception("process failed %s stage=%s", acc.email, stage)
        # try close modal
        try:
            await click_text(tab, LABELS["close"] + ["Cancel", "取消", "Hủy"])
            await sleep(0.3)
            # escape
            await js(
                tab,
                "document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))",
            )
        except Exception:
            pass
        return ImportResult(acc.email, account_name, False, stage, str(e))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def async_main(args: argparse.Namespace) -> int:
    global log
    cfg_path = Path(args.config).resolve()
    if not cfg_path.exists():
        print(f"config not found: {cfg_path}", file=sys.stderr)
        return 2
    cfg = load_config(cfg_path)
    log = setup_logger(cfg.get("log_file") or "import_log.txt")

    accounts: list[Account] = []
    accounts_path: Path | None = None
    if args.acc:
        for i, line in enumerate(args.acc):
            a = parse_account_line(line, i)
            if a and a.status.lower() == "success":
                accounts.append(a)
            elif a:
                log.warning("skip non-success --acc: %s", line)
            else:
                log.warning("invalid --acc: %s", line)
    else:
        file_path = args.accounts_file or cfg.get("accounts_file") or "accounts.txt"
        accounts_path = resolve_path(file_path, cfg_path.parent)
        accounts = load_success_accounts(accounts_path)
        log.info("loaded %d success accounts from %s", len(accounts), accounts_path)

    if not accounts:
        log.warning("no success accounts to import")
        return 0

    if args.dry_run:
        prefix = cfg.get("name_prefix") or "grok free"
        start = int(args.start or cfg.get("start_number") or 1)
        for i, acc in enumerate(accounts):
            log.info("[dry-run] %s → %s", acc.email, format_name(prefix, start + i))
        return 0

    browser, tab = await start_browser(cfg)
    ok_n = fail_n = 0
    results: list[ImportResult] = []
    try:
        await ensure_sub2api_login(tab, cfg)

        prefix = (cfg.get("name_prefix") or "grok free").strip()
        start = int(args.start if args.start is not None else (cfg.get("start_number") or 1))
        # scan page for next free number
        next_num = await scan_next_number(tab, prefix, start)
        if next_num != start:
            log.info("auto number: start_number=%s page_next=%s → use %s", start, next_num, next_num)
        num = next_num
        delay = float(cfg.get("delay_between_sec") or 2)

        for idx, acc in enumerate(accounts, 1):
            name = format_name(prefix, num)
            log.info("==== (%d/%d) %s → %s ====", idx, len(accounts), acc.email, name)
            # refresh accounts page each round
            base = cfg["sub2api_url"].rstrip("/")
            await tab.go_to(f"{base}/admin/accounts")
            await sleep(1.5)

            res = await process_account(browser, tab, cfg, acc, name)
            results.append(res)
            if res.ok:
                ok_n += 1
                log.info("OK  %s | %s | %s", res.email, res.name, res.message)
                if accounts_path and cfg.get("update_accounts_status", True):
                    tag = cfg.get("success_status_tag") or "added_sub2api"
                    update_account_status(accounts_path, acc.email, acc.password, f"{tag}:{res.name}")
            else:
                fail_n += 1
                log.error(
                    "FAIL %s | %s | stage=%s | %s",
                    res.email,
                    res.name,
                    res.stage,
                    res.message,
                )
                if accounts_path and cfg.get("update_accounts_status", True):
                    tag = cfg.get("fail_status_tag") or "add_sub2api_fail"
                    short = re.sub(r"\s+", " ", res.message)[:100]
                    update_account_status(
                        accounts_path,
                        acc.email,
                        acc.password,
                        f"{tag}:{res.stage}:{short}",
                    )
            num += 1
            if delay > 0 and idx < len(accounts):
                await sleep(delay)

    finally:
        try:
            if hasattr(browser, "stop"):
                await browser.stop()
        except Exception:
            pass

    log.info("==== DONE ok=%d fail=%d total=%d ====", ok_n, fail_n, len(results))
    for r in results:
        mark = "OK" if r.ok else "FAIL"
        log.info("  [%s] %s | %s | %s | %s", mark, r.email, r.name, r.stage, r.message)
    return 0 if fail_n == 0 else 1


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Add Grok accounts to Sub2API via OAuth UI (pydoll)")
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("--file", dest="accounts_file", default=None)
    p.add_argument("--acc", action="append", default=[], help="email|password|success")
    p.add_argument("--start", type=int, default=None, help="start number for name_prefix")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
