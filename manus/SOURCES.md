# Nguồn tham khảo (Manus)

Không có repo public làm **reg acc Manus** (send-code HTTP). Có tài liệu login cookie + credits API sau khi đã vào session.

## Official

| | |
|---|---|
| Login / signup (cùng trang) | https://manus.im/login |
| App | https://manus.im/app |
| Invite | `https://manus.im/invitation/<id>` |
| API product (cần API key, **không** phải signup) | https://open.manus.im/docs · https://open.manus.ai/docs |
| Docs | https://manus.im/docs/integrations/manus-api |

UI login (2026): **Sign in or sign up** — Facebook / Google / Microsoft / Apple / passkey / Continue (email, SPA).

## GitHub

| Repo | Dùng gì |
|---|---|
| [steipete/CodexBar](https://github.com/steipete/CodexBar) `docs/manus.md` + `ManusUsageFetcher.swift` | Cookie `session_id` (domain `manus.im`). `POST https://api.manus.im/user.v1.UserService/GetAvailableCredits` body `{}`, `Authorization: Bearer <session_id>`, header `Connect-Protocol-Version: 1`. Trả `totalCredits`, `freeCredits`, `periodicCredits`, `proMonthlyCredits`, `refreshCredits`, … |
| [jackwener/OpenCLI#1836](https://github.com/jackwener/OpenCLI/issues/1836) | Next.js (`files.manuscdn.com/webapp/_next/...`), cookie-mode login, `/api/*` cần session, public `/share` `/report` `/invitation`. |
| [whit3rabbit/manus-open](https://github.com/whit3rabbit/manus-open) | Sandbox API `api.manus.im` — **không** phải user signup. |

`manreg/credits.py` copy shape CodexBar (check session sau login). Signup path vẫn là Chrome trên `/login`.
