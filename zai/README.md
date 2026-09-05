# Z.ai / ZCode Reg

Tool cạnh `grok_tool` / `capcut` / `Heygen`. Reg tool **pure API** — captcha mint
qua **solver service :5073** (pattern solver :5072 của grok_tool/OpenArt).

**Không thấy repo public** trên GitHub làm reg acc Z.ai. Tool này bám frontend chính thức `chat.z.ai`:

1. Solver mint **Aliyun captcha** (loại `INPAINTING` — lỗ được AI tô lại) → in-page
   signup ngay trong Chrome của solver (`captcha_verify_param` gắn session/IP)
2. Mail verify (`/auths/verify_email` + `/auths/finish_signup`)
3. Đọc quota `/users/user/plan-usage`

## Solver (mở một cái python lên giải ẩn)

```bat
CHAY_SOLVER.bat        # cửa sổ CMD nằm nền, Chrome offscreen trong solver
```

Không mở bat cũng được — reg tool **tự kick solver python ẩn** lần đầu cần
(`zaisolver.py`, log tại `data/solver.log`). Reg tool chỉ POST HTTP tới
`:5073/signup`, không dính Chrome.

- Kéo **vòng đóng**: giữ chuột, đọc vị trí mảnh qua CDP, nhả đúng lúc mảnh tới
  đích — không cần model tỉ lệ mảnh/thumb (hệ số đổi theo từng puzzle).
- **Mỗi verify-fail Aliyun sinh puzzle mới** → mỗi drag là một vé độc lập:
  detect lỗ trên từng puzzle (`find_hole` — vùng mượt bất thường do AI inpaint)
  trước khi kéo; detector hụt thì rơi về vị trí quét đều.
- Acc kế được **prefetch signup nền** trong lúc acc hiện tại chờ OTP (stash,
  pattern OpenArt) — alias được mark ledger ngay khi signup OK để không dính
  trùng mailbox.

## Mail

- **Hotmail là mặc định** — `data/hotmails.txt` dạng
  `email|password|refresh_token|client_id` (1 dòng = 1 mailbox, dùng alias
  `+0..+4`, giờ đây z.ai **chặn domain temp**: `EMAIL_DOMAIN_BLOCKED`).
- Guerrilla/azpop/tmail chỉ để test — bị chặn ở bước signup.
- Pool rỗng thì check `grok_tool/data/hotmails.txt` (fallback tự động).

## Weekend Build (16/8–17/8 UTC+8)

- Acc **mới**, login ZCode lần đầu → có thể 100M GLM-5.3 (ZCode only)
- ZCode đã **pause cấp mới 100M**; user mới còn trial ~3M/ngày
- Acc đã có Coding Plan không được 100M
- Sheet `zai` **chỉ ghi acc có quota/offer**

## CLI

```bat
CHAY_REG.bat 1 --count 2
```

`1` = Hotmail (mặc định) · `2` = Azpop · `4` = Guerrilla

Web: tile **Z.ai** trên `http://127.0.0.1:8787/#/register`

Ledger: `data/accounts.txt`
