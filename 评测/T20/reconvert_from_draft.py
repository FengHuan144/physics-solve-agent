#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""reconvert_from_draft.py — 用盘上已存的模型草稿离线重转，不调 API、不花钱。

为什么需要它：`run_solve.py` 每次都重新请求模型。T26 修了 `draft_to_schema.py`
（两处：三角误判 / discussion 空 eq 崩溃）之后，A-01 的草稿已经在 `raw/` 里，
再花一次钱重跑没有意义；基线 7 题的草稿也都在，重转基线变体同样不该花钱。

它做的三件事与 `run_solve.py` 单题路径一致：
    raw/<qid>_draft.json + schema/examples/<qid>.json + raw/<qid>_call.json
      → D2S.build() → out/<qid><tag>.json → validate_schema + 验证器.cli
唯一差别：不请求 API，cm 从 `<qid>_call.json` 的 usage 里取。

用法：
    python 评测/T20/reconvert_from_draft.py --qid A-01            # 落 out/A-01.json
    python 评测/T20/reconvert_from_draft.py --qid A-02 --tag _t26fix   # 落变体，不覆盖
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import draft_to_schema as D2S          # noqa: E402
import run_solve as R                  # noqa: E402  复用它的 validate()，保证日志口径一致

TZ = timezone(timedelta(hours=8))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qid", required=True)
    ap.add_argument("--tag", default="", help="输出后缀，如 _t26fix；空则直接覆盖同名产物")
    ap.add_argument("--draft-tag", default="", help="草稿后缀（如 _nothink / _eflow），默认空")
    args = ap.parse_args()

    qid, tag = args.qid, args.tag
    draft_p = HERE / "raw" / ("%s_draft%s.json" % (qid, args.draft_tag))
    if not draft_p.exists():
        raise SystemExit("找不到草稿：%s" % draft_p)
    draft = json.loads(draft_p.read_text(encoding="utf-8"))
    gold = json.loads((R.EX_DIR / ("%s.json" % qid)).read_text(encoding="utf-8"))

    call_p = HERE / "raw" / ("%s_call%s.json" % (qid, args.draft_tag))
    call = json.loads(call_p.read_text(encoding="utf-8")) if call_p.exists() else {}
    usage = call.get("usage") or {}
    cm = {"model": call.get("model") or R.MODEL,
          "temperature": call.get("temperature", R.TEMPERATURE),
          "latency_ms": call.get("latency_ms") or 0,
          "tokens_in": usage.get("prompt_tokens", 0),
          "tokens_out": usage.get("completion_tokens", 0)}

    stamp = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
    doc, issues = D2S.build(qid, draft, gold, cm)
    out = HERE / "out" / ("%s%s.json" % (qid, tag))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    neq = sum(1 for s in doc["steps"] if s.get("equation"))
    print("[重转] %s%s  步 %d（金标 %d）  有方程 %d  issue %d  源草稿 %s"
          % (qid, tag, len(doc["steps"]), len(gold["steps"]), neq, len(issues), draft_p.name))
    for it in issues[:10]:
        print("   issue: " + it[:150])

    v = R.validate(qid, out, stamp)
    print("[Schema] E=%d W=%d rc=%d" % (v["n_e"], v["n_w"], v["schema_rc"]))
    for l in v["e_lines"]:
        print("   " + l.strip()[:160])
    print("[验证器] rc=%d  %s" % (v["runner_rc"], (v["runner_out"].strip().splitlines() or [""])[-1][:160]))

    (HERE / "logs" / ("reconvert_%s%s_%s.json" % (qid, tag, stamp))).write_text(
        json.dumps({"qid": qid, "tag": tag, "draft": draft_p.name, "call": call_p.name,
                    "cm": cm, "n_steps": len(doc["steps"]), "n_gold": len(gold["steps"]),
                    "n_eq": neq, "issues": issues,
                    "n_e": v["n_e"], "n_w": v["n_w"],
                    "e_lines": v["e_lines"], "chained": True,
                    "note": "离线重转：未调用 API，cm 取自 raw/%s_call.json" % qid},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
