# Grok Register Tool

Package nằm trong repo [grok-tool-](https://github.com/nguyenquan27122005-cmd/grok-tool-).

**Hướng dẫn đầy đủ (kiểu repo lớn):** xem [README gốc](../README.md).

- [Cách dùng từng bước](docs/USAGE.md)
- [Toàn bộ config](docs/CONFIG.md)
- [Kiến trúc](ARCHITECTURE.md)
- [Đẩy GitHub an toàn](SAFE_GITHUB.md)

## 30 giây

```bat
copy config.example.json config.json
:: sửa Sub2API + password — file này không commit

venv\Scripts\pip install -r requirements.txt

:: Terminal 1 — solver (nếu dùng HTTP)
CHAY_SOLVER.bat

:: Terminal 2 — web
CHAY_WEB.bat
:: http://127.0.0.1:8787
```

Hoặc CLI:

```bat
venv\Scripts\python.exe main.py 0 --count 1 --backend protocol
venv\Scripts\python.exe main.py 0 --count 1 --backend browser
```

`ESC` = dừng. Kết quả: `data/accounts.txt` (local only).
