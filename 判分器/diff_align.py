# -*- coding: utf-8 -*-
"""diff_align.py — S2 归属诊断：运行时 ``map_steps`` vs 人工对齐表（**只在验收时跑**）。

    python 判分器/diff_align.py

它读 ``评测/对齐/T20步点对齐_v2.json``（人工 64 点），**不进运行时**——
``grader.py`` 里没有任何地方 import 本文件，也没有 import 那份对齐表。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from 判分器 import align as AL      # noqa: E402
from 判分器 import grader as G      # noqa: E402
from 验证器 import runner as R      # noqa: E402

ALIGN = ROOT / "评测" / "对齐" / "T20步点对齐_v2.json"


def _home(by: list[str]) -> str:
    return "1:1" if len(by) == 1 else ("1:n" if len(by) >= 2 else "none")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    table = json.loads(ALIGN.read_text(encoding="utf-8"))
    ok = tot = 0
    f1_sum = 0.0
    rows = []
    for it in table["items"]:
        qid = it["qid"]
        points = G.load_points(qid)
        gold = G.load_gold(qid)
        ans = json.loads((ROOT / "评测" / "T20" / "out" / f"{qid}.json")
                         .read_text(encoding="utf-8"))
        doc, _ = R.run_answer(ans, alias=True, alias_qid=qid)
        ours = AL.map_steps(points, gold["steps"], doc["steps"])
        for hp in it["points"]:
            if hp["home"] not in ("1:1", "1:n"):
                continue
            by = ours.get(hp["point_id"], [])
            h = _home(by)
            tot += 1
            ok += h == hp["home"]
            inter = len(set(by) & set(hp["by"]))
            f1 = (2 * inter / (len(by) + len(hp["by"]))) if by else 0.0
            f1_sum += f1
            if h != hp["home"]:
                rows.append((hp["point_id"], hp["home"], h, by, hp["by"]))

    print(f"home 一致：{ok}/{tot} = {ok / tot:.1%}（S2 报告基准 52/64 = 81.2%）")
    print(f"by 平均 F1：{f1_sum / tot:.3f}")
    print(f"不一致 {len(rows)} 处：")
    for pid, hh, oh, by, human in rows:
        print(f"  {pid}: 人工 {hh} {human} | 我们 {oh} {by}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
