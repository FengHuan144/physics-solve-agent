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
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:            # 允许 `python 判分器/grader.py`
    sys.path.insert(0, str(ROOT))

from 验证器 import runner as R          # noqa: E402
from 判分器 import align as AL          # noqa: E402

XLSX_PATH = ROOT / "原始资料" / "五卷力学大题_采分点总表_v2.xlsx"
GOLD_DIR = ROOT / "schema" / "examples"
OUT_DIR = ROOT / "判分器" / "out"
DEFAULT_ANSWER_DIR = ROOT / "评测" / "T20" / "out"
DEFECTS_PATH = ROOT / "判分器" / "defects_v1.json"

QIDS = ("A-02", "A-08", "A-10", "B-02", "B-09", "B-12", "B-20")

# 阶段版本写进产物，用于区分「占位产物」与「真判产物」。contract 只校验该字段存在，
# **不校验 basis 与版本是否自洽**（那需要人看，见审核记录 R-3）。
GRADER_VERSION = "t25-s2"

# 金标可读字段白名单。``grading`` 不在其中——读它等于抄答案（卡 §2 陷阱 3）。
GOLD_READABLE_FIELDS = ("steps", "situation")

# ``na`` 的原因标签（T31 §3.1③ 六条 + §3.1④ 两条 + §3.2④ 一条 + 段1 实测补一条）
NA_REASONS = (
    "未实现",        # 该阶段尚未实现（段 1 之后不应再出现）
    "无候选步",      # 模型答案里找不到任何承载该点的步
    "白名单外符号",  # 步内符号不在知识表白名单，L1/L2 均不可判
    "merged分摊",    # 一步同时承载多个点，部分对无处分摊
    "无锚点",        # equation 与 value/criterion 双空，没有可判的锚
    "规范未过",      # 式子等价但结果规范（单位/方向/舍根）不达标
    "merged_step",   # 数据缺陷：金标/产物把多条等式焊成一条（T31 §3.1④）
    "field_mismatch",# 数据缺陷：equation 与 value.exact 互相矛盾（T31 §3.1④）
    "slot_collision",# 同一槽位在题内被赋 ≥2 个不同值，一律 na（T31 §3.2④）
    "欠定",          # 符号都在白名单，但方程欠定/无值可代，L1/L2 给不出 pass/fail
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


# --------------------------------------------------------------------------- 数据缺陷豁免

def load_defects(path: Path = DEFECTS_PATH) -> dict[tuple[str, str], dict]:
    """读**产物侧**缺陷表：``items``。``gold_items`` 不参与判分豁免（T31 §3.1④ 注）。"""
    if not path.exists():
        return {}
    d = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for it in d.get("items") or []:
        out[(str(it.get("qid")), str(it.get("step_id")))] = it
    return out


# --------------------------------------------------------------------------- 槽位碰撞

def _value_key(v: dict) -> str | None:
    if not v:
        return None
    if v.get("number") is not None:
        try:
            return f"{float(v['number']):.12g}|{(v.get('unit') or '').strip()}"
        except Exception:  # noqa: BLE001
            return f"{v['number']}|{(v.get('unit') or '').strip()}"
    if v.get("exact"):
        return str(v["exact"]).replace(" ", "")
    return None


def slot_collisions(doc: dict) -> dict[str, list[str]]:
    """``(qid, symbol)`` 在题内被赋 ≥2 个不同值 → 返回 ``{symbol: [值…]}``。

    槽位名取别名层改写后的 ``value.symbol``（``run_answer(alias=True)`` 的产物）。
    """
    vals: dict[str, list[str]] = defaultdict(list)
    for g in ((doc.get("situation") or {}).get("given") or []):
        k = _value_key({"number": g.get("value"), "unit": g.get("unit")})
        if g.get("symbol") and k:
            vals[str(g["symbol"])].append(k)
    for s in (doc.get("steps") or []):
        v = s.get("value") or {}
        k = _value_key(v)
        if v.get("symbol") and k:
            vals[str(v["symbol"])].append(k)
    return {sym: sorted(set(ks)) for sym, ks in vals.items() if len(set(ks)) >= 2}


def _uses_symbol(step: dict, sym: str) -> bool:
    if (step.get("value") or {}).get("symbol") == sym:
        return True
    eq = (step.get("equation") or {}).get("sympy") or ""
    return bool(re.search(rf"(?<![A-Za-z0-9_]){re.escape(sym)}(?![A-Za-z0-9_])", eq))


def _step_status(step: dict) -> tuple[str, dict | None]:
    """一步的 L1/L2 合成态：任一 fail → fail；全 pass → pass；否则 na。"""
    cs = step.get("checks") or []
    if any(c.get("status") == "fail" for c in cs):
        return "fail", next(c for c in cs if c.get("status") == "fail")
    if cs and all(c.get("status") == "pass" for c in cs):
        return "pass", None
    return "na", None


def _na_reason(steps: list[dict]) -> str:
    details = " ".join(
        str(c.get("detail") or "") for s in steps for c in (s.get("checks") or [])
        if c.get("status") == "na")
    if "不在白名单" in details or "unknown_symbol" in details:
        return "白名单外符号"
    if any(not ((s.get("equation") or {}).get("sympy")) and not (s.get("value"))
           for s in steps):
        return "无锚点"
    return "欠定"


# --------------------------------------------------------------------------- 无锚点的 2-gram 自检
#
# T34 §3.2：``na`` 点若 ``by`` 里的步既没有 ``equation.sympy``、又与采分点口径
# 说不上话，就不该保留一个指不出式子的步号——那是假装有归属。
#
# 「说不上话」用**口径被覆盖率**度量：``|口径2gram ∩ 步2gram| / |口径2gram|``。
# 不用 Jaccard：Jaccard 会惩罚「写得详细但切题」的步（步越长、并集越大、分越低），
# 而这里要问的是「这一步有没有对上口径的那句话」，不是「两步长得像不像」。
# 阈值 15% 由 T34 §3.2 给定，不是本次调出来的。

_NGRAM_STRIP = re.compile(r"[\s，。、；：？！“”‘’（）()《》【】,.;:?!%\-—_…·/×+*=<>≤≥≈＋－＝]+")


def _bigrams(text: str) -> set[str]:
    t = _NGRAM_STRIP.sub("", str(text or ""))
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) >= 2 else set()


def criterion_overlap(statement: str, criterion: str) -> float:
    """承载步 statement 覆盖了采分点口径多少 2-gram，0~1。"""
    b = _bigrams(criterion)
    if not b:
        return 0.0
    return len(_bigrams(statement) & b) / len(b)


def no_anchor_check(steps: list[dict], criterion: str) -> tuple[bool, str, float]:
    """``by`` 里**所有**步都无 ``equation.sympy``，且与口径的最大覆盖 < 15%。

    返回 ``(是否清空 by, 覆盖最高的步号, 该覆盖率)``。
    只要有一步有式子，就返回 ``False``——有式子锚点在，归属就不算空口。
    """
    if not steps:
        return False, "", 0.0
    if any(((s.get("equation") or {}).get("sympy")) for s in steps):
        return False, "", 0.0
    best_sid, best = "", 0.0
    for s in steps:
        cov = criterion_overlap(s.get("statement"), criterion)
        if cov > best:
            best_sid, best = str(s.get("step_id")), cov
    return best < 0.15, best_sid, best


# --------------------------------------------------------------------------- S2 credit

def credit_points(qid: str, points: list[dict], gold: dict, doc: dict,
                  defects: dict[tuple[str, str], dict] | None = None,
                  use_defects: bool = True) -> tuple[list[dict], Counter]:
    """按点出 ``hit/miss/na``。依据优先级（T31 §3.1）：

    1. 归属为空 → na/无候选步；槽位碰撞 → na/slot_collision
    2. 任一步 fail → miss（命中数据缺陷 → na + defect 标签）
    3. 全步 pass → hit
    4. 有方程且与金标同式（eqsim ≥ 0.9）→ hit
    5. 其余 → na（白名单外符号 / 无锚点 / 欠定）
    """
    defects = defects or {}
    by_pid = AL.map_steps(points, gold.get("steps") or [], doc.get("steps") or [])
    step_by_id = {str(s.get("step_id")): s for s in (doc.get("steps") or [])}
    gold_by_pid = {str(s["point_id"]): s for s in (gold.get("steps") or [])
                   if s.get("point_id")}
    collisions = slot_collisions(doc)

    rows: list[dict] = []
    reasons: Counter = Counter()

    def put(p, credit, score, by, basis, uncertain=False, reason=None):
        if credit == "na":
            reasons[reason or "欠定"] += 1
            rng = [0.0, float(p["score"])]
        elif credit == "hit":
            rng = [float(score), float(score)]
        else:  # miss：确定 0，区间闭合在 0
            rng = [0.0, 0.0]
        rows.append({
            "point_id": p["point_id"],
            "credit": credit,
            "score": float(score),
            "score_range": rng,
            "by": list(by),
            "basis": basis,
            "uncertain": bool(uncertain),
        })

    for p in points:
        pid = str(p["point_id"])
        by = by_pid.get(pid, [])
        steps = [step_by_id[s] for s in by if s in step_by_id]
        if not by or not steps:
            put(p, "na", 0, [], "无候选步：对齐后没有模型步承载该点", True,
                reason="无候选步")
            continue

        sts = [_step_status(s) for s in steps]
        fails = [(s, c) for s, (st, c) in zip(steps, sts) if st == "fail"]

        # 数据缺陷优先于槽位碰撞：缺陷步本来就该 na，标签要能指向根因（T31 闸 5）。
        if fails and use_defects:
            defect = None
            for s, _c in fails:
                d = defects.get((qid, str(s.get("step_id"))))
                if d:
                    defect = (s, d)
                    break
            if defect:
                s, d = defect
                kind = str(d.get("kind") or "merged_step")
                tag = {"no_slot": "白名单外符号"}.get(kind, kind)
                put(p, "na", 0, by,
                    f"{tag}：{s.get('step_id')} 命中数据缺陷——{str(d.get('should_be') or '')[:70]}",
                    True, reason=tag)
                continue

        hit_syms = sorted({sym for sym in collisions if any(_uses_symbol(s, sym) for s in steps)})
        if hit_syms:
            put(p, "na", 0, by,
                f"slot_collision：槽位 {'、'.join(hit_syms)} 在题内被赋 "
                f"{len(collisions[hit_syms[0]])} 个不同值", True,
                reason="slot_collision")
            continue

        if fails:
            s, c = fails[0]
            put(p, "miss", 0, by,
                f"{s.get('step_id')}：{c.get('layer')} fail——{str(c.get('detail') or '')[:80]}")
            continue

        if all(st == "pass" for st, _c in sts):
            eq = (steps[0].get("equation") or {}).get("sympy") or "—"
            put(p, "hit", p["score"], by,
                f"L1/L2 全 pass：{'、'.join(by)}；方程 {eq}"[:160])
            continue

        gold_eq = (gold_by_pid.get(pid, {}).get("equation") or {}).get("sympy")
        sims = [AL.eqsim(gold_eq, (s.get("equation") or {}).get("sympy")) for s in steps]
        # 段1 只认**完全同式**（eqsim=1.0）；差常数因子的 0.9 留给段2 判等价——
        # A-02-S02 就是 0.9 的假命中：分离时刻的动量式与最大压缩式恰好差 2 倍，
        # 是本题速度取值造成的，不是同一个物理陈述（T25 §4.2）。
        if gold_eq and sims and all(x >= 0.999 for x in sims):
            eq = (steps[0].get("equation") or {}).get("sympy") or "—"
            put(p, "hit", p["score"], by,
                f"方程与采分点完全同式（eqsim=1.0）：{eq}"[:160])
            continue

        reason = _na_reason(steps)
        # 只在「by 全步都没有 equation.sympy」时套 §3.2。混着有式子步的 na 点
        # （如 A-02-S04 的 by 含 S05 有方程）不能说「无式子可复核」，保持原 basis。
        if reason == "无锚点" and not any(
                ((s.get("equation") or {}).get("sympy")) for s in steps):
            # T34 §3.2：无式子锚点的点，要么老实说「全题没有一步对得上」（by 置空），
            # 要么保留步号但把 basis 改成引口径原句。诚实化，不改 credit、不改分母。
            empty, best_sid, cov = no_anchor_check(steps, p["criterion"])
            if empty:
                put(p, "na", 0, [],
                    f"无锚点：全题 {len(doc.get('steps') or [])} 步无一步有式子锚点"
                    f"或与口径对得上（已逐题检索）", True, reason="无锚点")
                continue
            sid = best_sid or (by[0] if by else "—")
            stmt = str(step_by_id.get(sid, {}).get("statement") or "").strip()
            put(p, "na", 0, by,
                f"无锚点：口径要求『{p['criterion'][:60]}』，承载步 {sid} 的 statement "
                f"写『{stmt[:60]}』，无式子可复核（2-gram 覆盖 {cov:.0%}）"[:220],
                True, reason="无锚点")
            continue

        put(p, "na", 0, by,
            f"{reason}：{'、'.join(by)} 的 L1/L2 未给出 pass/fail", True, reason=reason)

    return rows, reasons


def build_product(qid: str, mode: str, points: list[dict], gold: dict, doc: dict,
                  defects: dict | None = None, use_defects: bool = True) -> dict:
    """S2：credit 三态 + ``by`` + ``na_reasons``。"""
    rows, reasons = credit_points(qid, points, gold, doc, defects, use_defects)
    return {
        "qid": qid,
        "mode": mode,
        "grader_version": GRADER_VERSION,
        "points": rows,
        "summary": summarize(rows, points),
        "na_reasons": dict(reasons),
    }



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


def grade(answer_path: Path, out_path: Path | None = None,
          use_defects: bool = True) -> dict:
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
    doc, _report = R.run_answer(answer, alias=True, alias_qid=qid)

    product = build_product(qid, mode, points, gold, doc,
                            defects=load_defects(), use_defects=use_defects)
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
    ap.add_argument("--no-defects", action="store_true",
                    help="忽略缺陷豁免（闸 6：pass 数必须不变）")
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
            prod = grade(p, out_dir / f"{qid}.json", use_defects=not args.no_defects)
            print(_summary_line(prod))
        return 1 if bad else 0

    if not args.answer:
        ap.error("要么给 --answer，要么给 --all")
    p = Path(args.answer)
    out = Path(args.out) if args.out else OUT_DIR / f"{p.stem}.json"
    prod = grade(p, out, use_defects=not args.no_defects)
    print(_summary_line(prod))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
