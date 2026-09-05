# Manus Reg

Tool riêng cạnh `grok_tool` / `Heygen` / `capcut`.

Folder: `D:\grok_tool\manus`  
Login/signup **cùng trang** `https://manus.im/login` (OAuth Google/Apple/Facebook/Microsoft, passkey, hoặc Continue email). Tool đi **email**.

Nguồn: [SOURCES.md](SOURCES.md). Không có GitHub reg-bot; CodexBar đọc cookie `session_id` rồi gọi credits API.

## CLI

Dùng venv sẵn của `grok_tool`:

```bat
CHAY_REG.bat 2 --count 1 --backend browser
CHAY_REG.bat 1 --count 1 --backend browser
CHAY_REG.bat --invite MA_CODE 2 --count 1
CHAY_REG.bat --backend protocol
```

- `2` = Azpop (mặc định)
- `1` = Hotmail (`../grok_tool/data/hotmails.txt`)
- `4` = Guerrilla
- `--backend browser` = Chrome (nên dùng, port `9644`)
- `--backend protocol` = thử vài URL API công khai; điền `send_code_url` trong config khi capture được endpoint thật
- `--invite` / `MANUS_INVITE` = mã invite nếu form còn hỏi

Dừng: `Ctrl+C` hoặc tạo file `data/STOP`.

## Ledger

`data/accounts.txt`

```
email|password|status|time|extra
```

Sheet tab `manus` khi `status=success`. Extra = credits (`totalCredits` / `freeCredits`) nếu có `session_id`.

Sau login Chrome lấy cookie `session_id` rồi `POST api.manus.im/user.v1.UserService/GetAvailableCredits` (cùng shape [CodexBar](https://github.com/steipete/CodexBar/blob/main/docs/manus.md)).

## Khác Grok chỗ nào

Giữ: mail, STOP, Chrome off-screen, capture HTML → `data/network_capture_*.json`.  
Viết mới: URL `manus.im/login`, form email/OTP, onboarding skip.  
**Không** import Sub2API.

`protocol` dễ 404 nếu Manus đổi API — path chắc là **Chrome**. Sau 1 run browser, xem capture rồi điền `send_code_url`.

## Lưu ý

Manus ToS cấm farm acc. Dùng cho acc của bạn / test. IP bẩn / temp mail dễ bị chặn.
