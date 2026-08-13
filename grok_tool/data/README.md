# data/ (local only — not pushed to GitHub)

This folder holds **runtime secrets and personal results**. It is gitignored.

Examples (never commit):

- `accounts.txt` — registered emails / passwords / status  
- `hotmails.txt` — mail pool  
- `delivery_queue.json` — SSO retry queue  
- `*.log`, network captures, counters  

Copy `../config.example.json` → `../config.json` and fill in your own values on each machine.
