# -*- coding: utf-8 -*-
"""grading.py — T25 采分点级判分器：读一份自由作答的 answer JSON，逐 ``point_id`` 给分。

设计边界（卡 §0 / §2）：
- 复用 ``验证器/runner.py:run_answer()`` 产 L1/L2 结论，**不重写**任何验证层。
- 输入只读。金标只读 ``steps[]`` 与 ``situation``；``grading`` 字段在装载时就被丢弃，
  代码里任何地方都拿不到它（见 ``load_gold``）。
- ``评测/对齐/T20步点对齐_v2.json`` **不是运行时输入**，只用于 ``diff_align.py`` 验。

阶段（卡 §6）：
- S1 骨架：全点 ``na``，先把结构、契约、幂等做对。
- S2 归属与三态；S3 等价与结构隐含；S4 merged 与全量核对。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:            # 允许 `python 判分器/grader.py`
    sys.path.insert(0, str(ROOT))

from 验证器 import runner as R          # noqa: E402

XLSX_PATH = ROOT / "原始资料" / "五卷力学大题_采分点总表_v2.xlsx"
GOLD_DIR = ROOT / "schema" / "examples"
OUT_DIR = ROOT / "判分器" / "out"
DEFAULT_ANSWER_DIR = ROOT / "评测" / "T20" / "out"

QIDS = ("A-02", "A-08", "A-10", "B-02", "B-09", "B-12", "B-20")

# 阶段版本写进产物，用于区分「占位产物」与「真判产物」。contract 只校验该字段存在，
# **不校验 basis 与版本是否自洽**（那需要人看，见审核记录 R-3）。
GRADER_VERSION = "t25-s1"

# 金标可读字段白名单。``grading`` 不在其中——读它等于抄答案（卡 §2 陷阱 3）。
GOLD_READABLE_FIELDS = ("steps", "situation")

# ``na`` 的原因标签（D1 的 C 形态要求 na 按原因分列，先定枚举，S2 起使用）
NA_REASONS = (
    "未实现",        # 该阶段尚未实现
    "无候选步",      # 模型答案里找不到任何承载该点的步
    "白名单外符号",  # 步内符号不在知识表白名单，L1/L2 均不可判
    "merged分摊",    # 一步同时承载多个点，部分对无处分摊
    "无锚点",        # equation 与 criterion 双空
    "规范未过",      # 式子等价但结果规范（单位/方向/舍根）不达标
)


# --------------------------------------------------------------------------- 采分点

def load_points(qid: str, xlsx: Path = XLSX_PATH) -> list[dict]:
    """从冻结总表读该题全部采分点，按表内行序返回。

    只读五列：``point_id`` / ``分值`` / ``判分口径`` / ``采分点（必须出现的式子或判断）`` /
    ``采分类别``。不写盘、不改表。
    """
    import openpyxl

    wb = openpyxl.load_workbook(xlsx, data_only=True, read_only=True)
    ws = wb["采分点总表"]
    rows = ws.iter_rows(values_only=True)
    header = [str(c).strip() if c is not None else "" for c in next(rows)]
    idx = {h: i for i, h in enumerate(header)}
    need = ("point_id", "分值", "判分口径", "采分点（必须出现的式子或判断）", "采分类别")
    missing = [h for h in need if h not in idx]
    if missing:
        wb.close()
        raise SystemExit(f"总表缺列：{missing}")

    out: list[dict] = []
    for row in rows:
        pid = row[idx["point_id"]]
        if not pid:
            continue
        pid = str(pid).strip()
        if not pid.startswith(qid + "-S"):
            continue
        out.append({
            "point_id": pid,
            "score": float(row[idx["分值"]] or 0),
            "criterion": str(row[idx["采分点（必须出现的式子或判断）"]] or "").strip(),
            "rubric": str(row[idx["判分口径"]] or "").strip(),
            "category": str(row[idx["采分类别"]] or "").strip(),
        })
    wb.close()
    if not out:
        raise SystemExit(f"总表里找不到 {qid} 的采分点")
    return out


def load_gold(qid: str) -> dict:
    """读金标，**只返回白名单字段**。

    卡 §2 陷阱 3：``grading.point_hits`` 是「标准答案自己拿了多少分」，读了等于抄答案。
    这里在装载处物理丢弃，后续函数拿不到，也就不可能误用。
    """
    path = GOLD_DIR / f"{qid}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    gold = {k: raw.get(k) for k in GOLD_READABLE_FIELDS}
    assert "grading" not in gold, "金标 grading 字段不得进入判分链路"
    return gold


def gold_point_ids(gold: dict) -> list[str]:
    """金标步上登记的 point_id，按步序。"""
    return [str(s["point_id"]) for s in (gold.get("steps") or []) if s.get("point_id")]


# --------------------------------------------------------------------------- 判分

def build_skeleton(qid: str, mode: str, points: list[dict]) -> dict:
    """S1：全点 na 占位。结构完整，分数恒 0。"""
    rows = []
    for p in points:
        rows.append({
            "point_id": p["point_id"],
            "credit": "na",
            "score": 0.0,
            "score_range": [0.0, p["score"]],
            "by": [],
            "basis": "未实现",
            "uncertain": True,
        })
    return {
        "qid": qid,
        "mode": mode,
        "grader_version": GRADER_VERSION,
        "points": rows,
        "summary": summarize(rows, points),
        "na_reasons": {"未实现": len(rows)},
    }


def summarize(rows: list[dict], points: list[dict]) -> dict:
    """题级汇总。``score`` 必须能由点级求和得到，这里只做求和，不另算。"""
    hit = sum(1 for r in rows if r["credit"] == "hit")
    miss = sum(1 for r in rows if r["credit"] == "miss")
    na = sum(1 for r in rows if r["credit"] == "na")
    total = len(rows)
    score = round(sum(float(r["score"]) for r in rows), 6)
    score_total = round(sum(float(p["score"]) for p in points), 6)
    judged_n = hit + miss
    return {
        "total": total,
        "hit": hit,
        "miss": miss,
        "na": na,
        "score": score,
        "score_total": score_total,
        "judged_rate": f"{judged_n}/{total}",
        "hit_rate": (f"{hit}/{judged_n}" if judged_n else None),
    }


def grade(answer_path: Path, out_path: Path | None = None) -> dict:
    """判一份答案，返回产物 dict；给了 ``out_path`` 就写盘。"""
    answer = json.loads(answer_path.read_text(encoding="utf-8"))
    qid = str((answer.get("meta") or {}).get("question_id") or answer_path.stem)
    mode = str((answer.get("meta") or {}).get("mode") or "free")

    points = load_points(qid)
    gold = load_gold(qid)
    gold_ids = gold_point_ids(gold)
    if gold_ids != [p["point_id"] for p in points]:
        raise SystemExit(
            f"{qid}: 总表点数 {len(points)} 与金标步登记 {len(gold_ids)} 不一致 "
            f"（或顺序不同），拒绝判分")

    # 复用验证器：L1/L2 结论写进 doc.steps[].checks，S2 起作为第一优先级证据。
    _doc, _report = R.run_answer(answer, alias=True, alias_qid=qid)

    product = build_skeleton(qid, mode, points)
    write_product(product, out_path)
    return product


def write_product(product: dict, out_path: Path | None):
    if out_path is None:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(product, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    out_path.write_text(text, encoding="utf-8", newline="\n")


def _summary_line(product: dict) -> str:
    s = product["summary"]
    return (f"{product['qid']}  {product['grader_version']}  "
            f"total {s['total']}  hit {s['hit']}  miss {s['miss']}  na {s['na']}  "
            f"score {s['score']}/{s['score_total']}  judged {s['judged_rate']}  "
            f"hit_rate {s['hit_rate']}")


# --------------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="T25 采分点级判分器")
    ap.add_argument("--answer", help="单份答案 JSON")
    ap.add_argument("--out", help="产物写到这里（默认 判分器/out/{qid}.json）")
    ap.add_argument("--all", action="store_true", help="判 7 题（评测/T20/out/{qid}.json）")
    ap.add_argument("--answer-dir", default=str(DEFAULT_ANSWER_DIR),
                    help="--all 时读答案的目录")
    ap.add_argument("--out-dir", default=str(OUT_DIR), help="--all 时写产物的目录")
    args = ap.parse_args(argv)

    if args.all:
        out_dir = Path(args.out_dir)
        bad = 0
        for qid in QIDS:
            p = Path(args.answer_dir) / f"{qid}.json"
            if not p.exists():
                print(f"{qid}  缺失答案：{p}")
                bad += 1
                continue
            prod = grade(p, out_dir / f"{qid}.json")
            print(_summary_line(prod))
        return 1 if bad else 0

    if not args.answer:
        ap.error("要么给 --answer，要么给 --all")
    p = Path(args.answer)
    out = Path(args.out) if args.out else OUT_DIR / f"{p.stem}.json"
    prod = grade(p, out)
    print(_summary_line(prod))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
