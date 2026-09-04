#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_session_filter_unit.py — refimage 会话隔离纯逻辑单测（book-05；含同图多会话/重复登记场景）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runs.h3 import refimage  # noqa: E402

# 会话A两张 + 会话B一张 + 一张"同图多会话"（A 上传后 B 重复上传，都登记）+ 历史无归属
ROWS = [
    {"pool": "up", "name": "aaaa1111_imgA.png", "full": "/x/aaaa1111_imgA.png", "size": 1000, "mtime": 1, "kind": "image"},
    {"pool": "up", "name": "aaaa2222_imgB.png", "full": "/x/aaaa2222_imgB.png", "size": 1000, "mtime": 2, "kind": "image"},
    {"pool": "up", "name": "bbbb1111_imgC.png", "full": "/x/bbbb1111_imgC.png", "size": 1000, "mtime": 3, "kind": "image"},
    {"pool": "up", "name": "dddd1111_shared.png", "full": "/x/dddd1111_shared.png", "size": 1000, "mtime": 4, "kind": "image"},
    {"pool": "out", "name": "cccc1111_old.mp4", "full": "/x/cccc1111_old.mp4", "size": 1000, "mtime": 5, "kind": "video"},
]
BATCH_MAP = {
    "aaaa1111aaaa": {"bid": "b1", "cids": {"sessionA"}},
    "aaaa2222aaaa": {"bid": "b1", "cids": {"sessionA"}},
    "bbbb1111bbbb": {"bid": "b2", "cids": {"sessionB"}},
    "dddd1111dddd": {"bid": "b3", "cids": {"sessionA", "sessionB"}},  # 同图两会话
}
ok = True

def check(name, got, exp):
    global ok
    t = "PASS" if got == exp else "FAIL"
    print(f"  [{t}] {name}: got={got} exp={exp}")
    ok = ok and (got == exp)

selA = refimage._filter_by_session(ROWS, BATCH_MAP, "sessionA")
check("sessionA 条数", len(selA), 3)  # imgA/imgB/shared
check("sessionA 含 shared", any(r["name"] == "dddd1111_shared.png" for r in selA), True)
selB = refimage._filter_by_session(ROWS, BATCH_MAP, "sessionB")
check("sessionB 条数", len(selB), 2)  # imgC/shared
check("sessionX 空", len(refimage._filter_by_session(ROWS, BATCH_MAP, "sessionX")), 0)
m = refimage._get_row_meta(ROWS[3], BATCH_MAP)
check("shared cids 双会话", m.get("cids") == {"sessionA", "sessionB"}, True)
m2 = refimage._get_row_meta(ROWS[4], BATCH_MAP)
check("历史无归属 cids 空", m2.get("cids") == set(), True)
print("UNIT_OK" if ok else "UNIT_FAIL")
sys.exit(0 if ok else 1)
