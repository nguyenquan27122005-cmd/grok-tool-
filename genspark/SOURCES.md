# Nguồn Genspark

## Official

| | |
|---|---|
| App | https://www.genspark.ai/ |
| Login API (PKCE, 302 → B2C) | https://www.genspark.ai/api/login?redirect_url=/ |
| Auth callback | https://www.genspark.ai/api/auth |
| Session | https://www.genspark.ai/api/is_login · `/api/user` |
| Pricing / claim | https://www.genspark.ai/me?open_pricing=pricing |
| Help — account | https://www.genspark.ai/helpcenter?doc=general_Account_Management |

## Azure AD B2C

| | |
|---|---|
| Custom domain | `login.genspark.ai` |
| Tenant | `gensparkad.onmicrosoft.com` |
| Policy | `b2c_1_new_login` |
| Client ID | `536a4e98-fd24-4cbc-a67b-417e209e0080` |
| Redirect | `https://www.genspark.ai/api/auth` |

B2C signup = SelfAsserted: email + image CAPTCHA + verification code + password + `#continue`.

## GitHub / community

| | |
|---|---|
| [flupyxyz/genspark-farm](https://github.com/flupyxyz/genspark-farm) | Playwright farm: signup + 2captcha + Gmail IMAP + Claim My Free Month. Clone local: `_upstream_farm/` |
| [SharpWizard/genspark-py](https://github.com/SharpWizard/genspark-py) | Login HTTP (curl_cffi) **đã có acc** — không tạo acc. PKCE phải đi qua `/api/login` (đừng tự authorize) |

Pattern tool nội bộ: `D:\grok_tool\claude` (pydoll email+OTP) và `D:\grok_tool\canva` (Hotmail + Chrome ẩn).

## Protocol

Probe (thường fail → browser nếu chưa ra form signup):

- `GET https://www.genspark.ai/`
- `GET https://www.genspark.ai/api/login?redirect_url=/`
- Scrape `SETTINGS` + `x-ms-cpim-csrf` trên trang B2C
- `POST …/SelfAsserted` (VERIFICATION_REQUEST + captcha, rồi password)

Kết quả ghi `data/last_protocol.json` / `data/last_session.json` / `data/last_captcha.png`.
