# OpenArt Reg

Đăng ký [openart.ai](https://openart.ai) — auth là **Clerk** (`clerk.openart.ai`), flow
**email_code** (HTTP thuần, không Chrome).

## Chạy

```
CHAY_REG.bat                          # 1 acc hotmail
CHAY_REG.bat 1 --count 5              # 5 acc hotmail pool
CHAY_REG.bat 5 --custom-domain nguyenquan.dpdns.org   # domain riêng → forward về Hotmail
```

- **mail 1 = Hotmail (mặc định/khuyên dùng)** — OpenArt chặn domain temp
  (`form_email_address_blocked`) từ 2026-09.
- mail 2/3 (azpop/tmail) chỉ để backup/test — domain temp bị chặn thì fail ngay
  `error:email_flagged`, worker tự đổi mail theo `email_flagged_retry`.
- Backend duy nhất: `protocol` (Clerk API). Captcha = Cloudflare Turnstile invisible
  (sitekey trong `oareg/turnstile.py`), cần solver `:5072` (`CHAY_SOLVER.bat` của grok_tool)
  — **1 token cho 1 account**, chỉ dùng ở bước create sign_up.

## Flow (đã test thật 2026-09-04)

1. Solver Turnstile → token
2. `POST /v1/client/sign_ups` {email_address, password, captcha_token}
3. `POST .../prepare_verification` {strategy: email_code}
4. Đọc OTP từ mail `no-reply@openart.ai` (Graph / azpop / tmail)
5. `POST .../attempt_verification` {code} → `status=complete`

Kết quả: `data/accounts.txt` (+ Google Sheet tab `openart` nếu bật).

**Tốc độ (đo thật 2026-09-04):** acc đầu ~18s (trả captcha ~9s), acc kế chỉ ~9–15s
— token Turnstile cho acc kế được **giải ngầm trong lúc acc hiện tại đợi OTP**
(`prefetch_token`), trễ giữa acc 3–6s. Mail chậm (rare) thì acc = OTP wait + ~5s.

Chia sẻ venv + pool Hotmail với grok_tool (`../grok_tool`). Config chính trong `config.json`.
