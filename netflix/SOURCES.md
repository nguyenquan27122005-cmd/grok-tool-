# Nguồn tham khảo (Netflix)

Không có repo GitHub public nào làm **đăng ký acc Netflix mới** (HTTP protocol). Phần lớn GitHub là clone UI, login acc sẵn, hoặc household-confirm.

## Official

| | |
|---|---|
| Signup help | https://help.netflix.com/en/node/112419 |
| OTP / magic-link help | https://help.netflix.com/en/node/529303577956964 |
| Signup URL | https://www.netflix.com/signup |
| Login | https://www.netflix.com/login |

Flow máy tính (Help Center): **chọn gói → email + password → payment**. Tool dừng ở bước payment.

OTP/link: tới trong ~2 phút, hết hạn 15 phút. Có nút **Create Password Instead**.

## GitHub (hữu ích, không copy nguyên)

| Repo | Dùng gì |
|---|---|
| [CastagnaIT/plugin.video.netflix](https://github.com/CastagnaIT/plugin.video.netflix) | Login acc **đã có** (Kodi). Không phải signup. Auth key = browser login sẵn. |
| [LBBO/node-netflix2](https://github.com/LBBO/node-netflix2) | Client login acc sẵn. |
| [phd59fr/netflix-household-autovalidator](https://github.com/phd59fr/netflix-household-autovalidator) | Mail from `info@account.netflix.com`. |
| [dan5py/auto-flixer](https://github.com/dan5py/auto-flixer) | From `*@netflix.com`, lấy link netflix.com trong HTML. |

Không dùng: checker/combo (credential stuffing), household bypass (Nikflix), payment/card.

Mail parser tool này: sender Netflix + link `netflix.com/...signup|URL_SIGNUP` + mã 4–8 số.
