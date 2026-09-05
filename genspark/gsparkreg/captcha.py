"""Solve Azure AD B2C image CAPTCHA (base64) via 2captcha / YesCaptcha.

Genspark signup is B2C SelfAsserted with a text CAPTCHA image — same path as
https://github.com/flupyxyz/genspark-farm (2captcha in.php method=base64).
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

import requests

from gsparkreg.config import captcha_keys
from gsparkreg.log import log
from gsparkreg.paths import DATA

TWOCAPTCHA_IN = "https://2captcha.com/in.php"
TWOCAPTCHA_RES = "https://2captcha.com/res.php"
YES_CREATE = "https://api.yescaptcha.com/createTask"
YES_RESULT = "https://api.yescaptcha.com/getTaskResult"


def _strip_data_url(src: str) -> str:
    raw = (src or "").strip()
    if "," in raw and raw.lower().startswith("data:"):
        return raw.split(",", 1)[1].strip()
    return raw


def save_captcha_image(b64: str) -> Path | None:
    blob = _strip_data_url(b64)
    if not blob:
        return None
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        path = DATA / "last_captcha.png"
        path.write_bytes(base64.b64decode(blob))
        return path
    except Exception as e:
        log.debug("save captcha: %s", e)
        return None


def solve_2captcha(b64: str, api_key: str, *, timeout: int = 60) -> str:
    body = _strip_data_url(b64)
    r = requests.post(
        TWOCAPTCHA_IN,
        data={"key": api_key, "method": "base64", "body": body, "json": 1},
        timeout=30,
    )
    j = r.json() if r.text else {}
    if j.get("status") != 1:
        raise RuntimeError(f"2captcha in.php: {j}")
    task_id = j.get("request")
    deadline = time.time() + max(20, int(timeout))
    time.sleep(3)
    while time.time() < deadline:
        r2 = requests.get(
            TWOCAPTCHA_RES,
            params={"key": api_key, "action": "get", "id": task_id, "json": 1},
            timeout=15,
        )
        j2 = r2.json() if r2.text else {}
        if j2.get("status") == 1:
            ans = str(j2.get("request") or "").strip()
            if ans:
                return ans
        if str(j2.get("request") or "").upper() in ("ERROR_CAPTCHA_UNSOLVABLE", "ERROR_WRONG_CAPTCHA_ID"):
            raise RuntimeError(f"2captcha: {j2}")
        time.sleep(2)
    raise TimeoutError("2captcha timeout")


def solve_yescaptcha(b64: str, api_key: str, *, timeout: int = 60) -> str:
    body = _strip_data_url(b64)
    r = requests.post(
        YES_CREATE,
        json={"clientKey": api_key, "task": {"type": "ImageToTextTask", "body": body}},
        timeout=30,
    )
    j = r.json() if r.text else {}
    task_id = j.get("taskId")
    if not task_id:
        raise RuntimeError(f"yescaptcha create: {j}")
    deadline = time.time() + max(20, int(timeout))
    time.sleep(2)
    while time.time() < deadline:
        r2 = requests.post(
            YES_RESULT,
            json={"clientKey": api_key, "taskId": task_id},
            timeout=15,
        )
        j2 = r2.json() if r2.text else {}
        if j2.get("status") == "ready":
            sol = j2.get("solution") or {}
            ans = str(sol.get("text") or sol.get("gRecaptchaResponse") or "").strip()
            if ans:
                return ans
        if j2.get("errorId") not in (0, None) and j2.get("status") == "failed":
            raise RuntimeError(f"yescaptcha: {j2}")
        time.sleep(2)
    raise TimeoutError("yescaptcha timeout")


_OCR = None


def _ocr():
    global _OCR
    if _OCR is None:
        import ddddocr  # type: ignore

        _OCR = ddddocr.DdddOcr(show_ad=False)
    return _OCR


def _alnum(s: str) -> str:
    return "".join(c for c in (s or "") if c.isalnum())


def _ocr_png(im) -> str:
    import io

    buf = io.BytesIO()
    im.convert("RGB").save(buf, format="PNG")
    return _alnum(str(_ocr().classification(buf.getvalue()) or ""))


def solve_ddddocr_all(b64: str) -> list[str]:
    """Azure B2C captcha = 2 hàng × ~4 ký tự. OCR từng hàng rồi ghép.

    Trả list đáp ứng theo thứ tự ưu tiên — caller thử lần lượt trên CÙNG ảnh
    (B2C cho đoán lại nhiều lần trước khi bắt refresh), tăng gấp mấy lần cơ
    hội trúng so với chỉ submit 1 pick.
    """
    from PIL import Image, ImageOps, ImageFilter

    blob = base64.b64decode(_strip_data_url(b64))
    import io

    img = Image.open(io.BytesIO(blob)).convert("RGB")
    w, h = img.size
    # phóng to cho ddddocr
    big = img.resize((w * 3, h * 3), Image.Resampling.LANCZOS)
    bw, bh = big.size
    top = big.crop((0, 0, bw, bh // 2 + 8))
    bot = big.crop((0, bh // 2 - 8, bw, bh))

    def prep(im):
        g = ImageOps.grayscale(im)
        g = ImageOps.autocontrast(g)
        return g.filter(ImageFilter.SHARPEN).convert("RGB")

    def binarize(im, th=140):
        g = ImageOps.autocontrast(ImageOps.grayscale(im))
        return g.point(lambda p: 255 if p > th else 0).convert("RGB")

    cands: list[str] = []
    a_top = _ocr_png(prep(top))
    a_bot = _ocr_png(prep(bot))
    if a_top or a_bot:
        cands.append(a_top + a_bot)
    cands.append(_ocr_png(prep(big)))
    cands.append(_ocr_png(big))
    # invert rows (chữ xanh trên nền sáng)
    cands.append(_ocr_png(ImageOps.invert(ImageOps.grayscale(top)).convert("RGB"))
                 + _ocr_png(ImageOps.invert(ImageOps.grayscale(bot)).convert("RGB")))
    # binarize cả ảnh — thêm 1 biến thể cho chữ mảnh/đậm bất thường
    cands.append(_ocr_png(binarize(big)))

    scored = [c for c in cands if 4 <= len(c) <= 12] or [c for c in cands if c]
    if not scored:
        raise RuntimeError("ddddocr empty after split")
    # ưu tiên đúng 8 ký tự (B2C chuẩn), bỏ trùng giữ thứ tự
    scored.sort(key=lambda s: (abs(len(s) - 8), -len(s)))
    out: list[str] = []
    for c in scored:
        if c not in out:
            out.append(c)
    log.info("CAPTCHA ddddocr candidates=%s", out[:4])
    return out


def solve_ddddocr(b64: str) -> str:
    ans = solve_ddddocr_all(b64)[0]
    log.info("CAPTCHA ddddocr pick=%s", ans)
    return ans


def solve_image_candidates(b64: str, config: dict[str, Any] | None = None) -> list[str]:
    """List đáp án CAPTCHA theo thứ tự thử. Local ddddocr trả nhiều biến thể
    tiền xử lý; dịch vụ remote (2captcha/YesCaptcha) trả 1 đáp án."""
    if not b64:
        raise RuntimeError("empty captcha image")
    save_captcha_image(b64)
    keys = captcha_keys(config or {})
    errors: list[str] = []
    prefer = str((config or {}).get("captcha", {}).get("prefer") or "local").strip().lower()
    order = ["local", "2captcha", "yescaptcha"]
    if prefer in ("2captcha", "yescaptcha"):
        order = [prefer] + [x for x in order if x != prefer]
    for name in order:
        try:
            if name == "local":
                return solve_ddddocr_all(b64)
            if name == "2captcha" and keys.get("2captcha_key"):
                ans = solve_2captcha(b64, keys["2captcha_key"])
                log.info("CAPTCHA 2captcha=%s", ans)
                return [ans]
            if name == "yescaptcha" and keys.get("yescaptcha_key"):
                ans = solve_yescaptcha(b64, keys["yescaptcha_key"])
                log.info("CAPTCHA yescaptcha=%s", ans)
                return [ans]
        except Exception as e:
            errors.append(f"{name}:{e}")
            log.warning("%s fail: %s", name, e)
    raise RuntimeError("CAPTCHA solvers fail: " + "; ".join(errors)[:240])


def solve_image(b64: str, config: dict[str, Any] | None = None) -> str:
    """Return CAPTCHA text (best candidate). Local ddddocr first, then 2captcha / YesCaptcha."""
    return solve_image_candidates(b64, config)[0]
