# Grok Register Tool

Modular Grok / xAI registration helper:

- **Browser UI** (pydoll Chrome) or **protocol HTTP** (competitor-style, ~30s)
- Temp mail / Hotmail OTP
- SSO capture → **Sub2API** import (`grok free NNN`)
- Optional Google Sheet export
- Web control plane (`http://127.0.0.1:8787`)

> **Do not commit secrets.** Copy `config.example.json` → `config.json` locally.  
> See [SAFE_GITHUB.md](SAFE_GITHUB.md).

## Layout

```
grokreg/           core package
  core/            config, helpers, stop_control
  mail/            OTP + temp mail
  browser/         Chrome / CF
  reg/             browser register_one
  protocol/        HTTP protocol backend
  delivery/        Sub2API + sheets
  captcha/         Turnstile solver client
  tools/           batch / overnight
web_console/       FastAPI UI
services/          local Turnstile solver
config.example.json
```

## Setup

```bash
python -m venv venv
# Windows
venv\Scripts\pip install -r requirements.txt
copy config.example.json config.json
# edit config.json (Sub2API URL/user/pass, passwords — never commit)
```

## Run

```bash
# Browser (hidden / off-screen)
venv\Scripts\python.exe main.py 0 --count 1 --backend browser

# Protocol HTTP (needs Turnstile solver on :5072)
venv\Scripts\python.exe main.py 0 --count 1 --backend protocol

# Web UI
venv\Scripts\python.exe -m web_console.daemon
# → http://127.0.0.1:8787
```

Optional solver:

```bat
CHAY_SOLVER.bat
```

## Docs

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [SAFE_GITHUB.md](SAFE_GITHUB.md)

## License

Use at your own risk. Respect xAI / Grok terms of service.
