# -*- coding: utf-8 -*-
"""contract.py — 产物契约自校验（卡 §3 六条硬约束的机器版）。

用法::

    python 判分器/contract.py 判分器/out/*.json
    python 判分器/contract.py 判分器/out/A-02.json --answers-dir 评测/T20/out

**故意不复用 grader.py 的装载器**：产物校验器如果和产物生成器共用同一段读表代码，
读表本身错了就两边一起错。这里自己读总表、自己读答案，独立算一遍。

退出码 0 = 全部合格；1 = 有违约（逐条打印）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
XLSX_PATH = ROOT / "原始资料" / "五卷力学大题_采分点总表_v2.xlsx"
ANSWER_DIR = ROOT / "评测" / "T20" / "out"

CREDITS = ("hit", "miss", "na")
# T31 §3.1④/§3.2④ 追加：merged_step / field_mismatch / slot_collision；
# 段1 实测再补「欠定」（符号全在白名单、但方程欠定/无值可代，旧六标签无一能描述）。
NA_REASONS = ("未实现", "无候选步", "白名单外符号", "merged分摊", "无锚点", "规范未过",
              "merged_step", "field_mismatch", "slot_collision", "欠定")
BANNED_BASIS = ("意思对了", "差不多")


def _points_from_xlsx(qid: str) -> dict[str, float]:
    import openpyxl

    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True, read_only=True)
    ws = wb["采分点总表"]
    rows = ws.iter_rows(values_only=True)
    header = [str(c).strip() if c is not None else "" for c in next(rows)]
    i_pid, i_score = header.index("point_id"), header.index("分值")
    out: dict[str, float] = {}
    for row in rows:
        pid = row[i_pid]
        if pid and str(pid).strip().startswith(qid + "-S"):
            out[str(pid).strip()] = float(row[i_score] or 0)
    wb.close()
    return out


def _step_ids(qid: str, answers_dir: Path) -> set[str] | None:
    p = answers_dir / f"{qid}.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    return {str(s.get("step_id")) for s in (d.get("steps") or [])}


def check_one(path: Path, answers_dir: Path) -> tuple[list[str], str]:
    bad: list[str] = []
    d = json.loads(path.read_text(encoding="utf-8"))
    qid = d.get("qid")
    if not qid:
        return [f"{path.name}: 缺 qid"], "?"
    for k in ("mode", "points", "summary", "grader_version", "na_reasons"):
        if k not in d:
            bad.append(f"{qid}: 缺顶层字段 {k}")
    rows = d.get("points") or []
    table = _points_from_xlsx(qid)
    ids = [r.get("point_id") for r in rows]
    if len(set(ids)) != len(ids):
        bad.append(f"{qid}: point_id 有重复")
    if set(ids) != set(table):
        miss = sorted(set(table) - set(ids))
        extra = sorted(set(ids) - set(table))
        bad.append(f"{qid}: 点集与总表不一致（缺 {miss}，多 {extra}）")
    if ids != sorted(ids, key=lambda x: int(str(x).split("-S")[-1])):
        bad.append(f"{qid}: 点未按步序排列")

    steps = _step_ids(qid, answers_dir)
    for r in rows:
        pid = r.get("point_id")
        need = ("point_id", "credit", "score", "score_range", "by", "basis", "uncertain")
        miss_fields = [k for k in need if k not in r]
        if miss_fields:
            bad.append(f"{pid}: 缺四要素字段 {miss_fields}")
            continue
        credit = r["credit"]
        if credit not in CREDITS:
            bad.append(f"{pid}: credit={credit!r} 不在 {CREDITS}")
        mx = table.get(pid, 0.0)
        score = r["score"]
        rng = r["score_range"]
        if not isinstance(rng, list) or len(rng) != 2 or not (rng[0] <= rng[1]):
            bad.append(f"{pid}: score_range 非法 {rng}")
        elif not (rng[0] - 1e-9 <= score <= rng[1] + 1e-9):
            bad.append(f"{pid}: score={score} 不在区间 {rng}")
        if score < 0 or score > mx + 1e-9:
            bad.append(f"{pid}: score={score} 超出该点分值 {mx}")
        if not isinstance(r["uncertain"], bool):
            bad.append(f"{pid}: uncertain 必须是 bool")
        if not r["uncertain"] and isinstance(rng, list) and len(rng) == 2:
            if abs(score - rng[0]) > 1e-9 or abs(score - rng[1]) > 1e-9:
                bad.append(f"{pid}: 非 uncertain 点 score 与 score_range 不一致")
        if credit in ("miss", "na") and abs(score) > 1e-9:
            bad.append(f"{pid}: credit={credit} 但 score={score}（必须为 0）")
        if credit == "hit" and score <= 1e-9:
            bad.append(f"{pid}: credit=hit 但 score={score}（命中必须给分；总表最小分值 1）")
        if not isinstance(r["by"], list) or any(not isinstance(x, str) for x in r["by"]):
            bad.append(f"{pid}: by 必须是字符串数组")
        if credit == "hit" and not r["by"]:
            bad.append(f"{pid}: hit 但 by 为空（指不出哪一步 = 没命中）")
        if steps is not None:
            ghost = [x for x in r["by"] if x not in steps]
            if ghost:
                bad.append(f"{pid}: by 指向不存在的步 {ghost}")
        if not isinstance(r["basis"], str) or not r["basis"].strip():
            bad.append(f"{pid}: basis 为空")
        elif any(w in r["basis"] for w in BANNED_BASIS):
            bad.append(f"{pid}: basis 含禁用措辞（{r['basis']}）")

    s = d.get("summary") or {}
    for k in ("total", "hit", "miss", "na", "score", "score_total",
              "judged_rate", "hit_rate"):
        if k not in s:
            bad.append(f"{qid}: summary 缺 {k}")
    if s.get("total") != len(rows):
        bad.append(f"{qid}: summary.total={s.get('total')} ≠ 点数 {len(rows)}")
    for credit in CREDITS:
        n = sum(1 for r in rows if r.get("credit") == credit)
        if s.get(credit) != n:
            bad.append(f"{qid}: summary.{credit}={s.get(credit)} ≠ 实计 {n}")
    if s.get("hit", 0) + s.get("miss", 0) + s.get("na", 0) != len(rows):
        bad.append(f"{qid}: hit+miss+na ≠ 点数（三态必须互斥且穷尽）")
    point_sum = round(sum(float(r.get("score") or 0) for r in rows), 6)
    if abs(float(s.get("score", 0)) - point_sum) > 1e-6:
        bad.append(f"{qid}: summary.score={s.get('score')} ≠ 点级求和 {point_sum}")
    table_sum = round(sum(table.values()), 6)
    if abs(float(s.get("score_total", 0)) - table_sum) > 1e-6:
        bad.append(f"{qid}: summary.score_total={s.get('score_total')} ≠ 总表 {table_sum}")
    judged_n = s.get("hit", 0) + s.get("miss", 0)
    if s.get("judged_rate") != f"{judged_n}/{len(rows)}":
        bad.append(f"{qid}: judged_rate 定义不符，应为 {judged_n}/{len(rows)}")
    want_hr = f"{s.get('hit', 0)}/{judged_n}" if judged_n else None
    if s.get("hit_rate") != want_hr:
        bad.append(f"{qid}: hit_rate 应为 {want_hr!r}（分母 = hit+miss）")

    nr = d.get("na_reasons") or {}
    if not isinstance(nr, dict):
        bad.append(f"{qid}: na_reasons 必须是对象")
    else:
        illegal = [k for k in nr if k not in NA_REASONS]
        if illegal:
            bad.append(f"{qid}: na_reasons 未知标签 {illegal}")
        if sum(nr.values()) != s.get("na", 0):
            bad.append(f"{qid}: na_reasons 合计 {sum(nr.values())} ≠ na {s.get('na')}")
    return bad, qid


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="T25 产物契约校验")
    ap.add_argument("products", nargs="+", help="产物 JSON（可用通配符展开）")
    ap.add_argument("--answers-dir", default=str(ANSWER_DIR))
    args = ap.parse_args(argv)

    paths = [Path(p) for p in args.products]
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        print(f"找不到产物：{missing}")
        return 1
    total_bad = 0
    for p in sorted(paths):
        bad, qid = check_one(p, Path(args.answers_dir))
        total_bad += len(bad)
        print(f"{p.name if p.name != qid else qid:>10}  "
              f"{'OK' if not bad else f'{len(bad)} 项违约'}")
        for b in bad:
            print(f"    - {b}")
    print(f"契约校验：{len(paths)} 份产物 / {total_bad} 项违约")
    return 1 if total_bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
