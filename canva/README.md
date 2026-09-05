# Canva Reg

Tool cạnh `grok_tool` / `capcut` / `Heygen` / `zai`.

Folder: `D:\grok_tool\canva`

Flow chính thức Canva 2026: **Continue with email → tên acc → mã 6 số** (`Your Canva code`).
Canva **chặn temp/disposable mail** — ưu tiên Hotmail.

## CLI

```bat
CHAY_REG.bat 1 --count 1 --backend auto
CHAY_REG.bat 3 --count 1 --backend browser
CHAY_REG.bat 1 --count 1 --backend browser
CHAY_REG.bat 2 --count 1 --backend protocol
```

## Redeem trial / promo

`data/codes.txt` — mỗi dòng 1 mã. Acc: `email|password` hoặc cookie, hoặc dòng Hotmail `email|pass|refresh|client_id`.

```bat
CHAY_REDEEM.bat
python canva_tool.py redeem --accounts data/accounts.txt --codes data/codes.txt --proxy data/proxy.txt --threads 3 --output data/proof.json --success-only
```

Chrome ẩn (pydoll). Có cookie thì thử HTTP trước. Kết quả: console `[+] SUKSES` / `[-] FAIL`, file `data/proof.json` + `data/redeem_success.txt`.

`1` = Hotmail (`../grok_tool/data/hotmails.txt`) · `3` = tmail.wibucrypto.pro · `2` = Azpop · `0` = SMART (azpop ↔ tmail) · `4` = Guerrilla

`--backend auto` = thử HTTP rồi fallback Chrome (mặc định).  
`--backend protocol` = `/_ajax/csrf3/signup` + `POST /_ajax/signup` (dễ 400 vì reCAPTCHA Enterprise).  
`--backend browser` = Chrome ẩn (pydoll, port `9544`).

Dùng venv sẵn của `grok_tool`. Web: tile **Canva** trên `http://127.0.0.1:8787`.

Ledger: `data/accounts.txt`  
`email|password|status|time|plan`

## Khác Grok chỗ nào

Giữ: mail, STOP, ledger, Google Sheet tab `canva`, Chrome off-screen.  
Viết mới: URL `canva.com/signup`, CSRF `_ajax/csrf3`, OTP “Your Canva code”, onboarding skip.

## Lưu ý

Canva ToS cấm farm acc. Temp mail thường `error:email_flagged`. HTTP thuần hay cần captcha — path chắc là **Chrome**.
