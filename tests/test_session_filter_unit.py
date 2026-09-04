#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_session_filter_unit.py — refimage 会话隔离纯逻辑单测（book-05；无需 spark）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runs.h3 import refimage  # noqa: E402

# 构造：会话A两条 + 会话B一条 + 无归属一条
ROWS = [
    {"pool": "up", "name": "aaaa1111_imgA.png", "full": "/x/aaaa1111_imgA.png", "size": 1000, "mtime": 1, "kind": "image"},
    {"pool": "up", "name": "aaaa2222_imgB.png", "full": "/x/aaaa2222_imgB.png", "size": 1000, "mtime": 2, "kind": "image"},
    {"pool": "up", "name": "bbbb1111_imgC.png", "full": "/x/bbbb1111_imgC.png", "size": 1000, "mtime": 3, "kind": "image"},
    {"pool": "out", "name": "cccc1111_old.mp4", "full": "/x/cccc1111_old.mp4", "size": 1000, "mtime": 4, "kind": "video"},
]
BATCH_MAP = {
    "aaaa1111aaaa": {"bid": "b1", "cid": "sessionA"},
    "aaaa2222aaaa": {"bid": "b1", "cid": "sessionA"},
    "bbbb1111bbbb": {"bid": "b2", "cid": "sessionB"},
    # cccc1111cccc 无记录（历史产物，无归属）
}
ok = True

def check(name, got, exp):
    global ok
    t = "PASS" if got == exp else "FAIL"
    print(f"  [{t}] {name}: got={got} exp={exp}")
    ok = ok and (got == exp)

# 会话A：只见 A 的两张图，不含 B/历史
selA = refimage._filter_by_session(ROWS, BATCH_MAP, "sessionA")
check("sessionA 条数", len(selA), 2)
check("sessionA 全是 A", all(r["name"].startswith("aaaa") for r in selA), True)

# 会话B：只见 B
selB = refimage._filter_by_session(ROWS, BATCH_MAP, "sessionB")
check("sessionB 条数", len(selB), 1)

# 未知会话：空
check("sessionX 空", len(refimage._filter_by_session(ROWS, BATCH_MAP, "sessionX")), 0)

# meta 提取
m = refimage._get_row_meta(ROWS[0], BATCH_MAP)
check("meta cid", m.get("cid"), "sessionA")
check("meta bid", m.get("bid"), "b1")
m2 = refimage._get_row_meta(ROWS[3], BATCH_MAP)
check("历史无归属 cid 空", m2.get("cid"), "")

print("UNIT_OK" if ok else "UNIT_FAIL")
sys.exit(0 if ok else 1)
