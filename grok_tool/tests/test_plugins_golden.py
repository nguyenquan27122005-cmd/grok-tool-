"""Golden test — hành vi build_command của plugin PHẢI không đổi qua refactor.

Expected values được chụp từ code gốc (2026-08-22). Nếu refactor làm đổi lệnh
CLI → test fail ngay.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web_console.plugins import all_plugins
from web_console.plugins.sibling import SiblingToolPlugin

# argv tail = cmd[3:] (bỏ python -u main.py / canva_tool.py)
GOLDEN: dict[str, list[tuple[dict, list[str]]]] = {
    "grok": [
        ({"mail": "0", "count": 5, "backend": "github"}, ["2", "--count", "5", "--backend", "github"]),
        ({"mail": "0", "count": 0, "backend": "protocol"}, ["2", "--count", "0", "--backend", "protocol"]),
        ({"mail": "2", "count": 3, "backend": "browser"}, ["2", "--count", "3", "--backend", "browser"]),
        ({"mail": "3", "count": 2, "backend": "auto"}, ["2", "--count", "2", "--backend", "auto"]),
    ],
    "netflix": [
        ({"mail": "2", "count": 4, "backend": "browser"}, ["2", "--count", "4", "--backend", "browser", "--until-success"]),
        ({"mail": "2", "count": 0, "backend": "protocol", "until_success": False},
         ["2", "--count", "0", "--backend", "protocol"]),
        ({"mail": "2", "count": 2, "backend": "auto", "until_success": "false"},
         ["2", "--count", "2", "--backend", "auto"]),
        # resume: checkpoint batch cũ
        ({"mail": "2", "count": 5, "backend": "browser", "resume": True},
         ["2", "--count", "5", "--backend", "browser", "--until-success", "--resume"]),
        ({"mail": "2", "count": 5, "backend": "protocol", "threads": "2"},
         ["2", "--count", "5", "--backend", "protocol", "--until-success", "--threads", "2"]),
    ],
    "heygen": [
        ({"mail": "2", "count": 3, "backend": "protocol"}, ["2", "--count", "3", "--backend", "protocol"]),
        ({"mail": "2", "count": 1, "backend": "auto"}, ["2", "--count", "1", "--backend", "auto"]),
        ({"mail": "2", "count": 1, "backend": "browser"}, ["2", "--count", "1", "--backend", "browser"]),
        # mail lạ → default "2"
        ({"mail": "0", "count": 1, "backend": "protocol"}, ["2", "--count", "1", "--backend", "protocol"]),
        ({"mail": "tmail_wibu", "count": 1, "backend": "protocol"}, ["2", "--count", "1", "--backend", "protocol"]),
    ],
    "capcut": [
        ({"mail": "4", "count": 2, "backend": "protocol"}, ["4", "--count", "2", "--backend", "protocol"]),
        ({"mail": "2", "count": 1, "backend": "protocol"}, ["2", "--count", "1", "--backend", "protocol"]),
        # backend lạ vẫn ép protocol; mail lạ → default 4
        ({"mail": "3", "count": 1, "backend": "browser"}, ["4", "--count", "1", "--backend", "protocol"]),
    ],
    "dreamina": [
        ({"mail": "4", "count": 2, "backend": "protocol"}, ["4", "--count", "2", "--backend", "protocol"]),
        ({"mail": "4", "count": 5, "backend": "protocol", "threads": "2"},
         ["4", "--count", "5", "--backend", "protocol", "--threads", "2"]),
        # backend lạ vẫn ép protocol; mail lạ → default 4
        ({"mail": "3", "count": 1, "backend": "browser"}, ["4", "--count", "1", "--backend", "protocol"]),
    ],
    "zai": [
        ({"mail": "4", "count": 3, "backend": "protocol"}, ["4", "--count", "3", "--backend", "protocol"]),
        ({"mail": "2", "count": 1, "backend": "browser"}, ["2", "--count", "1", "--backend", "protocol"]),
        # mail lạ → default "1" (Hotmail) — z.ai chặn domain temp từ 2026-08
        ({"mail": "3", "count": 1}, ["1", "--count", "1", "--backend", "protocol"]),
    ],
    "manus": [
        ({"mail": "2", "count": 3, "backend": "browser"}, ["2", "--count", "3", "--backend", "browser"]),
        ({"mail": "2", "count": 2, "backend": "browser", "until_success": True},
         ["2", "--count", "2", "--backend", "browser", "--until-success"]),
        ({"mail": "2", "count": 2, "backend": "auto", "until_success": "0"}, ["2", "--count", "2", "--backend", "auto"]),
        # mail lạ → default 2; default until_success = OFF
        ({"mail": "1x", "count": 1}, ["2", "--count", "1", "--backend", "browser"]),
    ],
    "notion": [
        ({"mail": "3", "count": 3, "backend": "browser", "until_success": True, "until_offer": False},
         ["3", "--count", "3", "--backend", "browser", "--until-success"]),
        ({"mail": "3", "count": 1, "backend": "protocol", "until_success": False, "until_offer": True},
         ["3", "--count", "1", "--backend", "protocol", "--until-offer"]),
        # defaults: until_success ON, until_offer OFF; có option "5" Domain riêng
        # nên mail KHÔNG ép "3" nữa — mã lạ giữ nguyên (ở đây "9" giữ "9")
        ({"mail": "9", "count": 1, "backend": "auto"}, ["9", "--count", "1", "--backend", "auto", "--until-success"]),
    ],
    "claude": [
        ({"mail": "1", "count": 2, "backend": "browser"}, ["1", "--count", "2", "--backend", "browser"]),
        ({"mail": "3", "count": 1, "backend": "gpm"}, ["3", "--count", "1", "--backend", "gpm"]),
        # claude KHÔNG ép lại mail temp lạ, giữ nguyên "0"
        ({"mail": "0", "count": 1, "backend": "protocol"}, ["0", "--count", "1", "--backend", "protocol"]),
        ({"mail": "4", "count": 1, "backend": "weird"}, ["4", "--count", "1", "--backend", "browser"]),
    ],
    "canva": [
        ({"job": "reg", "mail": "3", "count": 2, "backend": "browser"}, ["3", "--count", "2", "--backend", "browser"]),
        ({"job": "reg", "mail": "0", "count": 1, "backend": "auto"}, ["0", "--count", "1", "--backend", "auto"]),
        ({"job": "redeem", "codes": "ABC123,DEF456", "threads": 4},
         ["redeem", "--accounts", "data/accounts.txt", "--codes", "data/codes_web.txt",
          "--threads", "4", "--output", "data/proof.json", "--success-only"]),
    ],
    "genspark": [
        ({"mail": "1", "count": 2, "backend": "browser"}, ["1", "--count", "2", "--backend", "browser"]),
        ({"mail": "3", "count": 1, "backend": "gpm"}, ["3", "--count", "1", "--backend", "gpm"]),
        ({"mail": "0", "count": 1, "backend": "protocol"}, ["0", "--count", "1", "--backend", "protocol"]),
        ({"mail": "4", "count": 1, "backend": "weird"}, ["4", "--count", "1", "--backend", "browser"]),
        ({"mail": "5", "count": 1, "backend": "browser", "custom_domain": "nguyenquan.dpdns.org"},
         ["5", "--count", "1", "--backend", "browser", "--custom-domain", "nguyenquan.dpdns.org"]),
    ],
}

EXPECTED_CWD = {
    "grok": "",
    "netflix": "netflix",
    "heygen": "Heygen",
    "capcut": "capcut",
    "dreamina": "dreamina",
    "zai": "zai",
    "manus": "manus",
    "notion": "notion",
    "claude": "claude",
    "canva": "canva",
    "chatgpt": "chatgpt",
    "genspark": "genspark",
}

EXPECTED_ENV = [
    ("capcut", {"invite": "X1", "claim_offer": False}, {"CAPCUT_INVITE": "X1", "CAPCUT_CLAIM": "0"}),
    ("capcut", {"invite": "", "claim_offer": True}, {"CAPCUT_CLAIM": "1"}),
    ("manus", {"invite": "INV9"}, {"MANUS_INVITE": "INV9"}),
    ("notion", {"partner": "P7"}, {"NOTION_PARTNER": "P7"}),
    ("genspark", {"claim_free_month": False}, {"GENSPARK_CLAIM": "0"}),
    ("genspark", {"claim_free_month": True}, {"GENSPARK_CLAIM": "1"}),
]


class GoldenCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        # build_command với mail Hotmail đọc pool acc thật (file local, không
        # commit). Mock pool để golden test chỉ đo shape argv — deterministic.
        patcher = mock.patch.object(
            SiblingToolPlugin, "hotmail_pool", return_value={"slots": 10},
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.plugins = all_plugins()

    def test_build_commands_unchanged(self) -> None:
        for tool, cases in GOLDEN.items():
            p = self.plugins[tool]
            for params, expected_tail in cases:
                with self.subTest(tool=tool, params=params):
                    cmd = p.build_command(params, ROOT)
                    self.assertIn(cmd[2], ("main.py", "canva_tool.py"))
                    self.assertEqual(cmd[3:], expected_tail, f"{tool} {params}")

    def test_cwd_unchanged(self) -> None:
        for tool, rel in EXPECTED_CWD.items():
            p = self.plugins[tool]
            cwd = p.cwd(ROOT)
            self.assertEqual(cwd, ROOT if not rel else ROOT.parent / rel, tool)

    def test_chatgpt_node_command(self) -> None:
        # Tool Node (đổi 2FA/pass) — không đi qua python main.py nên test riêng.
        import shutil

        p = self.plugins["chatgpt"]
        cmd = p.build_command({"accounts": "a@b.c|x|Y"}, ROOT)
        node = shutil.which("node") or "node"
        self.assertEqual(cmd[0], node)
        self.assertEqual(
            cmd[1:],
            ["change-2fa.mjs", "--file", "data/chatgpt_accounts.txt",
             "--output", "data/chatgpt_2fa_moi.txt"],
        )
        # field resume/threads tự sinh của SiblingToolPlugin phải bị lọc bỏ
        self.assertEqual([f.key for f in p.meta.fields], ["accounts"])

    def test_env_overrides_unchanged(self) -> None:
        for tool, params, expected in EXPECTED_ENV:
            p = self.plugins[tool]
            if not hasattr(p, "env_overrides"):
                continue
            with self.subTest(tool=tool, params=params):
                self.assertEqual(p.env_overrides(params), expected)

    def test_fields_signature_unchanged(self) -> None:
        # (fields gốc + field "resume" tự sinh từ SiblingToolPlugin kể từ batch E)
        sig = {t: [(f.key, str(f.default)) for f in self.plugins[t].meta.fields] for t in GOLDEN}
        self.assertEqual(
            sig["netflix"],
            [("mail", "1"), ("custom_domain", "nguyenquan.dpdns.org"), ("count", "1"),
             ("backend", "browser"), ("until_success", "True"),
             ("resume", "False"), ("threads", "1"), ("custom_read_mailbox", "auto")],
        )
        self.assertEqual(
            sig["capcut"],
            [("mail", "4"), ("custom_domain", "nguyenquan.dpdns.org"), ("count", "1"),
             ("backend", "protocol"), ("invite", ""), ("claim_offer", "True"),
             ("resume", "False"), ("threads", "1"), ("custom_read_mailbox", "auto")],
        )
        self.assertEqual(
            sig["notion"],
            [("mail", "3"), ("custom_domain", "nguyenquan.dpdns.org"), ("count", "1"),
             ("backend", "browser"), ("partner", ""), ("sheet_all", "False"),
             ("until_success", "True"), ("until_offer", "False"),
             ("resume", "False"), ("threads", "1"), ("custom_read_mailbox", "auto")],
        )
        self.assertEqual(
            sig["manus"],
            [("mail", "2"), ("count", "1"), ("backend", "browser"), ("invite", ""), ("until_success", "False"),
             ("resume", "False"), ("threads", "1")],
        )


if __name__ == "__main__":
    unittest.main()
