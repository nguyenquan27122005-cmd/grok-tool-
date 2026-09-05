# Claude / Anthropic Reg

Tool cạnh `grok_tool` / `canva` / `notion` / `zai`.

Folder: `D:\grok_tool\claude`

Signup chính thức **claude.ai**: email → mã 6 số (hoặc magic link) → tên. Anthropic **hay chặn temp mail** và đôi khi đòi **SĐT** (`error:need_phone`). Ưu tiên Hotmail.

Không có API signup công khai (xem `SOURCES.md`). HTTP probe ghi `data/last_protocol.json` rồi fallback Chrome.

## CLI

```bat
CHAY_REG.bat 1 --count 1 --backend browser
CHAY_REG.bat 1 --count 1 --backend auto
```

`1` = Hotmail (pool chung `grok_tool\data\hotmails.txt`) · `3` = tmail · `2` = Azpop · `4` = Guerrilla · `0` = SMART

`--backend browser` = Chrome ẩn (pydoll, port `9844`).  
`--backend gpm` = mở profile GPM-Login (`D:\gpm`, API `:19995`, mặc định profile `gpt`). Phải mở **GPMLogin.exe** trước.  
`--backend auto` = thử HTTP rồi Chrome.  
`--backend protocol` = chỉ HTTP (thường `error:need_browser`).

GPM không bảo đảm tránh SĐT. Hai profile hiện tại **không gắn proxy** — IP máy/VN vẫn hay bị hỏi phone.

Dùng venv sẵn của `grok_tool`. Web: tile **Claude / Anthropic** trên `http://127.0.0.1:8787/#/register`.

Ledger: `data/accounts.txt`  
`email|password|status|time|note`

## Status

| Status | Ý nghĩa |
|---|---|
| `success` | Vào claude.ai (chat/new) hoặc có `sessionKey` |
| `error:email_blocked` | Mail bị chặn (temp/disposable) |
| `error:need_phone` | Anthropic đòi xác minh SĐT |
| `error:no_otp` | Không thấy mã trong inbox |
| `error:need_browser` / `need_captcha` | HTTP không làm được |

## Khác Grok chỗ nào

Giữ: mail, STOP, ledger, Google Sheet tab `claude`, Chrome off-screen.  
Viết mới: URL `claude.ai/login`, OTP Anthropic, phone wall, session dump.

## Lưu ý

Anthropic ToS cấm farm acc. Temp mail / SĐT giả thường fail. Tool chỉ tự hóa form công khai, không bypass phone.
