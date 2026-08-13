# data/ (local only — not pushed to GitHub)

This folder holds **runtime secrets and personal results**. It is gitignored.

Examples (never commit):

- `accounts.txt` — registered emails / passwords / status  
- `hotmails.txt` — mail pool (1 dòng = tối đa `hotmail_max_aliases` Grok)  
- `hotmail_aliases.json` — ledger plus-alias đã dùng (`user+1@` …)  

- `delivery_queue.json` — SSO retry queue  
- `*.log`, network captures, counters  

Copy `../config.example.json` → `../config.json` and fill in your own values on each machine.
