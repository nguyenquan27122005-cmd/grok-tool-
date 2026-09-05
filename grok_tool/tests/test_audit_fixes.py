"""Self-check cho các fix audit 2026-09-05.

- batch_runner.should_stop_time: anchor vào thời điểm start (version cũ tự
  dừng ngay khi start trước giờ cắt).
- overnight_runner.should_stop: cùng mẫu lỗi (hour >= 6 dừng cả lúc 22:00).
- delivery_retry._load_queue: file hỏng phải được giữ lại (.corrupt-*), không
  được im lặng coi như queue rỗng rồi xoá sạch ở save kế tiếp.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import grokreg.tools.batch_runner as br
import grokreg.tools.overnight_runner as ov
from grokreg.delivery import delivery_retry as dr


class BatchStopTimeTest(unittest.TestCase):
    def _fake_now(self, y, mo, d, h, mi):
        class FakeDatetime(datetime):
            @classmethod
            def now(cls):  # noqa: D102
                return cls(y, mo, d, h, mi)

        return FakeDatetime

    def test_start_before_cutoff_runs_until_cutoff(self) -> None:
        # start 08:00, cutoff 10:30 → 08:05 vẫn chạy
        br.datetime = self._fake_now(2026, 9, 6, 8, 5)
        self.assertFalse(br.should_stop_time(10, 30, datetime(2026, 9, 6, 8, 0)))

    def test_start_before_cutoff_stops_after_cutoff(self) -> None:
        br.datetime = self._fake_now(2026, 9, 6, 10, 31)
        self.assertTrue(br.should_stop_time(10, 30, datetime(2026, 9, 6, 8, 0)))

    def test_start_evening_runs_to_next_morning_cutoff(self) -> None:
        # start 22:00, cutoff 10:30 → 23:00 & 05:00 hôm sau vẫn chạy
        br.datetime = self._fake_now(2026, 9, 6, 23, 0)
        self.assertFalse(br.should_stop_time(10, 30, datetime(2026, 9, 6, 22, 0)))
        br.datetime = self._fake_now(2026, 9, 7, 5, 0)
        self.assertFalse(br.should_stop_time(10, 30, datetime(2026, 9, 6, 22, 0)))
        br.datetime = self._fake_now(2026, 9, 7, 10, 31)
        self.assertTrue(br.should_stop_time(10, 30, datetime(2026, 9, 6, 22, 0)))


class OvernightStopTest(unittest.TestCase):
    def test_evening_start_runs_until_6am(self) -> None:
        old = ov.now, ov._RUN_START
        try:
            ov.now = lambda: datetime(2026, 9, 6, 22, 0)  # type: ignore[assignment]
            ov._RUN_START = datetime(2026, 9, 6, 22, 0)
            self.assertFalse(ov.should_stop())
            ov.now = lambda: datetime(2026, 9, 7, 5, 59)  # type: ignore[assignment]
            self.assertFalse(ov.should_stop())
            ov.now = lambda: datetime(2026, 9, 7, 6, 0)  # type: ignore[assignment]
            self.assertTrue(ov.should_stop())
        finally:
            ov.now, ov._RUN_START = old  # type: ignore[assignment]


class DeliveryQueueCorruptTest(unittest.TestCase):
    def test_corrupt_queue_file_is_kept_aside(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            qf = Path(td) / "delivery_queue.json"
            qf.write_text("{không phải json", encoding="utf-8")
            old = dr.QUEUE_FILE
            dr.QUEUE_FILE = qf
            try:
                items = dr._load_queue()
                self.assertEqual(items, [])
                # file gốc phải còn — đổi tên thành .corrupt-*, KHÔNG biến mất
                aside = list(Path(td).glob("delivery_queue.corrupt-*.json"))
                self.assertEqual(len(aside), 1, aside)
                self.assertIn("không phải json", aside[0].read_text(encoding="utf-8"))
            finally:
                dr.QUEUE_FILE = old


if __name__ == "__main__":
    unittest.main()
