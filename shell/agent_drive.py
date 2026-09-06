# -*- coding: utf-8 -*-
"""固化: shell/agent_drive.py — 以用户行为驱动 7860 调度器(可复用).

用法: python3 shell/agent_drive.py --images A.png,B.png,C.png,D.png --text "..." [--base http://127.0.0.1:7860]
流程: 新会话 -> 逐张上传(_upload) -> 发送(send) -> 打印会话 cid 与 agent 最后回复。
"""
import argparse
import json
import re
import sys
import httpx
from gradio_client import Client, handle_file


def main() -> int:
    ap = argparse.ArgumentParser(description="以用户行为驱动 7860 调度器 agent")
    ap.add_argument("--images", default="", help="逗号分隔的本地图片路径(上传到会话资源池)")
    ap.add_argument("--text", default="", help="用户口吻需求文本")
    ap.add_argument("--base", default="http://127.0.0.1:7860", help="agent UI 地址(本机隧道)")
    ap.add_argument("--timeout", type=int, default=900, help="单步超时(秒)")
    args = ap.parse_args()

    c = Client(args.base, verbose=False,
               httpx_kwargs={"timeout": httpx.Timeout(args.timeout, connect=30)})
    r_new = c.predict(api_name="/_new")
    cid = "?"
    try:
        m = re.search(r"([0-9]{8}_[0-9]{6}_[0-9a-z]{4})", str(r_new[2]))
        cid = m.group(1) if m else "?"
    except Exception:  # noqa: BLE001
        pass
    print("CID:", cid)

    imgs = [s.strip() for s in (args.images or "").split(",") if s.strip()]
    for i, p in enumerate(imgs):
        r_up = c.predict(api_name="/_upload", files=[handle_file(p)])
        try:
            note = json.dumps(r_up, ensure_ascii=False)
            m2 = re.search(r"(本会话素材池现有 [0-9]+ 项|个素材已在本会话池中)", note)
            print("  uploaded[%d]" % i, m2.group(1) if m2 else "ok")
        except Exception:  # noqa: BLE001
            print("  uploaded[%d] ok" % i)

    r_send = c.predict(api_name="/send", user_text=args.text)
    try:
        chat = r_send[0] if isinstance(r_send, (list, tuple)) else r_send
        last = chat[-1] if isinstance(chat, list) else chat
        print("LAST_MSG:", json.dumps(last, ensure_ascii=False)[:1200])
    except Exception as e:  # noqa: BLE001
        print("LAST_MSG_ERR:", e)
    print("DRIVE_DONE cid=", cid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
