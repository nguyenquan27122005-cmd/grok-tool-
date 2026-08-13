# Dùng grok-tool trong VS Code + lấy API key Sub2API

Chạy tool bằng **Terminal trong VS Code**, rồi lấy key từ Sub2API để gọi Grok (OpenAI-compatible). Không dán key / mật khẩu thật vào repo hay chat công khai.

## 1. Mở project

1. Cài [VS Code](https://code.visualstudio.com/).
2. **File → Open Folder** → chọn thư mục `grok_tool` (trong repo clone: `grok-tool-/grok_tool`).
3. Mở terminal: `` Ctrl+` `` (hoặc **Terminal → New Terminal**).  
   Prompt phải đứng trong `grok_tool` (có `main.py`, `config.example.json`).

```powershell
cd D:\path\to\grok-tool-\grok_tool
```

## 2. Cài lần đầu (một lần)

```powershell
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
copy config.example.json config.json
```

Sửa `config.json` **trên máy bạn** (file này gitignore, không commit):

- `fixed_password` — mật khẩu đặt cho acc Grok mới
- `sub2api.sub2api_url` — ví dụ `http://127.0.0.1:8080`
- `sub2api.sub2api_user` / `sub2api_pass` — tài khoản **admin** Sub2API (để tool import SSO)
- `name_prefix` = `grok free`, `group` = `grok free`

Linux / WSL:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
```

Chọn interpreter: `Ctrl+Shift+P` → **Python: Select Interpreter** → `.\venv\Scripts\python.exe`.

## 3. Chạy từ terminal VS Code

Mở **hai** (hoặc ba) tab terminal (`+` trên panel Terminal).

**Tab 1 — Turnstile solver** (bắt buộc nếu `--backend protocol`):

```powershell
.\venv\Scripts\python.exe -m services.turnstile_solver.start
# hoặc: .\CHAY_SOLVER.bat
```

Đợi `http://127.0.0.1:5072`.

**Tab 2 — Sub2API** phải đang chạy sẵn (app của bạn, mặc định `:8080`). Tool chỉ *gọi* Sub2API, không cài hộ.

**Tab 3 — reg**

```powershell
# 1 acc temp mail, HTTP ~30s
.\venv\Scripts\python.exe main.py 0 --count 1 --backend protocol

# Hotmail: 1 dòng trong data/hotmails.txt → tối đa 5 Grok (user / +1 … +4)
.\venv\Scripts\python.exe main.py 1 --count 5 --backend protocol

# Web UI
.\venv\Scripts\python.exe -m web_console.app
```

Web: [http://127.0.0.1:8787/#/register](http://127.0.0.1:8787/#/register)

- Chọn **Hotmail** → dán list hoặc **Browse file** → Start (số lượt = số slot alias, không cần ô số lượng).
- Tick **Auto Sub2API** để import ngay sau khi có SSO.

Thành công: ledger `data/accounts.txt` có `added_sub2api:grok free NNN`.  
`ESC` hoặc nút **Stop** trên web = dừng.

## 4. Lấy API key từ Sub2API

`sub2api_user` / `sub2api_pass` trong `config.json` là **admin import**. Key dùng trong VS Code / Cursor / curl là **token user** trên UI Sub2API — khác nhau.

1. Mở Sub2API: [http://127.0.0.1:8080](http://127.0.0.1:8080) (đổi host nếu bạn chạy chỗ khác).
2. Đăng nhập **user** (hoặc admin tạo user rồi vào trang đó).
3. Vào mục **令牌 / Tokens / API Keys** (tên menu tùy bản).
4. **Tạo token** mới. Gán group có acc vừa import (`grok free`) nếu UI hỏi group.
5. **Copy key một lần** — không commit, không đưa vào README.

Acc `grok free 001`, `002`, … do grok-tool đẩy vào sau mỗi lần reg. Token user chỉ *đi qua* pool đó; không phải SSO cookie.

## 5. Gọi API trong terminal VS Code

Base OpenAI-compatible (bản local phổ biến):

```text
http://127.0.0.1:8080/v1
```

**Không** paste key vào file trong repo. Dùng biến môi trường **User** trên máy bạn:

```powershell
# Windows PowerShell — session hiện tại
$env:SUB2API_KEY = "dán-key-vào-đây"
$env:SUB2API_BASE = "http://127.0.0.1:8080/v1"

# Liệt kê model (tên model xem trên UI Sub2API)
curl.exe "$env:SUB2API_BASE/models" -H "Authorization: Bearer $env:SUB2API_KEY"

# Chat thử — đổi model đúng tên trên Sub2API (vd. Grok 4.5 / grok-4.5)
curl.exe "$env:SUB2API_BASE/chat/completions" `
  -H "Authorization: Bearer $env:SUB2API_KEY" `
  -H "Content-Type: application/json" `
  -d "{\"model\":\"grok-4.5\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}]}"
```

Linux / WSL:

```bash
export SUB2API_KEY='dán-key-vào-đây'
export SUB2API_BASE='http://127.0.0.1:8080/v1'
curl "$SUB2API_BASE/models" -H "Authorization: Bearer $SUB2API_KEY"
```

Grok Build / Codex / công cụ khác: `base_url` = `http://127.0.0.1:8080/v1`, `api_key` hoặc `env_key=SUB2API_KEY`. Đừng set `OPENAI_API_KEY` hệ thống nếu bạn còn dùng OpenAI thật — dễ đè nhầm.

## 6. Reg OK mà chưa vào Sub2API

Ledger `success` hoặc `success_sub2api…` = đã có acc, import lỗi. Kiểm tra Sub2API đang mở, user/pass admin đúng, rồi chạy lại hàng đợi local (máy bạn):

```powershell
.\venv\Scripts\python.exe -m grokreg.tools.continue_sub2api
```

Hoặc bật lại **Auto Sub2API** và không reg trùng email đã thành công.

## 7. Lỗi thường gặp

| Hiện tượng | Việc cần làm |
|---|---|
| `401` / key rejected | Tạo lại token trên UI; đừng dùng password admin làm Bearer |
| `404` `/v1/models` | Thử `/api/v1/models` hoặc xem docs bản Sub2API bạn đang chạy |
| Có key nhưng không chat được | Acc chưa `added_sub2api`; group token ≠ `grok free` |
| Protocol timeout | Tab solver `:5072` chưa lên |
| VS Code không thấy `python` | Select Interpreter → `venv` |

Key, `config.json`, `data/accounts.txt`, `hotmails.txt` **không** được `git add`.
