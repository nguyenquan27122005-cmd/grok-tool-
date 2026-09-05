# Notion Reg

Tool riêng cạnh `grok_tool` / `Heygen` / `capcut`.

Folder: `D:\grok_tool\notion`  
Signup: `https://www.notion.so/signup` — email magic link / login code.

## Offer 1 / 3 / 6 tháng

Theo [Notion for Startups](https://www.notion.com/help/notion-for-startups):

| Thời hạn | Điều kiện |
|---|---|
| **6 tháng** Business + AI | Partner code + company email + website + &lt;100 NV + acc mới chưa trả phí |
| **3 tháng** | Không partner, vẫn là startup (company domain, website) |
| **1 tháng** | SMB / &lt;10 NV / form chưa verify đủ |

Tool **reg acc rồi đọc gói** (`getSubscriptionData`). Nếu `claim_offer` bật, mở `startups-apply`. Sheet tab `notion` **chỉ khi có offer** (Plus/Business/trial 1/3/6). Điền `startup.partner_code` nếu có mã partner thật — không bịa company/website.

## CLI

```bat
CHAY_REG.bat 3 --count 1 --backend browser
CHAY_REG.bat 3 --until-success --backend browser
CHAY_REG.bat 3 --until-offer --partner MA_PARTNER
```

- **Chỉ tmail** (`tmail.wibucrypto.pro`) — Hotmail / Azpop / Guerrilla không dùng
- `--backend auto` = HTTP `sendTemporaryPassword` rồi Chrome nếu fail
- Web: `http://127.0.0.1:8787/#/register` tile **Notion**

Nguồn: [SOURCES.md](SOURCES.md)
