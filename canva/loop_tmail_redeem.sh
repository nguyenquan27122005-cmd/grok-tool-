#!/bin/bash
# Loop: reg Canva bằng tmail + auto-redeem LINKEDINCANVA đến khi coupon chết.
# Dừng khi: mã bị blacklist (dead-code), log báo không còn mã, hoặc reg hỏng liên tiếp.
cd /d/grok_tool/canva || exit 1
PY=../grok_tool/venv/Scripts/python.exe
MAX_ROUNDS=12
FAIL_LIMIT=4
SF=/tmp/tmail_loop_status.txt
: > "$SF"
consec_fail=0
dead_re='invalid|expired|already redeemed|already used|not eligible|hết hạn|không hợp lệ|đã được sử dụng|đã dùng|unable to redeem'

for i in $(seq 1 $MAX_ROUNDS); do
  echo "=== ROUND $i $(date +%H:%M:%S) ===" >> "$SF"
  PYTHONUTF8=1 PYTHONIOENCODING=utf-8 "$PY" -u main.py 3 --count 1 --backend browser > "/tmp/tmail_round_$i.log" 2>&1
  rv=$(grep -aoE "Kết quả: [a-zA-Z_:0-9@.+ -]+" "/tmp/tmail_round_$i.log" | tail -1)
  rd=$(grep -aE "\[.\] (SUKSES|FAIL).*LINKEDINCANVA" "/tmp/tmail_round_$i.log" | tail -1)
  echo "REG: $rv" >> "$SF"
  echo "REDEEM: $rd" >> "$SF"

  if echo "$rd" | grep -qiE "$dead_re"; then
    echo "STOP: COUPON_DEAD" >> "$SF"
    break
  fi
  if echo "$rv" | grep -q "success"; then
    consec_fail=0
    # reg thành công mà không có "Redeem ngay" → mã đã bị blacklist/hết
    if ! grep -aq "Redeem ngay" "/tmp/tmail_round_$i.log"; then
      echo "STOP: NO_CODE_ACTIVE" >> "$SF"
      break
    fi
  else
    consec_fail=$((consec_fail+1))
    echo "reg fail streak=$consec_fail" >> "$SF"
    if [ "$consec_fail" -ge "$FAIL_LIMIT" ]; then
      echo "STOP: REG_KEEP_FAILING" >> "$SF"
      break
    fi
  fi
  sleep 8
done
echo "LOOP_DONE $(date +%H:%M:%S)" >> "$SF"
