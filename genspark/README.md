# Genspark.ai Reg

Tool cạnh `grok_tool` / `claude` / `canva` / `manus`.

Folder: `D:\grok_tool\genspark`

Signup **genspark.ai** qua Azure AD B2C (`login.genspark.ai` / tenant `gensparkad.onmicrosoft.com`, policy `b2c_1_new_login`):

1. Homepage → Sign up → More options → Sign up now
2. Email + **image CAPTCHA** (2captcha / YesCaptcha)
3. OTP 6 số trong mail
4. Password → Create
5. (Tuỳ chọn) **Claim My Free Month** → lấy Stripe checkout `$0` URL

Nguồn farm: [flupyxyz/genspark-farm](https://github.com/flupyxyz/genspark-farm). Chi tiết: [SOURCES.md](SOURCES.md).

B2C **bắt CAPTCHA ảnh**. Tool OCR local (`ddddocr`) trước; có thể thêm `captcha.2captcha_key` / `yescaptcha_key` nếu OCR sai. Hotmail ưu tiên — temp mail hay bị chặn.

## CLI

Dùng venv sẵn của `grok_tool`:

```bat
CHAY_REG.bat 1 --count 1 --backend browser
CHAY_REG.bat 1 --count 1 --backend auto
CHAY_REG.bat 1 --count 1 --backend browser --no-claim
```

`1` = Hotmail (pool chung `grok_tool\data\hotmails.txt`) · `3` = tmail · `2` = Azpop · `4` = Guerrilla · `0` = SMART · `5` = domain riêng

`--backend browser` = Chrome ẩn (pydoll, port `9944`).
`--backend gpm` = GPM-Login (`D:\gpm`, API `:19995`).
`--backend auto` = thử HTTP B2C rồi Chrome.
`--backend protocol` = chỉ HTTP (thường `error:need_browser` nếu chưa ra form signup+CAPTCHA).

Web: tile **Genspark** trên `http://127.0.0.1:8787/#/register`.

Ledger: `data/accounts.txt`

```
email|password|status|time|note
```

## Status

| Status | Ý nghĩa |
|---|---|
| `success:claimed` | Reg OK + lấy được Stripe `cs_live_…` |
| `success:no_offer` | Reg OK, không thấy nút Claim My Free Month |
| `success` | Reg OK, không chạy claim (`--no-claim`) |
| `error:need_captcha` / `error:captcha_failed` | OCR/solver không đọc được ảnh B2C |
| `error:captcha_failed` | Solver sai / B2C từ chối |
| `error:email_blocked` | Mail bị chặn (temp/disposable) |
| `error:no_otp` | Không thấy mã trong inbox |
| `error:need_browser` | HTTP không làm được — dùng Chrome |

## Cấu hình CAPTCHA

Mặc định OCR local (`ddddocr`, đã cài trong venv grok_tool). Nếu hay sai, thêm key:

```json
"captcha": {
  "2captcha_key": "YOUR_2CAPTCHA_KEY",
  "yescaptcha_key": "",
  "prefer": "local"
}
```

Hoặc env `TWOCAPTCHA_KEY` / `YESCAPTCHA_KEY`.

## Khác Grok chỗ nào

Giữ: mail, STOP, ledger, Google Sheet tab `genspark`, Chrome off-screen, plugin web.
Viết mới: B2C signup, image CAPTCHA, claim free month.
**Không** import Sub2API.

## Lưu ý

Genspark ToS cấm farm acc. Free month auto-renew (~$24.99/mo). Tool tự hóa form công khai + solver CAPTCHA bạn tự trả — không bypass thanh toán.
