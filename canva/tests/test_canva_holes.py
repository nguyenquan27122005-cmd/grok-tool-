from canreg.mail import extract_proof, _is_canva_mail
from canreg.tmail_policy import HARD_BAN, apply_to_tmail_cfg, preferred_domains, record_good
from canreg.redeem import FAIL_HINTS, OK_HINTS, _classify_text
from canreg.offers import offer_from_page
from canreg.browser import _logged_in, _stage


def test_login_otp_subject():
    p = extract_proof("Enter 165834 in the next 10 minutes.", subject="Your login code is 165834")
    assert p.get("code") == "165834"


def test_signup_otp_subject():
    p = extract_proof("", subject="Your Canva code is 912094")
    assert p.get("code") == "912094"


def test_otp_inside_huge_tmail_html():
    """tmail ghép cả trang Livewire — OTP không được cắt vì nằm sau 500 ký tự."""
    head = "<!DOCTYPE html><html><head>" + ("x" * 800) + "</head><body>"
    html = head + "<div>Your Canva code is 774411</div><p>Enter 774411 in the next 10 minutes.</p></body></html>"
    p = extract_proof(html)
    assert p.get("code") == "774411"
    junk = head + "<span>114477</span><style>color:#123456</style>"
    assert not extract_proof(junk).get("code")


def test_login_mail_detected():
    assert _is_canva_mail("Your login code is 165834", "no-reply@account.canva.com")
    assert _is_canva_mail("Enter 165834 in the next 10 minutes.", "no-reply@account.canva.com")


def test_redeem_fail_couldnt():
    assert _classify_text("We couldn’t redeem your coupon. Please try again.") == "fail"
    assert _classify_text("We couldn't redeem your coupon") == "fail"
    assert any("couldn’t redeem" in h or "couldn't redeem" in h for h in FAIL_HINTS)


def test_redeem_click_not_enough():
    assert "welcome to canva" not in OK_HINTS
    assert _classify_text("Welcome to Canva Create a design") != "ok"


def test_logged_in_not_homepage():
    assert not _logged_in("https://www.canva.com/", "Log in or sign up in seconds Continue with email")
    assert not _logged_in("https://www.canva.com/signup/", "Create your account")
    assert not _logged_in(
        "https://www.canva.com/templates",
        "Log in or sign up in seconds Continue with email",
    )
    assert _logged_in("https://www.canva.com/folder/abc", "Recent designs Create a design")
    assert _logged_in("https://www.canva.com/templates", "Discover templates Photos Videos")


def test_tmail_security_block_is_flagged():
    body = (
        "You’re almost signed up  Enter the code we sent to a@wibucrypto.pro "
        "We can’t sign you up for security reasons. Try to continue with a different email."
    )
    assert _stage("https://www.canva.com/signup/", body) == "flagged"


def test_tmail_skips_wibucrypto():
    assert "wibucrypto.pro" in HARD_BAN
    assert "wibucrypto.pro" not in preferred_domains(["wibucrypto.pro", "aden.name.ng"])
    cfg = apply_to_tmail_cfg(
        {"domains": ["wibucrypto.pro", "aden.name.ng", "melvinscharity.org", "aban.edu.vn"]}
    )
    assert "wibucrypto.pro" not in cfg["domains"]
    assert "melvinscharity.org" not in cfg["domains"]
    assert "aban.edu.vn" not in cfg["domains"]
    assert "aden.name.ng" in cfg["domains"]
    assert "btedra.name.ng" in cfg["domains"]


def test_tmail_hunt_skips_proven():
    record_good("btedra.name.ng")
    cfg = apply_to_tmail_cfg(
        {"domains": ["btedra.name.ng", "aden.name.ng", "wibucrypto.pro"]},
        hunt_new=True,
    )
    assert "wibucrypto.pro" not in cfg["domains"]
    assert "btedra.name.ng" not in cfg["domains"]
    assert "aden.name.ng" in cfg["domains"]


def test_offer_not_cta():
    o = offer_from_page("https://www.canva.com/", "Upgrade to Pro Try Canva Pro Create a design")
    assert o["plan"] == "free"
    assert not o["has_offer"]
    o2 = offer_from_page("https://www.canva.com/settings/billing", "You're a Pro member Your Pro subscription")
    assert o2["plan"] == "pro"
    assert o2["has_offer"]
