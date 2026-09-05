# SciSpace Reg

Đăng ký [scispace.com](https://scispace.com) — signup thuần HTTP, **KHÔNG OTP,
KHÔNG captcha, KHÔNG verify email**. Tài khoản active ngay với 100 credits.

## Chạy

```
CHAY_REG.bat                        # 1 acc temp mail
CHAY_REG.bat 0 --count 10           # 10 acc temp
CHAY_REG.bat 1 --count 5            # 5 acc hotmail pool
```

- **mail 0 = temp (mặc định/khuyên dùng)** — SciSpace không chặn domain temp
  (tmail_wibu / azpop đều nhận).
- Backend duy nhất: `protocol` — `POST /api/auth/signup`
  `{full_name, email, password, invitation_key:null}` → 201.
- AWS WAF trên trang web chỉ là JS challenge; API nhận thẳng request
  curl_cffi (chrome131) không cần giải.
- Không cần solver Turnstile (:5072), không cần Chrome.

Kết quả: `data/accounts.txt` (+ Google Sheet tab `scispace` nếu bật — cần tạo tab
trên Apps Script trước, mặc định đang tắt).

## Lấy link thanh toán từng gói

```
CHAY_REG.bat checkout --plans premium --interval yearly
CHAY_REG.bat checkout --plans premium,advanced,max --interval monthly
```

- Đăng nhập từng acc trong `data/accounts.txt` (dòng success) → tạo Stripe
  Checkout Session → link `pay.scispace.com/c/pay/cs_live_...`
- Gói: `premium`, `advanced`, `max`, `team`, `team_advanced`, `team_max`
  (team tối thiểu 2 users — tool tự đặt quantity=2)
- Link sống ~24h, không thanh toán thì tự huỷ; ghi vào `data/checkout_links.txt`
- Web console: chọn chế độ **"Lấy link thanh toán"** trên tile SciSpace

Chia sẻ venv + pool Hotmail với grok_tool (`../grok_tool`). Tốc độ ~3s/acc;
`--threads 3` → **6 acc trong ~12s** (HTTP thuần, acc độc lập nên song song thoải mái).
Web console có sẵn chọn 1/3/5 luồng.
