# Netflix Reg

Tool riêng cạnh `grok_tool` / `capcut` / `Heygen`.

Folder: `D:\grok_tool\netflix`  
Mail / STOP / ledger: cùng kiểu Grok (Hotmail / Azpop / Guerrilla).

Netflix signup (Help Center): **chọn gói → email + password → payment**. Tool **dừng ở cổng thanh toán** — không điền card, không gọi API billing.

Nguồn: [SOURCES.md](SOURCES.md). GitHub **không** có tool reg Netflix public; chỉ login acc sẵn (CastagnaIT Kodi) và household-mail (`info@account.netflix.com`).

## CLI

Dùng venv sẵn của `grok_tool`:

```bat
CHAY_REG.bat 1 --count 1 --backend browser
CHAY_REG.bat 2 --count 1 --backend browser
CHAY_REG.bat --backend protocol
```

- `1` = Hotmail (`../grok_tool/data/hotmails.txt`) — mặc định, Netflix hay chặn temp mail
- `2` = Azpop
- `4` = Guerrilla
- `--backend browser` = Chrome (nên dùng, port `9544`)
- `--backend protocol` = chỉ probe trang public, ghi `data/last_protocol.json`

Dừng: `Ctrl+C` hoặc tạo file `data/STOP`.

## Ledger

`data/accounts.txt`

```
email|password|status|time|extra
```

`need_payment` = đã qua email/password, Netflix đòi payment. **Có ghi Sheet tab `netflix`**.

OTP/link: ~2 phút, hết hạn 15 phút ([help](https://help.netflix.com/en/node/529303577956964)). Browser bấm **Create Password Instead** nếu hiện magic-link.

## Khác Grok chỗ nào

Giữ: mail, STOP, Chrome off-screen, capture HTML.  
Viết mới: URL `netflix.com/signup`, form, OTP Netflix.  
**Không** có Sub2API, **không** có payment.

## Lưu ý

ToS Netflix cấm farm acc / chia sẻ gói. Dùng cho acc của bạn / test. Payment / trial / card nằm ngoài tool này.
