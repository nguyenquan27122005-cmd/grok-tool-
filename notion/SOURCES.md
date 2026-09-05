# Nguồn Notion

## Official

| | |
|---|---|
| Signup | https://www.notion.so/signup |
| Startups 1/3/6 tháng | https://www.notion.com/help/notion-for-startups |
| Apply | https://www.notion.so/startups-apply |
| Pricing / Education Plus | https://www.notion.com/pricing |

## GitHub / community

| | |
|---|---|
| [kaedea/notion-down](https://github.com/kaedea/notion-down) `notion_token.py` | `POST https://notion.so/api/v3/loginWithEmail` → cookie `token_v2` |
| [cstrnt/notion-api](https://github.com/cstrnt/notion-api) | token_v2 |
| notion-py | `getSpaces` / `getSubscriptionData` |

Protocol tool: `POST /api/v3/sendTemporaryPassword` rồi magic link. Captcha thì `error:need_captcha` — không giải captcha khó.
