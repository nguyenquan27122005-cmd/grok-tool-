"""Auto-split from main.py — modular package."""
from __future__ import annotations

import argparse
import asyncio
import email as email_lib
import imaplib
import json
import logging
import os
import random
import re
import string
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

import requests

from pydoll.browser.chromium import Chrome
from pydoll.browser.options import ChromiumOptions

import grokreg.browser.anti_flag as af
from grokreg.mail.tmail_wibu import TmailWibuProvider
import grokreg.mail.temp_mail_router as tmr
import grokreg.browser.chrome_cleanup as chrome_clean
import grokreg.core.style_log as slog
from grokreg.core.stop_control import (
    StopRequested,
    clear_stop,
    interruptible_sleep,
    is_stop_requested,
    raise_if_stop,
    request_stop,
    sleep_interruptible,
    start_esc_listener,
    stop_reason,
)

from grokreg.core.runtime import (
    ROOT,
    DATA_DIR,
    CONFIG_PATH,
    log,
    MS_CLIENT_IDS,
    FIRST_NAMES,
    LAST_NAMES,
    RATE_LIMIT_PATH,
)


def load_config() -> dict[str, Any]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    # hotmail | azpopmail (temp) | mailtm | auto
    cfg.setdefault("email_provider", "hotmail")
    cfg.setdefault("hotmail_list", "data/hotmails.txt")
    cfg.setdefault("hotmail_max_aliases", 5)
    # https://azpopmail.com/document — temp mail REST API
    cfg.setdefault(
        "azpopmail",
        {
            "base_url": "https://azpopmail.com",
            "token": "",
            "verify_ssl": False,
            "domains": [],
            "poll_interval": 3,
        },
    )
    # https://tmail.wibucrypto.pro/mailbox — Laravel Livewire 2 temp mail
    cfg.setdefault(
        "tmail_wibu",
        {
            "base_url": "https://tmail.wibucrypto.pro",
            "verify_ssl": True,
            "create_mode": "create",
            "poll_interval": 4,
            "domains": [
                "wibucrypto.pro",
                "aden.name.ng",
                "adix.name.ng",
                "aban.edu.vn",
                "codedcapcut.email",
            ],
        },
    )
    # --- anti-flag / overnight defaults ---
    cfg.setdefault("fresh_profile_per_account", True)
    cfg.setdefault("reuse_chrome_profile", False)
    cfg.setdefault("keep_browser_open", False)
    cfg.setdefault("humanize", True)
    cfg.setdefault("human_delay_min", 1.5)
    cfg.setdefault("human_delay_max", 4.5)
    cfg.setdefault("inter_success_delay_min", 45)
    cfg.setdefault("inter_success_delay_max", 90)
    cfg.setdefault("mail_fail_cooldown_min", 120)
    cfg.setdefault("cf_max_retries", 2)
    cfg.setdefault("batch_count", 1)
    cfg.setdefault(
        "antiflag",
        {
            "enabled": True,
            "clear_cookies_on_start": True,
            "clear_storage_on_start": True,
            "stealth_inject": False,
            "force_ua": False,
            "human_typing": True,
            "pre_click_jiggle": True,
            "isolate_profile": True,
            "align_tz_to_ip": True,
            "hide_webdriver": True,
            "browser_preferences": True,
        },
    )
    # Merge critical antiflag keys if config has partial dict
    # Defaults lean Castle-friendly (do NOT force wipe cookies — kills Castle device state)
    if isinstance(cfg.get("antiflag"), dict):
        cfg["antiflag"].setdefault("clear_cookies_on_start", False)
        cfg["antiflag"].setdefault("clear_storage_on_start", False)
        cfg["antiflag"].setdefault("isolate_profile", False)
        cfg["antiflag"].setdefault("align_tz_to_ip", True)
        cfg["antiflag"].setdefault("browser_preferences", True)
        cfg["antiflag"].setdefault("stealth_inject", False)
    # reg_speed: fast (default, closer to competitor ~30–90s browser)
    #             safe (slower humanize / longer Castle)
    cfg.setdefault("reg_speed", "fast")
    speed = str(cfg.get("reg_speed") or "fast").strip().lower()
    if speed == "fast":
        cfg.setdefault("castle_warmup_sec", 3)
        cfg.setdefault("castle_wait_token_sec", 10)
        cfg.setdefault("human_delay_min", 0.35)
        cfg.setdefault("human_delay_max", 1.1)
        cfg.setdefault("cf_wait_sec", 22)
        cfg.setdefault("turnstile_before_email_sec", 8)
        cfg.setdefault("timeout_otp", 120)
        cfg.setdefault("open_grok_after_success", False)
        cfg.setdefault("inter_success_delay_min", 8)
        cfg.setdefault("inter_success_delay_max", 20)
        if isinstance(cfg.get("antiflag"), dict):
            cfg["antiflag"].setdefault("human_typing", False)
            cfg["antiflag"].setdefault("pre_click_jiggle", False)
    else:
        cfg.setdefault("castle_warmup_sec", 12)
        cfg.setdefault("castle_wait_token_sec", 28)
    cfg.setdefault("castle_warmup_sec", 12)
    cfg.setdefault("castle_wait_token_sec", 28)
    cfg.setdefault("castle_retry_on_mint_fail", 1)
    cfg.setdefault("proxy", "")
    cfg.setdefault("headless", False)
    # Web + desktop: never steal focus unless user opts in
    if str(os.environ.get("GROK_NO_FOCUS") or "").strip().lower() in ("1", "true", "yes"):
        cfg["chrome_steal_focus"] = False
        cfg["chrome_window_mode"] = "offscreen"
        cfg["chrome_window_position"] = str(cfg.get("chrome_window_position") or "-2400,40")
        cfg["chrome_background"] = True
    cfg.setdefault("chrome_steal_focus", False)
    cfg.setdefault("chrome_window_mode", "offscreen")
    cfg.setdefault("chrome_window_position", "-2400,40")
    cfg.setdefault("timeout_otp", 180)
    cfg.setdefault("password_length", 14)
    cfg.setdefault("save_file", "data/accounts.txt")
    # Fresh isolated profile every account (anti-flag) — never reuse by default
    cfg.setdefault("chrome_user_data_dir", "chrome_profile")
    cfg.setdefault("chrome_debug_port", 9333)
    cfg["fresh_profile_per_account"] = bool(
        cfg.get("fresh_profile_per_account", True)
    )
    cfg["reuse_chrome_profile"] = bool(cfg.get("reuse_chrome_profile", False))
    if cfg["fresh_profile_per_account"]:
        cfg["reuse_chrome_profile"] = False
    # Skip hotmail still in OTP cooldown (minutes after rate_limit)
    cfg.setdefault("rate_limit_cooldown_min", 55)
    # After signup success, open Grok chat (not leave on accounts.x.ai/account)
    cfg.setdefault("open_grok_after_success", True)
    cfg.setdefault("grok_url", "https://grok.com/")
    # Pipeline: reg success → Sub2API (SSO API preferred, browser OAuth fallback)
    # Learned from grok-register-web: sso cookie → /api/v1/admin/grok/sso-to-oauth
    cfg.setdefault(
        "sub2api",
        {
            "enabled": True,
            "mode": "auto",  # auto | sso_api | browser_oauth
            "sub2api_url": "http://localhost:8080",
            "sub2api_user": "",
            "sub2api_pass": "",
            "sub2api_api_token": "",
            "name_prefix": "grok free",
            "start_number": 1,
            "group": "grok free",
            "group_ids": [],
            "model_test": "Grok 4.5",
            "timeout_oauth_sec": 180,
            "timeout_sec": 180,
            "timeout_test_sec": 120,
            "run_test": False,
            "fallback_browser_oauth": True,
            "durable_retry": True,
            "durable_interval_sec": 60,
        },
    )
    # Fill new keys on older config.json without wiping user values
    _s2 = cfg.setdefault("sub2api", {})
    _s2.setdefault("mode", "auto")
    _s2.setdefault("sub2api_api_token", "")
    _s2.setdefault("group_ids", [])
    _s2.setdefault("timeout_sec", 180)
    _s2.setdefault("fallback_browser_oauth", True)
    _s2.setdefault("durable_retry", True)
    _s2.setdefault("durable_interval_sec", 60)
    _s2.setdefault("run_test", False)
    # External mail reader (dongvanfb by default) — primary OTP source for hotmail
    cfg.setdefault(
        "mail_api",
        {
            "enabled": True,
            "client_id": "9e5f94bc-e8a4-4e73-b8be-63364c29d753",
            "poll_interval": 4,
            "timeout": 180,
            "otp_regex": r"\b(\d{6})\b",
            # Multi-provider list (skip laggy ones by enabled:false)
            "providers": [
                {"name": "mailgen", "enabled": True, "base_url": "https://mailgen.shop"},
                {"name": "mailtm_style", "enabled": False, "base_url": ""},
                {
                    "name": "generic_graph",
                    "enabled": True,
                    "base_url": "https://mailgen.shop",
                },
                {
                    "name": "custom",
                    "enabled": False,
                    "base_url": "http://127.0.0.1:1234",
                    "method": "POST",
                    "endpoint": "/api/otp",
                    "body": {
                        "email": "{email}",
                        "password": "{password}",
                        "refresh_token": "{refresh_token}",
                        "client_id": "{client_id}",
                    },
                    "headers": {},
                },
            ],
        },
    )
    return cfg


