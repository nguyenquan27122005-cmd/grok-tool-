# CapCut Reg

Tool riêng cạnh `grok_tool` / `Heygen`.

- **API:** `capcut_reg_tool.zip` — ByteDance Passport (`send_code` → OTP → `register/v2`)
- **Mail / STOP / web / Sheet:** cùng kiểu Grok (Azpop / Hotmail, không Guerrilla)

## CLI

```bat
CHAY_REG.bat 2 --count 1 --backend protocol
CHAY_REG.bat --invite MA_CODE 2 --count 1
CHAY_REG.bat --check-session
CHAY_REG.bat --check-session SESSION_KEY
```

`2` = Azpop · `1` = Hotmail (`../grok_tool/data/hotmails.txt`)

Hoặc từ web Grok `http://127.0.0.1:8787` — tile **CapCut**.

Ledger: `data/accounts.txt`  
`email|password|status|time|session_key`

## Proxy

`config.json` → `"proxy": "http://user:pass@host:port"`

## Ưu đãi acc mới (2026)

| Loại | Cách nhận | Auto lúc reg? |
|---|---|---|
| **Pro trial 7 ngày** | Web/App/PC → Upgrade / Join Pro (vùng hỗ trợ, acc chưa từng Pro, app ≥ 8.20) | Thử bind session + đọc trang subscribe |
| **Invite PC +7 ngày** | Mời bạn mới cài CapCut PC; tối đa 10 người = 70 ngày. Bạn được mời cũng 7 ngày, redeem trong 3 ngày | Điền `invite_code` / `share_uid` trong config |
| **Desktop /u/e30** | Cài CapCut PC, login acc — đôi khi 30 ngày Pro | Chỉ mở campaign, cần app PC |
| **Commerce Pro trial** | Gói business riêng (credit), không phải Pro thường | Không |
| **Coupon / landing** | Link subscribe giảm % + 7 ngày | Không (phải mở landing) |
| **VIP redeem** | `/commerce/vip-redeem` + code | Có nếu điền `invite_code` |

`claim_offer: true` (mặc định) — sau register tool login web bằng `sessionid` rồi dò ưu đãi. Trial 7 ngày nhiều vùng vẫn phải bấm **Join Pro** trên web/app.

## Lưu ý

Zip gốc dùng Guerrilla + `app_id=1233`. Endpoint/app_id sai thì `send_code` fail — sửa `app_id` / `api_base` trong config. Arkose captcha chưa có solver.
