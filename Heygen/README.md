# HeyGen Reg

Tool **riêng** (không trộn vào `grok_tool`) — cùng kiểu: mail OTP + Chrome / HTTP + web Start/Stop.

Folder: `D:\grok_tool\Heygen`  
Grok vẫn chạy `http://127.0.0.1:8787` — HeyGen dùng **`http://127.0.0.1:8788`**.

## Chạy

Dùng venv sẵn của `grok_tool` (không cần venv mới):

```bat
CHAY_WEB.bat
```

Hoặc CLI:

```bat
CHAY_REG.bat 0 --count 1 --backend browser
```

- `0` = temp mail (azpop / tmail)  
- `1` = Hotmail (đọc `../grok_tool/data/hotmails.txt`)  
- `--backend browser` = Chrome (nên dùng)  
- `--backend protocol` = thử API HTTP (dễ 404 nếu HeyGen đổi endpoint)

## Khác Grok chỗ nào

Giữ: mail, solver `:5072` (nếu CF), web log, STOP, ledger `data/accounts.txt`.  
Viết mới: URL `auth.heygen.com/signup`, form, OTP/link HeyGen, onboarding, cookie session.

`protocol` chỉ **thử** vài URL API công khai. Signup HeyGen hay đổi — path chắc là **Chrome**.

## Lưu ý

HeyGen ToS cấm farm acc. Dùng cho acc của bạn / test. IP bẩn / temp mail dễ bị chặn.
