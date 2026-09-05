# Nguồn Claude

## Official

| | |
|---|---|
| App signup / login | https://claude.ai/login |
| Console (API) | https://console.anthropic.com |
| Claude Code | https://github.com/anthropics/claude-code |
| Quickstarts | https://github.com/anthropics/claude-quickstarts |

## GitHub / community

Không thấy repo public làm **reg acc claude.ai** ổn định (signup không có HTTP API).

| | |
|---|---|
| [anthropics/claude-code](https://github.com/anthropics/claude-code) | CLI, không phải signup consumer |
| [anthropics/claude-quickstarts](https://github.com/anthropics/claude-quickstarts) | Cần API key sẵn |
| Sub2API `platform=anthropic` | OAuth / setup-token *sau khi đã có acc* — không tạo acc |

Pattern tool nội bộ: `D:\grok_tool\notion` (pydoll email+OTP) và `D:\grok_tool\canva` (Hotmail + Chrome ẩn).

## Protocol

Probe (thường fail → browser):

- `GET https://claude.ai/login`
- `POST https://claude.ai/api/auth/send_magic_link`
- `POST https://claude.ai/api/auth/email`
- `POST https://claude.ai/api/email_login`

Kết quả ghi `data/last_session.json` / `data/last_protocol.json`.
