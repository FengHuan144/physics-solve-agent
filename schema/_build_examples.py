#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 schema/examples/ 的 27 份真题样例（T08b 起；T08f 补齐余下 20 题后全量为 27）。

设计原则
--------
1. **只写 examples/**：本脚本不碰 `answer.schema.json`、校验器、原型。
2. **不编数据**：题干、已知量、小问、答案一律取自 `采分点/题干原文/*.md`；
   `point_id` 取自 xlsx 采分点总表。
3. **L1 不是手写的**：方程步由 sympy 代入数值现算残差；判据步（criterion）
   代入 expr 与 expected 判 comparator，算不平直接抛异常、不写盘。
4. **L2 手写**：量纲由人看，脚本不假装能证。

T08d（Schema 1.2，2026-11-25）
-----------------------------
四件事一次改完，**必须全量重生成**（不许分批，否则会出现半新半旧的样例）：

  ① 图读数进 `figures[].provides` + `question.input_sha256`；
     `given[].source="figure"` 标来源（B-20 三条读数、A-02 三个图读数）。
  ② 整题层 `validation.layers` 由步级反推（fail > na > pass），不再写死 pass。
     B-09 有 1 步、B-12 有 2 步 L1 为 na，所以这两题整题 L1 由 pass 变 na —— 是纠正。
  ③ `process_segments[].segment_id` + `boundary_reference`，`steps[].segment_id` 指向分段。
  ④ `equation` 可空 + 新增 `criterion`：判断步/临界步 equation=null，判据搬进 criterion。
     13 步迁 criterion（11 judgment + 2 critical），11 步 kind 改 value。

T08e（Schema 1.2.1，2026-11-25）
-------------------------------
补一个「图文件不受任何指纹保护」的洞：`figures[].file` + `figures[].file_sha256`。
**哈希由本脚本读磁盘字节现算**（见 `attach_figure_files`），不许手抄；本卡只读图，
不复制、不移动、不改名任何图文件。图哈希是独立字段，**不并进 input_sha256** ——
并进去会让 7 份样例的输入指纹全变，与 stem_sha256 打架。

T08f（2026-11-25）
---------------
补齐余下 20 题（A-01/A-03/A-04/A-05/A-06/A-09/B-01/B-03/B-04/B-05/B-06/B-07/B-08/
B-10/B-13/B-15/B-16/B-17/B-18/B-19），全量 27 份 / 223 步 / 344 分。三处配套改动：
  ① `build()` 的 point_hits 透传 `note`（原写死空串），合步留痕用；
  ② 符号白名单新登记 Uvolt / Icur / Rr（B-10 电动机），见 `知识表/符号白名单_v1.csv`；
  ③ 默认列表改为 27 题全量，分批时显式给名字。

用法
----
    python schema/_build_examples.py              # 全量 27 份
    python schema/_build_examples.py b02 a10      # 只生成指定几份
"""

import hashlib
import json
import os
import sys

from sympy import Rational, Symbol, sympify

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
OUT_DIR = os.path.join(BASE, "examples")

# 1.2.1：图文件 —— 本卡只读。键 = (题号, fig_no)，值是相对工作区根的路径（正斜杠）。
# 文件名的「图」字是真实存在的（B-20_图乙.png），不要改成 _2.png，也不要复制一份出来：
# 原型侧 _build.py 的 FIG_ALIAS 已把「甲乙丙丁」映射到 fig_no，改代码不改资产。
FIG_FILES = {
    ("A-02", 2): "原始资料/题图/A-02_图2.png",
    ("B-09", 1): "原始资料/题图/B-09_图1.png",
    ("B-20", 1): "原始资料/题图/B-20_图甲.png",
    ("B-20", 2): "原始资料/题图/B-20_图乙.png",
}


def attach_figure_files(cfg):
    """给每张图填 file / file_sha256；没有图文件的填双 null（R16 要求成对）。

    哈希必须现算：手抄的值下次就是假值，而 R17 会在磁盘上重算比对。
    """
    qid = cfg["meta"]["question_id"]
    for fig in cfg["question"]["figures"]:
        rel = FIG_FILES.get((qid, fig["fig_no"]))
        if rel is None:
            fig["file"] = None
            fig["file_sha256"] = None
            continue
        abspath = os.path.join(ROOT, rel)
        if not os.path.isfile(abspath):
            raise SystemExit("图文件不存在：%s（%s 图 %d）" % (rel, qid, fig["fig_no"]))
        with open(abspath, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        fig["file"] = rel
        fig["file_sha256"] = digest


# ---------------------------------------------------------------- 通用装配

def _canon_num(v):
    """数值规范化。必须与 validate_schema.py 的同名函数逐字一致。"""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return "%.17g" % float(v)
    return str(v)


def canonical_provides(question):
    """figures[].provides 的规范化串。必须与 validate_schema.py 逐字一致。"""
    rows = []
    for fig in question.get("figures") or []:
        fno = fig.get("fig_no")
        fno = int(fno) if isinstance(fno, int) else 0
        for p in fig.get("provides") or []:
            rows.append((fno, str(p.get("symbol", "")), _canon_num(p.get("value")),
                         str(p.get("unit", "")), str(p.get("read_from", "")),
                         str(p.get("text", ""))))
    rows.sort()
    return "\n".join("|".join(str(x) for x in r) for r in rows)


def input_sha256(question):
    payload = question.get("stem_text", "") + "\n\n#provides\n" + canonical_provides(question)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _l1_of_criterion(crit, nums, pid):
    """判据步的 L1：把 criterion 的 expr 与 expected 都代入数值，按 comparator 判。

    与方程步的区别只在语义：这里算的是「判据成立吗」，不是「方程残差为零」。
    qualitative / expected=null / 有符号无数值 → na，不许硬凑 pass。
    """
    cmp_ = crit["comparator"]
    exp = crit["expected"]
    if cmp_ == "qualitative" or exp is None:
        return ("na", "定性判据（comparator=qualitative），无数值可回代")
    delta = sympify(crit["expr"]) - sympify(exp)
    free = {str(x) for x in delta.free_symbols}
    missing = [x for x in free if x not in nums]
    if missing:
        return ("na", "判据含无给定数值的符号 %s，无法数值回代（只做量纲与符号闭合）"
                % "、".join(sorted(missing)))
    val = float(delta.subs({Symbol(k): v for k, v in nums.items()}))
    ok = {"eq": abs(val) <= 1e-9, "ne": abs(val) > 1e-9,
          "gt": val > 0, "ge": val >= -1e-9,
          "lt": val < 0, "le": val <= 1e-9}[cmp_]
    assert ok, "%s 判据不成立：%s %s %s（差值 %.6g）" % (pid, crit["expr"], cmp_, exp, val)
    sub = "、".join("%s=%g" % (k, nums[k]) for k in sorted(free))
    tail = "，差值 0" if cmp_ == "eq" else "，差值 %g" % val
    return ("pass", "判据回代成立（%s%s）" % (sub, tail))


# ---------------------------------------------------------------- 过程分段（1.2 缺陷 ③）
# refs 按 no 升序与 process_segments 一一对应：(segment_id, boundary_reference)
# map 按 steps 顺序一一对应：步 → segment_id，None 表示跨段、不归属（Schema 里该字段可选）

SEGMENTS = {
    "A-08": {
        "refs": [
            ("SEG-01", "以圆轨道顶端由静止释放为起点、底端 P 点切线水平为终点；重力势能以地面为零点"),
            ("SEG-02", "以过 P 点瞬间为起点、到达 M 点为终点；位移沿 P→M 取正"),
            ("SEG-03", "以碰前瞬间为起点、碰后瞬间为终点；碰撞时间极短按零计，位置取 M 点"),
            ("SEG-04", "以 b 进入 M 点为起点、到达 N 点为终点；速度参照系取传送带上表面（向左 1 m/s）"),
            ("SEG-05", "以 b 在 N 点受第一次冲量为起点、离开 M 点为终点；每次冲量按瞬时计，时间零点取第一次冲量"),
        ],
        "map": ["SEG-01", "SEG-01", "SEG-01", "SEG-02", "SEG-03",
                "SEG-04", "SEG-04", "SEG-05", "SEG-05", "SEG-05", "SEG-05"],
    },
    "B-12": {
        "refs": [
            ("SEG-01", "以初始静止为界；两者加速度均为零，支持力作用面为桌面"),
            ("SEG-02", "以滑块离开 A 点为起点、到达 B 点为终点；位移沿杆向上为正"),
            ("SEG-03", "以滑块到达 B 点的瞬间为起止；碰前后速度均沿杆向上为正"),
            ("SEG-04", "以碰后共同速度为初态、最高点速度为零为末态；桌面为 h＝0 的参考"),
        ],
        "map": ["SEG-01", "SEG-01", "SEG-02", "SEG-02", "SEG-02",
                "SEG-02", "SEG-03", "SEG-04", "SEG-04"],
    },
    "B-09": {
        "refs": [
            ("SEG-01", "以甲被拨出处为起点、乙所在处为终点；位移沿拨出方向为正"),
            ("SEG-02", "以两珠接触的瞬间为起止；碰撞时间不计，位置取乙的初始位置"),
            ("SEG-03", "以碰后瞬间为起点、边框 a 为位移终点；s 从碰后位置起算"),
            ("SEG-04", "以碰后瞬间为起点、甲停下为终点；与第 1 段共用同一计时起点"),
        ],
        "map": ["SEG-01", "SEG-01", "SEG-02", "SEG-03", None, "SEG-01", None],
    },
    "B-02": {
        "refs": [
            ("SEG-01", "以地面抛出点为起点、最高点速度为零为终点；竖直向上为正"),
            ("SEG-02", "以最高点炸裂的瞬间为起止；竖直分速度为零，水平方向动量为零"),
            ("SEG-03", "以炸裂点为起点、落地点为终点；下落时间与上升时间同为 t"),
        ],
        "map": ["SEG-01", "SEG-02", "SEG-02", None, "SEG-03", "SEG-03"],
    },
    "A-10": {
        "refs": [
            ("SEG-01", "以星系中心为原点、r 从 R 起算（只取 r>R）；只用向心力式，不设势能零点"),
            ("SEG-02", "以星系中心为原点、r 从 0 起算（只取 r≤R）；球内质量按半径 r 的球体计"),
            ("SEG-03", "以 r＝R 处的速率 v₀ 为同一参照；n>1，nR 处含暗物质"),
        ],
        "map": ["SEG-01", "SEG-01", "SEG-02", "SEG-02", "SEG-02",
                "SEG-03", "SEG-03", "SEG-03"],
    },
    "B-20": {
        "refs": [
            ("SEG-01", "第 (1) 问独立情境：轨道固定；Q 点速度沿水平方向，重力势能以水平段为 0"),
            ("SEG-02", "以物块静置于轨道最左端为起点、物块到达 P 点为终点；水平向左为正"),
            ("SEG-03", "以撤去 F 的瞬间为起点、物块经过 Q 点为终点；水平方向动量守恒"),
            ("SEG-04", "以物块经过 Q 点为起点、离开轨道为终点；速度取相对地面"),
        ],
        "map": ["SEG-01", "SEG-01", "SEG-01", "SEG-02", "SEG-02",
                "SEG-02", "SEG-02", "SEG-02", "SEG-03", "SEG-03"],
    },
    "A-02": {
        "refs": [
            ("SEG-01", "以 t＝0 两物块接触为起点、t＝t₀ 共速（压缩量最大）为终点；水平面为势能零点"),
            ("SEG-02", "以 t＝t₀ 共速为起点、t＝2t₀ 弹簧恢复原长为终点"),
            ("SEG-03", "以斜面底端为起点、最高点速度为零为终点；重力势能以水平面为 0"),
            ("SEG-04", "以最高点为起点、回到水平面为终点；与第 3 段共用同一零势能面"),
            ("SEG-05", "以第二次碰撞的瞬间为起点、再次到达与前次相同的最高点为终点"),
        ],
        "map": ["SEG-01", "SEG-01", "SEG-01", "SEG-01", "SEG-01",
                "SEG-01", "SEG-01", "SEG-01", "SEG-05", "SEG-05",
                "SEG-05", "SEG-05", "SEG-03", "SEG-04", None],
    },
}


def _tag_segments(cfg):
    """把 SEGMENTS 里的 segment_id / boundary_reference / 步归属写进 cfg。"""
    spec = SEGMENTS.get(cfg["meta"]["answer_id"])
    if not spec:
        return
    segs = sorted(cfg["situation"]["process_segments"], key=lambda x: x["no"])
    assert len(segs) == len(spec["refs"]), \
        "%s 过程分段 %d 条，refs %d 条" % (cfg["meta"]["answer_id"], len(segs), len(spec["refs"]))
    for seg, (sid, ref) in zip(segs, spec["refs"]):
        seg["segment_id"] = sid
        seg["boundary_reference"] = ref
    assert len(spec["map"]) == len(cfg["steps"]), \
        "%s 步数 %d，map %d 条" % (cfg["meta"]["answer_id"], len(cfg["steps"]), len(spec["map"]))
    for st, sid in zip(cfg["steps"], spec["map"]):
        if sid:
            st["seg"] = sid


def build(cfg):
    """cfg: meta/question/situation/outline 由各题填，steps 由 make_steps 生成。"""
    _tag_segments(cfg)
    attach_figure_files(cfg)
    steps, hits = [], []
    nums = cfg["nums"]
    for i, s in enumerate(cfg["steps"], start=1):
        crit = s.get("crit")
        if crit is None:
            expr = sympify(s["sympy"])
            free = {str(x) for x in expr.free_symbols}
            assert free <= set(cfg["allowed_symbols"]), \
                "%s 用了未声明的符号 %s" % (s["pid"], free - set(cfg["allowed_symbols"]))

            # L1：只有在所有自由符号都有数值时才回代
            l1 = None
            missing = [x for x in free if x not in nums]
            if not missing:
                val = expr.subs({Symbol(k): v for k, v in nums.items()})
                assert abs(float(val)) < 1e-9, \
                    "%s 回代残差 %.6g ≠ 0（%s）" % (s["pid"], float(val), s["sympy"])
                sub = "、".join("%s=%g" % (k, nums[k]) for k in sorted(free))
                l1 = ("pass", "回代残差 0（%s）" % sub)
            else:
                l1 = ("na", "全符号题：%s 无给定数值，无法数值回代（只做量纲与符号闭合）"
                      % "、".join(sorted(missing)))
            equation = {"latex": s["latex"], "sympy": s["sympy"],
                        "symbols": sorted(free), "parse_status": "ok"}
        else:
            equation = None
            l1 = _l1_of_criterion(crit, nums, s["pid"])

        checks = [{"layer": "L1", "status": l1[0], "detail": l1[1], "error_code": None},
                  {"layer": "L2", "status": "pass", "detail": s["l2"], "error_code": None}]
        if s.get("l4"):
            checks.append({"layer": "L4", "status": "pass", "detail": s["l4"], "error_code": None})
        if s.get("l4na"):
            checks.append({"layer": "L4", "status": "na", "detail": s["l4na"], "error_code": None})

        step = {
            "step_id": s["pid"], "step_no": i, "title": s["title"],
            "point_id": s["pid"], "kind": s["kind"], "statement": s["stmt"],
            "equation": equation,
        }
        if crit is not None:
            step["criterion"] = crit
        if s.get("seg"):
            step["segment_id"] = s["seg"]
        step.update({
            "value": s.get("val"),
            "law_ids": s["laws"], "checks": checks,
            "confidence": s.get("conf", 5), "status": "checked",
        })
        steps.append(step)
        hits.append({"point_id": s["pid"], "step_id": s["pid"],
                     "score_awarded": s["score"], "score_possible": s["score"],
                     "hit": True, "note": s.get("note", "")})

    awarded = sum(h["score_awarded"] for h in hits)
    assert abs(awarded - cfg["meta"]["full_score"]) < 1e-9, \
        "采分点合计 %g ≠ 卷面分 %g" % (awarded, cfg["meta"]["full_score"])
    sub_sum = sum(q["score"] for q in cfg["question"]["subquestions"])
    assert abs(sub_sum - cfg["meta"]["full_score"]) < 1e-9, \
        "小问分值合计 %g ≠ 卷面分 %g" % (sub_sum, cfg["meta"]["full_score"])

    cfg["question"]["stem_sha256"] = hashlib.sha256(
        cfg["question"]["stem_text"].encode("utf-8")).hexdigest()
    # 1.2：图读数进指纹。没有 provides 时这一段只由题干决定，与 stem_sha256 等价但多一层分隔，
    # 不追求两者相等 —— 两个指纹各管一段，并存不是冗余。
    cfg["question"]["input_sha256"] = input_sha256(cfg["question"])

    # 整题层状态由步级 checks 反推，不写死：全符号题 L1 全 na 时不能谎报 pass。
    # fail 优先；有任何 na 就记 na（部分可验 ≠ 全验）；全 pass 才 pass。
    layers = {}
    for lay in ("L1", "L2", "L4"):
        sts = [c["status"] for s in steps for c in s["checks"] if c["layer"] == lay]
        if not sts:
            layers[lay] = "na"
        elif "fail" in sts:
            layers[lay] = "fail"
        elif "na" in sts:
            layers[lay] = "na"
        else:
            layers[lay] = "pass"

    doc = {
        "schema_version": "1.2.1",
        "meta": cfg["meta"],
        "question": cfg["question"],
        "situation": cfg["situation"],
        "outline": [{"step_no": i, "title": s["title"],
                     "depends_on": s.get("deps", [] if i == 1 else [i - 1]),
                     "expanded": True, "point_hint": s["pid"]}
                    for i, s in enumerate(cfg["steps"], start=1)],
        "steps": steps,
        "grading": {"point_hits": hits, "missing_points": [], "extra_steps": [],
                    "score_awarded": awarded, "score_total": cfg["meta"]["full_score"],
                    "weighted_rate": 1.0},
        "validation": {"layers": {"L1": layers["L1"], "L2": layers["L2"], "L3": "na",
                                  "L4": layers["L4"]},
                       "failures": [], "zero_point_hit": False, "rewrite_rounds": 0},
        "triage": {"level": "green",
                   "signals": {"hard_check": "pass", "question_type_prior": cfg["prior"],
                               "self_rank": None, "rework_rate": None},
                   "reason": cfg["reason"]},
        "review": {"verdict": "pending", "rejected_steps": [], "reason_codes": [],
                   "diffs": [], "added_steps": [], "reordered": False},
    }
    path = os.path.join(OUT_DIR, cfg["meta"]["question_id"] + ".json")
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("写出 %s（%d 步 / %g 分）" % (os.path.basename(path), len(steps), awarded))


# ---------------------------------------------------------------- A-08

def a08():
    stem = ("如图，半径为 R＝1.8 m 的四分之一光滑圆轨道固定在竖直平面内，其末端与水平地面 PM 相切于 P 点，"
            "PM 的长度 d＝2.7 m。一长为 L＝3.3 m 的水平传送带以恒定速率 v₀＝1 m/s 逆时针转动，其右端与地面在 M 点无缝对接。"
            "物块 a 从圆轨道顶端由静止释放，沿轨道下滑至 P 点，再向左做直线运动至 M 点与静止的物块 b 发生弹性正碰，"
            "碰撞时间极短。碰撞后 b 向左运动到达传送带的左端 N 时，瞬间给 b 一水平向右的冲量 I，其大小为 6 N·s。"
            "以后每隔 Δt＝0.6 s 给 b 一相同的瞬时冲量 I，直到 b 离开传送带。已知 a 的质量为 mₐ＝1 kg，b 的质量为 m_b＝2 kg，"
            "它们均可视为质点。a、b 与地面及传送带间的动摩擦因数均为 μ＝0.5，取重力加速度大小 g＝10 m/s²。求："
            "(1)a 运动到圆轨道底端时轨道对它的支持力大小；"
            "(2)b 从 M 运动到 N 的时间；"
            "(3)b 从 N 运动到 M 的过程中与传送带摩擦产生的热量。")
    cfg = {
        "meta": {"answer_id": "A-08", "question_id": "A-08", "group": "A",
                 "source": "2024 贵州卷", "question_no": 15, "full_score": 19,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T11:30:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [{"fig_no": 1,
                         "caption": "四分之一圆轨道（半径 R）与水平地面相切于 P、PM 段、传送带 MN；原文无图题",
                         "caption_source": "none", "is_required": False}],
            "subquestions": [
                {"no": "(1)", "text": "a 运动到圆轨道底端时轨道对它的支持力大小。", "score": 5},
                {"no": "(2)", "text": "b 从 M 运动到 N 的时间。", "score": 6},
                {"no": "(3)", "text": "b 从 N 运动到 M 的过程中与传送带摩擦产生的热量。", "score": 8},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "物块 a", "mass_symbol": "m1", "note": "从圆轨道顶端静止释放，视为质点，质量 1 kg"},
                {"id": "obj2", "name": "物块 b", "mass_symbol": "m2", "note": "原静止于 M 点，视为质点，质量 2 kg"},
                {"id": "obj3", "name": "传送带", "mass_symbol": "Mbelt", "note": "长 3.3 m，以 1 m/s 逆时针（上表面向左）匀速转动"},
            ],
            "given": [
                {"symbol": "R", "value": 1.8, "unit": "m", "text": "半径为 R＝1.8 m 的四分之一光滑圆轨道"},
                {"symbol": "d", "value": 2.7, "unit": "m", "text": "PM 的长度 d＝2.7 m"},
                {"symbol": "L", "value": 3.3, "unit": "m", "text": "一长为 L＝3.3 m 的水平传送带"},
                {"symbol": "v0", "value": 1, "unit": "m/s", "text": "以恒定速率 v₀＝1 m/s 逆时针转动"},
                {"symbol": "Iimp", "value": 6, "unit": "N*s", "text": "冲量 I，其大小为 6 N·s"},
                {"symbol": "dt", "value": 0.6, "unit": "s", "text": "以后每隔 Δt＝0.6 s 给 b 一相同的瞬时冲量"},
                {"symbol": "m1", "value": 1, "unit": "kg", "text": "a 的质量为 mₐ＝1 kg"},
                {"symbol": "m2", "value": 2, "unit": "kg", "text": "b 的质量为 m_b＝2 kg"},
                {"symbol": "mu", "value": 0.5, "unit": "1", "text": "a、b 与地面及传送带间的动摩擦因数均为 μ＝0.5"},
                {"symbol": "g", "value": 10, "unit": "m/s^2", "text": "取重力加速度大小 g＝10 m/s²"},
            ],
            "process_segments": [
                {"no": 1, "name": "a 沿圆轨道下滑", "start": "a 从圆轨道顶端静止释放", "end": "a 到达底端 P"},
                {"no": 2, "name": "a 在 PM 段减速", "start": "a 经过 P 向左运动", "end": "a 到达 M（速度 3 m/s）"},
                {"no": 3, "name": "弹性正碰", "start": "a 与静止的 b 在 M 相碰", "end": "碰后 a 反弹、b 向左以 2 m/s 运动"},
                {"no": 4, "name": "b 在传送带上减速后随带匀速", "start": "b 由 M 向左进入传送带", "end": "b 到达 N（先减速到 1 m/s，再匀速）"},
                {"no": 5, "name": "b 受周期冲量往返", "start": "b 在 N 受向右冲量", "end": "b 由 N 回到 M 并离开传送带"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "Nf", "text": "圆轨道底端轨道对 a 的支持力"},
                {"no": "(2)", "quantity": "t", "text": "b 从 M 到 N 的时间"},
                {"no": "(3)", "quantity": "Qheat", "text": "b 从 N 到 M 与传送带摩擦产生的热量"},
            ],
            "assumptions": [
                "圆轨道光滑，a 下滑过程只有重力做功",
                "a、b 均可视为质点，碰撞为一维弹性正碰且时间极短，碰中动量与动能同时守恒",
                "传送带上表面因逆时针转动而向左运动，速率恒为 1 m/s",
                "水平向左取负方向，向右为正方向（与题目「向左运动」叙述一致）",
            ],
        },
        "nums": {"R": 1.8, "d": 2.7, "L": 3.3, "v0": 1.0, "Iimp": 6.0, "dt": 0.6,
                 "m1": 1.0, "m2": 2.0, "mu": 0.5, "g": 10.0,
                 "v1": 6.0, "v2": 3.0, "v2p": 2.0, "Nf": 30.0, "a1": 5.0, "a2": 5.0,
                 "s1": 0.3, "t": 3.2, "v2b": 2.0, "ds": 9.5, "Qheat": 95.0},
        "allowed_symbols": ["R", "d", "L", "v0", "Iimp", "dt", "m1", "m2", "mu", "g",
                            "v1", "v2", "v2p", "Nf", "a1", "a2", "s1", "t", "v2b", "ds", "Qheat"],
        "prior": "high",
        "reason": "金标参考解：四过程 + 周期冲量，L1 逐式数值回代、L2 量纲全过，19/19 满分，未触归零点",
        "steps": [
            dict(pid="A-08-S01", title="圆轨道下滑机械能守恒求 v1", kind="equation", score=2,
                 stmt="四分之一圆弧半径 R＝1.8 m，a 从顶端静止滑到底端，只有重力做功：m₁gR＝½m₁v₁²，得 v₁＝6 m/s。",
                 latex="m_{1} g R = \\frac{1}{2} m_{1} v_{1}^{2}",
                 sympy="m1*g*R - Rational(1,2)*m1*v1**2",
                 l2="两边均为 J（kg·m²/s²）",
                 l4="圆轨道光滑，无摩擦项；正压力全程不做功，故不出现",
                 val={"symbol": "v1", "number": 6.0, "exact": "sqrt(2*g*R)", "unit": "m/s",
                      "direction": None, "sig_figs": 1},
                 laws=["L-09"]),
            dict(pid="A-08-S02", title="底端沿半径方向列向心力方程", kind="equation", score=2,
                 stmt="在最低点 P，支持力与重力的合力提供向心力：N－m₁g＝m₁v₁²/R。",
                 latex="N_{f} - m_{1} g = m_{1} \\frac{v_{1}^{2}}{R}",
                 sympy="Nf - m1*g - m1*v1**2/R",
                 l2="N 与 mg 为 N，右边 kg·(m/s)²/m＝N",
                 l4="圆心在 P 正上方，向心方向为竖直向上，故 N 取正、mg 取负",
                 laws=["L-06"]),
            dict(pid="A-08-S03", title="解出支持力 Nf=30 N", kind="value", score=1,
                 stmt="代入 v₁＝6 m/s、R＝1.8 m 得 N＝1×10＋1×36/1.8＝30 N；由牛顿第三定律，a 对轨道的压力同为 30 N。",
                 latex="N_{f} = 30",
                 sympy="Nf - 30",
                 l2="N（kg·m/s²）",
                 val={"symbol": "Nf", "number": 30.0, "exact": "m1*g + m1*v1^2/R", "unit": "N",
                      "direction": "+y", "sig_figs": 2},
                 laws=["L-06"]),
            dict(pid="A-08-S04", title="PM 段匀减速求碰前速度 v2", kind="equation", score=2,
                 stmt="a 在 PM 段只受摩擦力，a₁＝μg＝5 m/s²；由 v₂²＝v₁²－2a₁d 得 v₂＝3 m/s。",
                 latex="v_{2}^{2} - v_{1}^{2} + 2 a_{1} d = 0",
                 sympy="v2**2 - v1**2 + 2*a1*d",
                 l2="各项均为 m²/s²",
                 l4="减速度取正、加号在式子中体现为 +2a₁d（移项后变号），方向沿 PM 指向 M",
                 val={"symbol": "v2", "number": 3.0, "exact": "sqrt(v1^2 - 2*mu*g*d)", "unit": "m/s",
                      "direction": "-x", "sig_figs": 1},
                 laws=["L-01", "L-05", "L-04"]),
            dict(pid="A-08-S05", title="弹性正碰求 b 碰后速度", kind="equation", score=2,
                 stmt="一维弹性正碰、b 原静止：v_b′＝2m₁v₂/(m₁＋m₂)＝2×1×3/3＝2 m/s（向左）；a 反弹为 1 m/s。",
                 latex="v_{2p} = \\frac{2 m_{1} v_{2}}{m_{1} + m_{2}}",
                 sympy="v2p - 2*m1*v2/(m1+m2)",
                 l2="m/s",
                 l4="一动一静弹性碰撞的碰后速度式；只对 b 应用，a 的碰后速度另行给出但非本步采分点",
                 val={"symbol": "v2p", "number": 2.0, "exact": "2*m1*v2/(m1+m2)", "unit": "m/s",
                      "direction": "-x", "sig_figs": 1},
                 laws=["L-12"]),
            dict(pid="A-08-S06", title="判定 b 在带上先减速、加速度大小", kind="value", score=1,
                 stmt="b 以 2 m/s 向左进入向左 1 m/s 的传送带，相对带向左运动，摩擦力向右，a_b＝μg＝5 m/s²，故 b 先减速到与带共速 1 m/s。",
                 latex="a_{2} = \\mu g",
                 sympy="a2 - mu*g",
                 l2="m/s²",
                 val={"symbol": "a2", "number": 5.0, "exact": "mu*g", "unit": "m/s^2",
                      "direction": None, "sig_figs": 1},
                 l4="摩擦力方向按「阻碍相对运动」判定：b 相对带向左 → 摩擦力向右；带速向左不等于 b 与带同向运动",
                 laws=["L-05", "L-04"]),
            dict(pid="A-08-S07", title="分段求 b 由 M 到 N 的时间", kind="value", score=1,
                 stmt="减速段 t₁＝(2−1)/5＝0.2 s、位移 s₁＝0.3 m；随带匀速段 t₂＝(3.3−0.3)/1＝3.0 s；合计 t＝3.2 s。",
                 latex="t = \\frac{v_{2p} - v_{0}}{a_{2}} + \\frac{L - s_{1}}{v_{0}}",
                 sympy="t - (v2p-v0)/a2 - (L - (v2p**2-v0**2)/(2*a2))/v0",
                 l2="s",
                 l4="两段不能合并成一段匀变速：第二段与带共速后不再受摩擦，加速度为 0",
                 val={"symbol": "t", "number": 3.2, "exact": "1/5 + 3", "unit": "s",
                      "direction": None, "sig_figs": 2},
                 laws=["L-01", "L-05"]),
            dict(pid="A-08-S08", title="判定冲量后 b 的速度方向与大小", kind="value", score=2,
                 stmt="冲量使 b 获得 Δv＝I/m₂＝3 m/s 向右，而 b 此时正以 1 m/s 随带向左运动，故冲量后速度为 2 m/s 向右（不是 3 m/s）。",
                 latex="v_{2b} = \\frac{I}{m_{2}} - v_{0}",
                 sympy="v2b - (Iimp/m2 - v0)",
                 l2="N·s/kg＝m/s",
                 l4="冲量改变的是动量增量，必须叠加冲量前的速度；直接把 Δv 当末速度是本题最大失分点",
                 val={"symbol": "v2b", "number": 2.0, "exact": "I/m2 - v0", "unit": "m/s",
                      "direction": "+x", "sig_figs": 1},
                 laws=["L-11"]),
            dict(pid="A-08-S09", title="求单个冲量周期的时间与相对速度", kind="equation", score=2,
                 stmt="冲量后 b 相对带 3 m/s 向右，摩擦力向左、a＝5 m/s²，经 Δt′＝3/5＝0.6 s 恰好与带共速——与冲量间隔 Δt＝0.6 s 同步，故每次冲量都发生在共速瞬间。",
                 latex="dt = \\frac{v_{2b} + v_{0}}{a_{2}}",
                 sympy="dt - (v2b + v0)/a2",
                 l2="(m/s)/(m/s²)＝s",
                 l4="相对速度取 (2 − (−1))＝3 m/s；把带速当 0 会得 0.4 s，周期错位后整问失效",
                 val={"symbol": "dt", "number": 0.6, "exact": "3/5", "unit": "s",
                      "direction": None, "sig_figs": 3},
                 laws=["L-05", "L-01"]),
            dict(pid="A-08-S10", title="定出到 M 的剩余距离与末段", kind="critical", score=2,
                 stmt="每周期净位移 (2−1)/2×0.6＝0.3 m，10 个周期走 3.0 m，距 M 尚余 3.3−3.0＝0.3 m；第 11 次冲量后再经 0.2 s 到达 M，末段相对路程 0.5 m。",
                 crit=dict(expr="L - 10*(v2b - v0)/2*dt", expected="s1", comparator="eq",
                           text="每周期净位移 (2−1)/2×0.6＝0.3 m，10 个周期走 3.0 m，距 M 尚余 3.3−3.0＝0.3 m，与 s₁ 相等。"),
                 l2="m",
                 l4="剩余 0.3 m 与首段位移 s₁ 数值相同但意义不同（一为减速段、一为末段），不可互相替代",
                 laws=["L-01", "L-05"]),
            dict(pid="A-08-S11", title="摩擦生热 Q=95 J", kind="equation", score=2,
                 stmt="相对路程：10 个整周期各 0.9 m 共 9.0 m，末段 0.5 m，合计 9.5 m；Q＝μm₂g·s_相对＝0.5×2×10×9.5＝95 J。",
                 latex="Q = \\mu m_{2} g \\, ds",
                 sympy="Qheat - mu*m2*g*ds",
                 l2="无量纲×kg×m/s²×m＝J",
                 l4="摩擦生热用相对路程，不是 b 对地位移（对地位移 3.0 m），也不是传送带位移",
                 val={"symbol": "Qheat", "number": 95.0, "exact": "mu*m2*g*ds", "unit": "J",
                      "direction": None, "sig_figs": 2},
                 laws=["L-10"]),
        ],
    }
    build(cfg)


# ---------------------------------------------------------------- B-12

def b12():
    stem = ("某同学受自动雨伞开伞过程的启发，设计了如图所示的物理模型。竖直放置在水平桌面上的滑杆上套有一个滑块，"
            "初始时它们处于静止状态。当滑块从 A 处以初速度 v₀ 为 10 m/s 向上滑动时，受到滑杆的摩擦力 f 为 1 N，"
            "滑块滑到 B 处与滑杆发生完全非弹性碰撞，带动滑杆离开桌面一起竖直向上运动。"
            "已知滑块的质量 m＝0.2 kg，滑杆的质量 M＝0.6 kg，A、B 间的距离 l＝1.2 m，重力加速度 g 取 10 m/s²，"
            "不计空气阻力。求："
            "(1)滑块在静止时和向上滑动的过程中，桌面对滑杆支持力的大小 N₁ 和 N₂；"
            "(2)滑块碰撞前瞬间的速度大小 v₁；"
            "(3)滑杆向上运动的最大高度 h。")
    cfg = {
        "meta": {"answer_id": "B-12", "question_id": "B-12", "group": "B",
                 "source": "2022 广东卷", "question_no": 13, "full_score": 11,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T11:30:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [{"fig_no": 1,
                         "caption": "竖直滑杆与套在其上的滑块，A 在上、B 在下，间距 l；原文无图题",
                         "caption_source": "none", "is_required": False}],
            "subquestions": [
                {"no": "(1)", "text": "桌面对滑杆支持力的大小 N₁ 和 N₂。", "score": 4},
                {"no": "(2)", "text": "滑块碰撞前瞬间的速度大小 v₁。", "score": 3},
                {"no": "(3)", "text": "滑杆向上运动的最大高度 h。", "score": 4},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "滑块", "mass_symbol": "m", "note": "质量 0.2 kg，套在竖直滑杆上，从 A 向上滑动"},
                {"id": "obj2", "name": "滑杆", "mass_symbol": "M", "note": "质量 0.6 kg，竖直置于桌面，碰前静止"},
            ],
            "given": [
                {"symbol": "v0", "value": 10, "unit": "m/s", "text": "以初速度 v₀ 为 10 m/s 向上滑动"},
                {"symbol": "f", "value": 1, "unit": "N", "text": "受到滑杆的摩擦力 f 为 1 N"},
                {"symbol": "m", "value": 0.2, "unit": "kg", "text": "滑块的质量 m＝0.2 kg"},
                {"symbol": "M", "value": 0.6, "unit": "kg", "text": "滑杆的质量 M＝0.6 kg"},
                {"symbol": "L", "value": 1.2, "unit": "m", "text": "A、B 间的距离 l＝1.2 m（符号归一到 L）"},
                {"symbol": "g", "value": 10, "unit": "m/s^2", "text": "重力加速度 g 取 10 m/s²"},
            ],
            "process_segments": [
                {"no": 1, "name": "静止", "start": "初始", "end": "滑块开始上滑前"},
                {"no": 2, "name": "滑块上滑、杆不动", "start": "滑块以 10 m/s 从 A 上滑", "end": "滑块到达 B（距 A 为 l）"},
                {"no": 3, "name": "完全非弹性碰撞", "start": "滑块到 B 与杆相碰", "end": "两者以共同速度一起上移"},
                {"no": 4, "name": "整体竖直上抛", "start": "碰后瞬间", "end": "到达最高点（离桌 h）"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "N1", "text": "静止时桌面对杆的支持力"},
                {"no": "(1)", "quantity": "N2", "text": "滑块上滑时桌面对杆的支持力"},
                {"no": "(2)", "quantity": "v1", "text": "滑块碰前瞬间速度"},
                {"no": "(3)", "quantity": "h", "text": "杆向上运动的最大高度"},
            ],
            "assumptions": [
                "滑杆始终竖直，滑块沿杆做直线运动，取竖直向上为正方向",
                "滑块上滑过程中杆保持静止（题干「带动滑杆离开桌面」发生在碰后）",
                "不计空气阻力；桌面水平，支持力竖直向上",
            ],
        },
        "nums": {"v0": 10.0, "f": 1.0, "m": 0.2, "M": 0.6, "L": 1.2, "g": 10.0,
                 "v1": 8.0, "N1": 8.0, "N2": 5.0, "vc": 2.0, "h": 0.2},
        "allowed_symbols": ["v0", "f", "m", "M", "L", "g", "v1", "N1", "N2", "vc", "h", "Fnet"],
        "prior": "high",
        "reason": "金标参考解：整体法与隔离法切换的两套受力，L1 逐式数值回代、L2 量纲全过，11/11 满分",
        "steps": [
            dict(pid="B-12-S01", title="判定静止时可用整体法", kind="judgment", score=1,
                 stmt="初始静止，滑块与杆加速度均为零，可把两者作为整体：竖直方向合外力为零。",
                 crit=dict(expr="Fnet", expected=0, comparator="eq",
                           text="初始静止，滑块与杆加速度均为零，可作整体：竖直方向合外力为零。"),
                 l2="N",
                 l4="整体法的前提是两部分加速度相同（此处同为 0）；上滑时该前提被破坏，必须换隔离法",
                 laws=["L-03"]),
            dict(pid="B-12-S02", title="整体法求 N1=8 N", kind="value", score=1,
                 stmt="整体竖直方向：N₁＝(m＋M)g＝(0.2＋0.6)×10＝8 N。",
                 latex="N_{1} = (m + M) g",
                 sympy="N1 - (m + M)*g",
                 l2="kg·m/s²＝N",
                 val={"symbol": "N1", "number": 8.0, "exact": "(m+M)*g", "unit": "N",
                      "direction": "+y", "sig_figs": 1},
                 laws=["L-03"]),
            dict(pid="B-12-S03", title="判定上滑时须隔离杆", kind="judgment", score=1,
                 stmt="滑块上滑时两者不再具有相同加速度，整体法失效；杆仍静止，须单独隔离杆分析。滑块对杆的摩擦力向上（大小 1 N），故桌面对杆的支持力变小。",
                 crit=dict(expr="Fnet", expected=0, comparator="eq",
                           text="滑块对杆的摩擦力向上 1 N，杆仍静止故合力为零；但两者加速度不同，整体法失效，须隔离杆。"),
                 l2="N",
                 l4="摩擦力方向：滑块相对杆向上运动，杆受的摩擦力向上；杆静止故合力仍为零",
                 laws=["L-03", "L-05"]),
            dict(pid="B-12-S04", title="隔离杆求 N2=5 N", kind="value", score=1,
                 stmt="隔离杆：竖直方向 N₂＋f′＝Mg，f′＝1 N 向上，得 N₂＝6−1＝5 N。",
                 latex="N_{2} = M g - f",
                 sympy="N2 - (M*g - f)",
                 l2="N",
                 val={"symbol": "N2", "number": 5.0, "exact": "M*g - f", "unit": "N",
                      "direction": "+y", "sig_figs": 1},
                 laws=["L-03", "L-05"]),
            dict(pid="B-12-S05", title="对滑块用动能定理求碰前速度", kind="equation", score=2,
                 stmt="滑块从 A 到 B：重力与摩擦力都做负功，−mgl−fl＝½mv₁²−½mv₀²，代入得 v₁＝8 m/s。",
                 latex="- m g l - f l = \\frac{1}{2} m v_{1}^{2} - \\frac{1}{2} m v_{0}^{2}",
                 sympy="-m*g*L - f*L - (Rational(1,2)*m*v1**2 - Rational(1,2)*m*v0**2)",
                 l2="各项均为 J",
                 l4="两个力都沿运动反方向，功均取负；摩擦力大小恒为 1 N，与正压力无关（题给为定值）",
                 val={"symbol": "v1", "number": 8.0, "exact": "sqrt(v0^2 - 2*(g + f/m)*l)", "unit": "m/s",
                      "direction": "+y", "sig_figs": 1},
                 laws=["L-08", "L-05"]),
            dict(pid="B-12-S06", title="解出 v1=8 m/s", kind="value", score=1,
                 stmt="v₁＝√(100−2×(10＋5)×1.2)＝√64＝8 m/s，方向竖直向上。",
                 latex="v_{1} = 8",
                 sympy="v1 - 8",
                 l2="m/s",
                 l4="开方取正根：滑块仍在向上运动，负根对应「若继续上升再返回」的虚构解",
                 val={"symbol": "v1", "number": 8.0, "exact": "8", "unit": "m/s",
                      "direction": "+y", "sig_figs": 1},
                 laws=["L-08"]),
            dict(pid="B-12-S07", title="完全非弹性碰撞求共同速度", kind="equation", score=2,
                 stmt="碰后两者速度相同：mv₁＝(m＋M)v_c，得 v_c＝0.2×8/0.8＝2 m/s。",
                 latex="m v_{1} = (m + M) v_{c}",
                 sympy="m*v1 - (m + M)*vc",
                 l2="kg·m/s",
                 l4="碰撞时间极短、重力冲量可忽略，故竖直方向动量守恒；碰后一起运动即完全非弹性",
                 val={"symbol": "vc", "number": 2.0, "exact": "m*v1/(m+M)", "unit": "m/s",
                      "direction": "+y", "sig_figs": 1},
                 laws=["L-12"]),
            dict(pid="B-12-S08", title="整体竖直上抛求最大高度", kind="equation", score=1,
                 stmt="碰后整体只受重力：v_c²＝2gh，得 h＝4/20＝0.2 m。",
                 latex="v_{c}^{2} = 2 g h",
                 sympy="vc**2 - 2*g*h",
                 l2="m²/s²",
                 l4="上抛到最高点速度为零；用动能定理 −(m+M)gh＝0−½(m+M)v_c² 与本法等价",
                 laws=["L-02", "L-09"]),
            dict(pid="B-12-S09", title="解出 h=0.2 m", kind="value", score=1,
                 stmt="h＝v_c²/(2g)＝4/20＝0.2 m。",
                 latex="h = 0.2",
                 sympy="h - Rational(1,5)",
                 l2="m",
                 val={"symbol": "h", "number": 0.2, "exact": "vc^2/(2*g)", "unit": "m",
                      "direction": None, "sig_figs": 1},
                 laws=["L-02"]),
        ],
    }
    build(cfg)


# ---------------------------------------------------------------- B-09

def b09():
    stem = ("算盘是我国古老的计算工具，中心带孔的相同算珠可在算盘的固定导杆上滑动，使用前算珠需要归零。"
            "如图所示，水平放置的算盘中有甲、乙两颗算珠未在归零位置，甲靠边框 b，甲、乙相隔 s₁＝3.5×10⁻² m，"
            "乙与边框 a 相隔 s₂＝2.0×10⁻² m，算珠与导杆间的动摩擦因数 μ＝0.1。现用手指将甲以 0.4 m/s 的初速度拨出，"
            "甲、乙碰撞后甲的速度大小为 0.1 m/s，方向不变，碰撞时间极短且不计，重力加速度 g 取 10 m/s²。求："
            "(1)通过计算，判断乙算珠能否滑动到边框 a；"
            "(2)求甲算珠从拨出到停下所需的时间。")
    cfg = {
        "meta": {"answer_id": "B-09", "question_id": "B-09", "group": "B",
                 "source": "2021 广东卷", "question_no": 13, "full_score": 11,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T11:30:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [{"fig_no": 1,
                         "caption": "算盘水平放置，甲、乙两算珠套在同一根导杆上；由边框 b 向 a 依次为 b—甲—乙—a，甲靠 b，甲、乙相隔 s₁，乙与 a 相隔 s₂。放大图为示意，导杆方向以原文「水平」为准；原文无图题",
                         "caption_source": "human",
                         "is_required": True}],
            "subquestions": [
                {"no": "(1)", "text": "判断乙算珠能否滑动到边框 a。", "score": 6},
                {"no": "(2)", "text": "甲算珠从拨出到停下所需的时间。", "score": 5},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "甲算珠", "mass_symbol": "m", "note": "靠边框 b，被拨出后向右运动"},
                {"id": "obj2", "name": "乙算珠", "mass_symbol": "m", "note": "与甲相隔 s₁，原静止，被碰后向 a 运动"},
            ],
            "given": [
                {"symbol": "s1", "value": 0.035, "unit": "m", "text": "甲、乙相隔 s₁＝3.5×10⁻² m"},
                {"symbol": "s2", "value": 0.02, "unit": "m", "text": "乙与边框 a 相隔 s₂＝2.0×10⁻² m"},
                {"symbol": "mu", "value": 0.1, "unit": "1", "text": "算珠与导杆间的动摩擦因数 μ＝0.1"},
                {"symbol": "v0", "value": 0.4, "unit": "m/s", "text": "将甲以 0.4 m/s 的初速度拨出"},
                {"symbol": "v1p", "value": 0.1, "unit": "m/s", "text": "碰撞后甲的速度大小为 0.1 m/s，方向不变"},
                {"symbol": "g", "value": 10, "unit": "m/s^2", "text": "重力加速度 g 取 10 m/s²"},
            ],
            "process_segments": [
                {"no": 1, "name": "甲碰前减速", "start": "甲被拨出（0.4 m/s）", "end": "甲到达乙处（碰前 0.3 m/s）"},
                {"no": 2, "name": "甲乙碰撞", "start": "甲与乙相碰", "end": "甲 0.1 m/s、乙 0.2 m/s，均向 a 方向（碰撞时间极短）"},
                {"no": 3, "name": "乙碰后减速", "start": "碰后瞬间", "end": "乙停下（或到达边框 a）"},
                {"no": 4, "name": "甲碰后减速", "start": "碰后瞬间", "end": "甲停下"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "s", "text": "乙能否滑到边框 a"},
                {"no": "(2)", "quantity": "t", "text": "甲从拨出到停下的时间"},
            ],
            "assumptions": [
                "两颗算珠质量相同（题干「相同算珠」），碰撞为一维正碰",
                "算珠穿在导杆上，正压力等于重力，摩擦力 f＝μmg，故 a＝μg",
                "取甲拨出方向为正方向",
            ],
        },
        "nums": {"s1": 0.035, "s2": 0.02, "mu": 0.1, "v0": 0.4, "v1p": 0.1, "g": 10.0,
                 "m": 1.0, "a1": 1.0, "v1": 0.3, "v2": 0.2, "t1": 0.1, "t": 0.2},
        "allowed_symbols": ["s1", "s2", "mu", "v0", "v1p", "g", "m", "a1", "v1", "v2", "t1", "t", "Fnet"],
        "prior": "high",
        "reason": "金标参考解：两段减速 + 等质量正碰，L1 逐式数值回代、L2 量纲全过，11/11 满分；依赖图为「是」，本样例只作结构表达用",
        "steps": [
            dict(pid="B-09-S01", title="算珠减速的加速度 a=μg", kind="equation", score=2,
                 stmt="算珠在水平导杆上，正压力等于重力，f＝μmg，故 a＝μg＝1 m/s²，甲、乙相同。",
                 latex="a_{1} = \\mu g",
                 sympy="a1 - mu*g",
                 l2="m/s²",
                 l4="两珠「相同」是共用同一加速度的依据；若质量不同，μ 相同仍得同一 a，但碰撞式需改",
                 laws=["L-05", "L-04"]),
            dict(pid="B-09-S02", title="甲碰前速度由速度位移关系求", kind="equation", score=2,
                 stmt="甲从拨出处到乙处位移 s₁：v₁²＝v₀²－2a₁s₁，得 v₁＝0.3 m/s。",
                 latex="v_{1}^{2} - v_{0}^{2} + 2 a_{1} s_{1} = 0",
                 sympy="v1**2 - v0**2 + 2*a1*s1",
                 l2="m²/s²",
                 l4="位移取 s₁（两珠初始间距），不是到边框 a 的距离",
                 val={"symbol": "v1", "number": 0.3, "exact": "sqrt(v0^2 - 2*mu*g*s1)", "unit": "m/s",
                      "direction": None, "sig_figs": 2},
                 laws=["L-01", "L-05"]),
            dict(pid="B-09-S03", title="等质量一维正碰求乙碰后速度", kind="equation", score=2,
                 stmt="两珠质量相同，正碰动量守恒：mv₁＝mv_甲′＋mv_乙，代入 v_甲′＝0.1 得 v_乙＝0.2 m/s。",
                 latex="m v_{1} = m v_{1p} + m v_{2}",
                 sympy="m*v1 - m*v1p - m*v2",
                 l2="kg·m/s（m 可约去，但保留以体现守恒对象是两珠系统）",
                 l4="碰后用题给的甲速 0.1 m/s 代入，不必解二次方程；等质量正碰等价于「交换速度」，可作验算",
                 val={"symbol": "v2", "number": 0.2, "exact": "v1 - v1p", "unit": "m/s",
                      "direction": None, "sig_figs": 2},
                 laws=["L-12"]),
            dict(pid="B-09-S04", title="判断乙能否到达边框 a", kind="critical", score=1,
                 stmt="乙碰后滑行距离 s＝v₂²/(2a₁)＝0.04/2＝0.02 m，恰等于 s₂＝2.0×10⁻² m，故乙恰好滑到边框 a。",
                 crit=dict(expr="v2**2/(2*a1)", expected="s2", comparator="eq",
                           text="乙碰后滑行 s＝v₂²/(2a₁)＝0.04/2＝0.02 m，恰等于 s₂＝2.0×10⁻² m，故乙恰好滑到边框 a。"),
                 l2="m²/s²",
                 l4="「恰好到达」的判据是滑行距离与 s₂ 相等，不是「大于」；把结论写成「能到达」须给出等于的证据",
                 laws=["L-01"]),
            dict(pid="B-09-S05", title="判定甲分两段运动", kind="judgment", score=1,
                 stmt="甲的运动被碰撞分成两段：碰前从 0.4 减到 0.3 m/s，碰后从 0.1 减到 0；两段加速度同为 1 m/s²，但初速不同。",
                 crit=dict(expr="Fnet", expected=0, comparator="eq",
                           text="水平方向只有摩擦力，两段都做匀减速：碰前 0.4→0.3 m/s、碰后 0.1→0，加速度同为 1 m/s²。"),
                 l2="N",
                 l4="水平方向只有摩擦力，故两段都做匀减速；不能把 0.4→0 当成一段（碰撞改写了速度）",
                 laws=["L-04", "L-05"]),
            dict(pid="B-09-S06", title="求甲碰前段的时间", kind="equation", score=2,
                 stmt="碰前段 t₁＝(v₀−v₁)/a₁＝(0.4−0.3)/1＝0.1 s。",
                 latex="t_{1} = \\frac{v_{0} - v_{1}}{a_{1}}",
                 sympy="t1 - (v0 - v1)/a1",
                 l2="s",
                 l4="速度变化取大小，方向已由「减速」确定",
                 val={"symbol": "t1", "number": 0.1, "exact": "1/10", "unit": "s",
                      "direction": None, "sig_figs": 1},
                 laws=["L-01"]),
            dict(pid="B-09-S07", title="求甲总时间 t=0.2 s", kind="value", score=1,
                 stmt="碰后段 t₂＝v_甲′/a₁＝0.1/1＝0.1 s；合计 t＝t₁＋t₂＝0.2 s。",
                 latex="t = t_{1} + \\frac{v_{1p}}{a_{1}}",
                 sympy="t - t1 - v1p/a1",
                 l2="s",
                 l4="两段时间相接（碰撞时间不计），可直接相加；若计入碰撞时间则题干「极短且不计」被违反",
                 val={"symbol": "t", "number": 0.2, "exact": "1/5", "unit": "s",
                      "direction": None, "sig_figs": 1},
                 laws=["L-01"]),
        ],
    }
    build(cfg)


# ---------------------------------------------------------------- B-02（全符号）

def b02():
    """2025 北京 17：全符号题。six 步全部 na —— 验「无数值锚点时 L1 的降级路径」。"""
    stem = ("某物体以一定初速度从地面竖直向上抛出，经过时间 t 到达最高点。在最高点该物体炸裂成 A、B 两部分，"
            "质量分别为 2m 和 m，其中 A 以速度 v 沿水平方向飞出。重力加速度为 g，不计空气阻力。求："
            "(1)该物体抛出时的初速度大小 v₀；"
            "(2)炸裂后瞬间 B 的速度大小 v_B；"
            "(3)A、B 落地点之间的距离 d。")
    cfg = {
        "meta": {"answer_id": "B-02", "question_id": "B-02", "group": "B",
                 "source": "2025 北京卷", "question_no": 17, "full_score": 9,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T13:20:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            # 原文 §3：本题无图。figures 允许空数组，本样例是第一个显式验空路径的
            "figures": [],
            "subquestions": [
                {"no": "(1)", "text": "该物体抛出时的初速度大小 v₀。", "score": 2},
                {"no": "(2)", "text": "炸裂后瞬间 B 的速度大小 v_B。", "score": 3},
                {"no": "(3)", "text": "A、B 落地点之间的距离 d。", "score": 4},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "炸裂前的物体", "mass_symbol": "m",
                 "note": "质量 3m（m 为质量单位）；从地面竖直上抛"},
                {"id": "obj2", "name": "A 部分", "mass_symbol": "m",
                 "note": "质量 2m；炸裂后沿水平方向飞出，式中以系数 2 体现"},
                {"id": "obj3", "name": "B 部分", "mass_symbol": "m",
                 "note": "质量 m；炸裂后与 A 反向沿水平方向飞出"},
            ],
            "given": [
                {"symbol": "v0", "value": None, "unit": "m/s", "text": "抛出时的初速度 v₀（题给符号，无值）"},
                {"symbol": "t", "value": None, "unit": "s", "text": "从抛出到最高点所用时间 t（题给符号）"},
                {"symbol": "m", "value": None, "unit": "kg",
                 "text": "A、B 质量分别为 2m 与 m —— m 是质量单位，全题不出现数值"},
                {"symbol": "v", "value": None, "unit": "m/s", "text": "A 炸裂后沿水平方向飞出的速度 v（题给符号）"},
                {"symbol": "g", "value": None, "unit": "m/s^2", "text": "重力加速度 g（题给符号，无数值）"},
            ],
            "process_segments": [
                {"no": 1, "name": "竖直上抛", "start": "物体以 v₀ 从地面抛出", "end": "到达最高点（速度为零，历时 t）"},
                {"no": 2, "name": "最高点炸裂", "start": "在最高点炸裂为 A、B",
                 "end": "A 以 v 水平飞出、B 以 v_B 反向水平飞出（竖直分速度均为零）"},
                {"no": 3, "name": "两段平抛", "start": "炸裂后瞬间", "end": "A、B 同时落地（下落时间同为 t）"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "v0", "text": "抛出时的初速度大小"},
                {"no": "(2)", "quantity": "v2", "text": "炸裂后瞬间 B 的速度大小"},
                {"no": "(3)", "quantity": "d", "text": "A、B 落地点之间的距离"},
            ],
            "assumptions": [
                "取竖直向上为 +y、水平方向为 +x；A 沿 +x 飞出，B 沿 −x",
                "炸裂瞬间内力远大于重力，且炸裂前竖直分速度为零，故 A、B 的竖直分速度均为零",
                "m 是质量单位（A＝2m、B＝m），全题不出现数值；L1 无值可回代，按 na 处理",
                "不计空气阻力；重力加速度记为 g，题给符号无值",
            ],
        },
        "nums": {},
        "allowed_symbols": ["v0", "g", "t", "m", "v", "v2", "t2", "s1", "s2", "d", "Fnet"],
        "prior": "mid",
        "reason": "金标参考解：全符号题，L1 全步 na（无数值可回代），L2 量纲逐式手判；9/9 满分，未触归零点",
        "steps": [
            dict(pid="B-02-S01", title="上抛到最高点：v0 = gt", kind="equation", score=2,
                 stmt="物体以 v₀ 上抛、只受重力，到最高点时速度为零、历时 t：v₀＝gt。这是本题唯一的运动学约束。",
                 latex="v_{0} = g t",
                 sympy="v0 - g*t",
                 l2="两边均为 m/s",
                 l4="「到最高点速度为零」只能配速度式；写成 v₀＝½gt² 或 v₀＝gt² 是把位移式当速度式（判分口径本步 0 分）",
                 val={"symbol": "v0", "number": None, "exact": "g*t", "unit": "m/s",
                      "direction": "+y", "sig_figs": None},
                 laws=["L-02"]),
            dict(pid="B-02-S02", title="判定只有水平方向动量守恒", kind="judgment", score=1,
                 stmt="炸裂内力沿竖直方向成对抵消、水平方向无外力冲量；又因最高点竖直分速度为零，故只对水平方向写动量守恒（炸裂前水平动量为零）。",
                 crit=dict(expr="Fnet", expected=0, comparator="eq",
                           text="炸裂内力沿竖直方向成对抵消、水平方向无外力冲量，故只对水平方向写动量守恒。"),
                 l2="N（水平方向合外力为零）",
                 l4="此式是「水平方向合外力为零」的等式化，不是对竖直方向受力求和：竖直方向有炸裂内力，但成对且瞬时",
                 laws=["L-12"]),
            dict(pid="B-02-S03", title="水平动量守恒求 B 的速度", kind="equation", score=2,
                 stmt="炸裂前水平动量为零，炸裂后 A 沿 +x 以 v 飞出、B 沿 −x 飞出：0＝2m·v−m·v_B，得 v_B＝2v；题问速度大小，取 2v。",
                 latex="2 m v = m v_{2}",
                 sympy="2*m*v - m*v2",
                 l2="两边均为 kg·m/s",
                 l4="负号只表示 B 与 A 反向；漏负号会把 B 写成与 A 同向，质量比颠倒会得 v/2——两种都是本步 0 分",
                 val={"symbol": "v2", "number": None, "exact": "2*v", "unit": "m/s",
                      "direction": "-x", "sig_figs": None},
                 laws=["L-12"]),
            dict(pid="B-02-S04", title="下落时间与上升时间同为 t", kind="judgment", score=1,
                 stmt="炸裂点高度 h＝½gt²；从该高度自由落体到地面所需时间由 ½gt² 反解仍为 t —— 上抛的上升段与下落段对同一高度对称。",
                 crit=dict(expr="t2", expected="t", comparator="eq",
                           text="炸裂点高度 h＝½gt²，从该高度自由落体到地面的时间由 ½gt² 反解仍为 t。"),
                 l2="s",
                 l4="只对「从最高点落到地面」这一段成立；把下落时间另设为 √(2h/g) 而不化简到 t，本步 0 分",
                 val={"symbol": "t2", "number": None, "exact": "t", "unit": "s",
                      "direction": None, "sig_figs": None},
                 laws=["L-02", "L-01"]),
            dict(pid="B-02-S05", title="两段平抛的水平位移", kind="equation", score=1,
                 stmt="A、B 均做平抛、水平方向匀速：x_A＝v·t、x_B＝v_B·t＝2v·t（下落时间同为 t），合写为 s₁＋s₂＝(v＋v₂)t。",
                 latex="s_{1} + s_{2} = (v + v_{2}) t",
                 sympy="s1 + s2 - (v + v2)*t",
                 l2="m",
                 l4="两个水平位移共用同一个下落时间 t；漏乘 t 或把 x_B 写成 v_B·t/2 都是本步 0 分",
                 laws=["L-01"]),
            dict(pid="B-02-S06", title="反向飞出，d = 3vt", kind="value", score=2,
                 stmt="A、B 从同一点反向水平飞出，落地点在炸裂点正下方两侧：d＝x_A＋x_B＝vt＋2vt＝3vt（不是相减）。",
                 latex="d = s_{1} + s_{2}",
                 sympy="d - s1 - s2",
                 l2="m",
                 l4="「距离」是两点间距离，反向必相加；写成 |x_A−x_B|＝vt 是本步 0 分。结果不含 m、不带单位",
                 val={"symbol": "d", "number": None, "exact": "3*v*t", "unit": "m",
                      "direction": None, "sig_figs": None},
                 laws=["L-01"]),
        ],
    }
    for st, d in zip(cfg["steps"], [[], [1], [2], [1], [3, 4], [5]]):
        st["deps"] = d
    build(cfg)


# ---------------------------------------------------------------- A-10（万有引力·全符号）

def a10():
    """2023 北京 20：全符号 + 球内质量分布 + 暗物质；依赖图＝否（is_required=false）。"""
    stem = ("螺旋星系中有大量的恒星和星际物质，主要分布在半径为 R 的球体内，球体外仅有极少的恒星。"
            "球体内物质总质量为 M，可认为均匀分布，球体内外的所有恒星都绕星系中心做匀速圆周运动，"
            "恒星到星系中心的距离为 r，引力常量为 G。"
            "(1)求 r>R 区域的恒星做匀速圆周运动的速度大小 v 与 r 的关系；"
            "(2)根据电荷均匀分布的球壳内试探电荷所受库仑力的合力为零，利用库仑力与万有引力的表达式的相似性和相关力学知识，"
            "求 r≤R 区域的恒星做匀速圆周运动的速度大小 v 与 r 的关系；"
            "(3)科学家根据实测数据，得到此螺旋星系中不同位置的恒星做匀速圆周运动的速度大小 v 随 r 的变化关系图像，"
            "如图所示，根据在 r>R 范围内的恒星速度大小几乎不变，科学家预言螺旋星系周围(r>R)存在一种特殊物质，"
            "称之为暗物质。暗物质与通常的物质有引力相互作用，并遵循万有引力定律，求 r=nR 内暗物质的质量 M′。")
    cfg = {
        "meta": {"answer_id": "A-10", "question_id": "A-10", "group": "A",
                 "source": "2023 北京卷", "question_no": 20, "full_score": 12,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T13:25:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [{"fig_no": 1,
                         "caption": "第 (3) 问的 v–r 曲线示意：r<R 段随 r 上升、r>R 段近似水平；原文无图题，"
                                    "关键事实（r>R 速度几乎不变）已在文字中给出",
                         "caption_source": "none", "is_required": False}],
            "subquestions": [
                {"no": "(1)", "text": "求 r>R 区域恒星匀速圆周运动的速度大小 v 与 r 的关系。", "score": 3},
                {"no": "(2)", "text": "求 r≤R 区域恒星匀速圆周运动的速度大小 v 与 r 的关系。", "score": 4},
                {"no": "(3)", "text": "求 r=nR 内暗物质的质量 M′。", "score": 5},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "螺旋星系球体内的物质", "mass_symbol": "M",
                 "note": "半径 R 的球体内总质量 M，均匀分布；球体外恒星极少，忽略其引力"},
                {"id": "obj2", "name": "恒星（试探质点）", "mass_symbol": "m",
                 "note": "质量 m，绕星系中心做匀速圆周运动，轨道半径 r"},
            ],
            "given": [
                {"symbol": "R", "value": None, "unit": "m", "text": "物质主要分布在半径为 R 的球体内（符号量）"},
                {"symbol": "M", "value": None, "unit": "kg", "text": "球体内物质总质量为 M，可认为均匀分布"},
                {"symbol": "r", "value": None, "unit": "m", "text": "恒星到星系中心的距离 r（符号量）"},
                {"symbol": "Gc", "value": None, "unit": "m^3/kg/s^2",
                 "text": "引力常量为 G —— 按 T09 归一为 Gc（避免与重力 G 撞名），题给符号无值"},
                {"symbol": "n", "value": None, "unit": "1", "text": "第 (3) 问的 r=nR 中的比值 n（符号量，n>1）"},
            ],
            "process_segments": [
                {"no": 1, "name": "球外 r>R：平方反比", "start": "恒星在 r>R 处做圆周运动",
                 "end": "得 v＝√(GcM/r)，随 r 增大而减小"},
                {"no": 2, "name": "球内 r≤R：质量随 r³ 增长", "start": "恒星在 r≤R 处",
                 "end": "得 v＝r√(GcM/R³)，随 r 增大而增大"},
                {"no": 3, "name": "r=nR 处与暗物质", "start": "实测 r>R 速度几乎不变",
                 "end": "得 M′＝(n−1)M"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "v", "text": "球外速度与 r 的关系"},
                {"no": "(2)", "quantity": "v", "text": "球内速度与 r 的关系"},
                {"no": "(3)", "quantity": "Mp", "text": "r=nR 内的暗物质质量"},
            ],
            "assumptions": [
                "球体内物质均匀分布 —— 半径 r 处球内质量 M₀＝M r³/R³，不是 M，也不是按 r² 的面积比",
                "球体外「仅有极少的恒星」：r>R 处只计入球内总质量 M，球壳对内部恒星的引力为零",
                "第 (3) 问「r>R 范围内速度几乎不变」是实测事实，r＝R 与 r＝nR 处取同一速率 v₀；这不是由 GcM/r 推出的递减关系",
                "暗物质只提供引力、同样遵循万有引力定律；恒星做匀速圆周运动，向心力全部由引力提供",
                "符号 v 指「该处速率」，球内与球外是两个分支（S02 与 S05 各记本段表达式）；第 (3) 问另记边缘速率为 v₀",
                "引力常量写 Gc（T09 规定）；本题全符号，无一个数值",
            ],
        },
        "nums": {},
        "allowed_symbols": ["Gc", "M", "m", "R", "r", "v", "M0", "v0", "n", "Mp"],
        "prior": "high",
        "reason": "金标参考解：全符号 + 球内质量分布 + 暗物质；L1 全步 na，L2 逐式手判；12/12 满分，未触归零点",
        "steps": [
            dict(pid="A-10-S01", title="球外：引力提供向心力", kind="equation", score=2,
                 stmt="r>R 时恒星受到的引力只由球内总质量 M 提供：GcMm/r²＝mv²/r。",
                 latex="\\frac{Gc M m}{r^{2}} = \\frac{m v^{2}}{r}",
                 sympy="Gc*M*m/r**2 - m*v**2/r",
                 l2="两边均为 N（kg·m/s²）",
                 l4="球外只看球内质量（球壳定理）；r 是恒星到中心的距离，写成 R 是本步 0 分",
                 laws=["L-07", "L-06"]),
            dict(pid="A-10-S02", title="球外 v = √(GM/r)", kind="value", score=1,
                 stmt="约去 m、两边乘 r：v²＝GcM/r，取正根 v＝√(GcM/r)。球外速度随 r 增大而减小。",
                 latex="v = \\sqrt{\\frac{Gc M}{r}}",
                 sympy="v**2 - Gc*M/r",
                 l2="左边 m²/s²；右边 m³/(kg·s²)·kg/m＝m²/s²",
                 l4="取正根（速率）；写成 √(GM/R) 即把 r 换成 R，根号内写成 GM/r² 也是本步 0 分",
                 val={"symbol": "v", "number": None, "exact": "sqrt(Gc*M/r)", "unit": "m/s",
                      "direction": None, "sig_figs": None},
                 laws=["L-07"]),
            dict(pid="A-10-S03", title="球内质量按体积比 M0 = Mr³/R³", kind="value", score=2,
                 stmt="均匀分布 ⇒ 半径 r 的球内质量 M₀ 与体积成正比：M₀/M＝(r/R)³，即 M₀＝Mr³/R³（随 r³ 增长）。",
                 latex="M_{0} = M \\frac{r^{3}}{R^{3}}",
                 sympy="M0 - M*r**3/R**3",
                 l2="kg",
                 l4="把 M₀ 写成 M（认为球内质量与 r 无关）或写成 Mr²/R²（按面积比）都是本步 0 分",
                 val={"symbol": "M0", "number": None, "exact": "M*r^3/R^3", "unit": "kg",
                      "direction": None, "sig_figs": None},
                 laws=["L-07"]),
            dict(pid="A-10-S04", title="球内：代入 M0 后 v²=GMr²/R³", kind="equation", score=1,
                 stmt="球内引力由 M₀ 提供：GcM₀m/r²＝mv²/r；代入 M₀＝Mr³/R³ 得 v²＝GcMr²/R³。",
                 latex="\\frac{Gc M_{0} m}{r^{2}} = \\frac{m v^{2}}{r}",
                 sympy="Gc*M0*m/r**2 - m*v**2/r",
                 l2="两边均为 N",
                 l4="M₀ 中的 r³ 与分母 r² 约成一次 r；用 r>R 的式子直接代入会得 v∝1/√r，与「球内速度随 r 增大」相反",
                 laws=["L-07", "L-06"]),
            dict(pid="A-10-S05", title="球内 v = r√(GM/R³)", kind="value", score=1,
                 stmt="v＝r√(GcM/R³)：与 r 成正比；r＝R 处与球外表达式连续（同为 √(GcM/R)）。",
                 latex="v = r \\sqrt{\\frac{Gc M}{R^{3}}}",
                 sympy="v**2 - r**2*Gc*M/R**3",
                 l2="m²/s²",
                 l4="漏掉 r 的一次方会写成 √(GM/R³)（量纲已是 m/s²，不是 m/s）；写成 v∝1/√r 也是本步 0 分",
                 val={"symbol": "v", "number": None, "exact": "r*sqrt(Gc*M/R^3)", "unit": "m/s",
                      "direction": None, "sig_figs": None},
                 laws=["L-07"]),
            dict(pid="A-10-S06", title="两处取同一 v0", kind="judgment", score=2,
                 stmt="r＝R 处由球外表达式得 v₀²＝GcM/R；实测「r>R 范围内速度几乎不变」，故 r＝nR 处速率也记作同一 v₀，可对两处分别写「引力＝向心」并联立。",
                 crit=dict(expr="v0**2*R - Gc*M", expected=0, comparator="eq",
                           text="r＝R 处由球外表达式得 v₀²＝GcM/R；实测 r>R 速度几乎不变，故 r＝nR 处取同一 v₀。"),
                 l2="m²/s²·m＝m³/s²；右边 m³/(kg·s²)·kg 同量纲",
                 l4="这是实测事实，不是牛顿引力的推论：按 GcM/r，r>R 的速度应随 r 减小。S07 两式共用同一个 v₀，就是这一步判定的落地；未说明两处同 v₀（另设未知量又无方程）本步 0 分",
                 val={"symbol": "v0", "number": None, "exact": "sqrt(Gc*M/R)", "unit": "m/s",
                      "direction": None, "sig_figs": None},
                 laws=["L-07"]),
            dict(pid="A-10-S07", title="两处列式并联立", kind="equation", score=2,
                 stmt="R 处：GcM/R²＝v₀²/R；nR 处（含暗物质）：Gc(M＋M′)/(nR)²＝v₀²/(nR)。两式各为零，相除即可消去 v₀。",
                 latex="\\frac{Gc M}{R^{2}} - \\frac{v_{0}^{2}}{R} + \\frac{Gc (M + M_{p})}{(n R)^{2}} - \\frac{v_{0}^{2}}{n R} = 0",
                 sympy="(Gc*M/R**2 - v0**2/R) + (Gc*(M + Mp)/(n*R)**2 - v0**2/(n*R))",
                 l2="四项均为 N/kg＝m/s²",
                 l4="两式同列时 equation 记残差和（和为零）；两式各自为零见判分口径。只写一处、nR 处漏 M 只写 M′，都是本步 0 分",
                 laws=["L-07"]),
            dict(pid="A-10-S08", title="M′ = (n−1)M", kind="value", score=1,
                 stmt="两式相除：(M＋M′)/M＝n²·(R/nR)＝n，故 M′＝(n−1)M —— 只与 n 有关，与 r 的具体值无关。",
                 latex="M_{p} = (n - 1) M",
                 sympy="Mp - (n-1)*M",
                 l2="kg",
                 l4="写成 (n²−1)M 是把 (nR)² 与 nR 混用；写成 nM 是漏减球内原有质量 M；结果含 Gc 或 v₀ 未消尽也是 0 分",
                 val={"symbol": "Mp", "number": None, "exact": "(n-1)*M", "unit": "kg",
                      "direction": None, "sig_figs": None},
                 laws=["L-07"]),
        ],
    }
    for st, d in zip(cfg["steps"], [[], [1], [], [3], [4], [2], [6], [7]]):
        st["deps"] = d
    build(cfg)


# ---------------------------------------------------------------- B-20（图即数据源·临时可跑）

def b20():
    """2024 山东 17：a–F 图线的斜率与截距只存在于图中。

    1.2（T08d 缺陷 ①）：三条读数逐条登记在 figures[fig_no=2].provides，
    given 里同符号项标 source=figure，并由 stem_text + 规范化 provides 算出
    question.input_sha256 —— 改任一条读数，指纹必失配。
    """
    stem = ("如图甲所示，质量为 M 的轨道静止在光滑水平面上，轨道水平部分的上表面粗糙，竖直半圆形部分的表面光滑，"
            "两部分在 P 点平滑连接，Q 为轨道的最高点。质量为 m 的小物块静置在轨道水平部分上，与水平轨道间的动摩擦因数为 μ，"
            "最大静摩擦力等于滑动摩擦力。已知轨道半圆形部分的半径 R＝0.4 m，重力加速度大小 g＝10 m/s²。"
            "(1)若轨道固定，小物块以一定的初速度沿轨道运动到 Q 点时，受到轨道的弹力大小等于 3mg，求小物块在 Q 点的速度大小 v；"
            "(2)若轨道不固定，给轨道施加水平向左的推力 F，小物块处在轨道水平部分时，轨道的加速度 a 与 F 对应关系如图乙所示。"
            "(ⅰ)求 μ 和 m；(ⅱ)初始时，小物块静置在轨道最左端，给轨道施加水平向左的推力 F＝8 N，当小物块到 P 点时撤去 F，"
            "小物块从 Q 点离开轨道时相对地面的速度大小为 7 m/s。求轨道水平部分的长度 L。")
    cfg = {
        "meta": {"answer_id": "B-20", "question_id": "B-20", "group": "B",
                 "source": "2024 山东卷", "question_no": 17, "full_score": 14,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T13:30:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [
                {"fig_no": 1,
                 "caption": "图甲：轨道由水平粗糙段与竖直光滑半圆段在 P 点平滑连接，Q 为半圆最高点，小物块静置于水平段左端；原文无图题",
                 "caption_source": "human", "is_required": True},
                {"fig_no": 2,
                 "caption": "图乙：轨道加速度 a 随推力 F 变化的折线（两段斜率与一段截距；读数逐条登记在 provides）；原文无图题",
                 "caption_source": "human", "is_required": True,
                 "provides": [
                     {"symbol": "k1", "value": 0.5, "unit": "kg^-1",
                      "read_from": "图乙 F≤4 N 段的斜率",
                      "text": "由图乙第一段（过原点、到 F＝4 N 止）的斜率读出 k₁＝0.5 kg⁻¹，即 1/(M＋m)"},
                     {"symbol": "k2", "value": 1, "unit": "kg^-1",
                      "read_from": "图乙 F>4 N 段的斜率",
                      "text": "由图乙第二段（F>4 N）的斜率读出 k₂＝1 kg⁻¹，即 1/M"},
                     {"symbol": "b2", "value": -2, "unit": "m/s^2",
                      "read_from": "图乙 F>4 N 段的纵轴截距",
                      "text": "由图乙第二段反向延长到 F＝0 的截距读出 b₂＝−2 m/s²，即 −μmg/M；符号为负"},
                 ]},
            ],
            "subquestions": [
                {"no": "(1)", "text": "轨道固定时，小物块在 Q 点的速度大小 v。", "score": 4},
                # 原文第 (2) 问内含 (ⅰ)(ⅱ)；Schema 的 no 只允许 (\d+)，故平铺为 (2)(3)，text 标注来源
                {"no": "(2)", "text": "原文第 (2) 问 (ⅰ)：由图乙求 μ 和 m。", "score": 4},
                {"no": "(3)", "text": "原文第 (2) 问 (ⅱ)：F＝8 N，物块到 P 时撤去 F，Q 点离开时相对地面 7 m/s，求水平段长度 L。", "score": 6},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "轨道", "mass_symbol": "M",
                 "note": "水平段粗糙、半圆段光滑；静止在光滑水平面上，可被水平推力 F 推动"},
                {"id": "obj2", "name": "小物块", "mass_symbol": "m",
                 "note": "静置在轨道水平段左端；与水平段动摩擦因数 μ，最大静摩擦力等于滑动摩擦力"},
            ],
            "given": [
                {"symbol": "R", "value": 0.4, "unit": "m", "text": "半圆形部分的半径 R＝0.4 m"},
                {"symbol": "g", "value": 10, "unit": "m/s^2", "text": "重力加速度大小 g＝10 m/s²"},
                {"symbol": "F", "value": 8, "unit": "N", "text": "第 (2)(ⅱ) 问的推力 F＝8 N（方向水平向左）"},
                {"symbol": "v1", "value": 7, "unit": "m/s",
                 "text": "小物块从 Q 点离开轨道时相对地面的速度大小 7 m/s（第 (2)(ⅱ) 问）"},
                {"symbol": "M", "value": None, "unit": "kg", "text": "轨道质量 M（题干只给符号，数值须由图乙解出）"},
                {"symbol": "m", "value": None, "unit": "kg", "text": "小物块质量 m（同上）"},
                {"symbol": "k1", "value": 0.5, "unit": "kg^-1", "source": "figure",
                 "text": "【图乙读出】F≤4 N 段斜率 0.5 kg⁻¹，即 1/(M＋m)；题干未给（见 fig_no=2 的 provides）"},
                {"symbol": "k2", "value": 1, "unit": "kg^-1", "source": "figure",
                 "text": "【图乙读出】F>4 N 段斜率 1 kg⁻¹，即 1/M；题干未给（见 fig_no=2 的 provides）"},
                {"symbol": "b2", "value": -2, "unit": "m/s^2", "source": "figure",
                 "text": "【图乙读出】F>4 N 段截距 −2 m/s²，即 −μmg/M；题干未给（见 fig_no=2 的 provides）"},
            ],
            "process_segments": [
                {"no": 1, "name": "第 (1) 问：轨道固定、物块过 Q 点（独立情境）",
                 "start": "小物块以一定初速度沿固定的轨道运动",
                 "end": "小物块经过最高点 Q（速度沿水平方向）；不与第 (2) 问的时间序列相连"},
                {"no": 2, "name": "F 作用下的水平段（先整体后相对滑动）",
                 "start": "给小物块静置于左端的轨道施加水平向左的推力 F",
                 "end": "小物块到达 P 点、撤去 F（F≤4 N 时两者相对静止，F>4 N 时相对滑动）"},
                {"no": 3, "name": "撤去 F 后继续相对滑动",
                 "start": "撤去 F 的瞬间", "end": "小物块到达 Q 点（水平方向动量守恒、机械能守恒）"},
                {"no": 4, "name": "过 Q 点离开轨道", "start": "小物块经过 Q 点", "end": "离开轨道，相对地面速度 7 m/s"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "v", "text": "轨道固定时 Q 点的速度"},
                {"no": "(2)", "quantity": "mu", "text": "动摩擦因数"},
                {"no": "(2)", "quantity": "m", "text": "小物块质量"},
                {"no": "(3)", "quantity": "L", "text": "轨道水平部分的长度"},
            ],
            "assumptions": [
                "第 (1) 问轨道固定，属独立情境，不与第 (2) 问的时间序列相连",
                "图乙的三条读数（0.5 kg⁻¹、1 kg⁻¹、−2 m/s²）只存在于图中，题干文字未给；1.2 起逐条登记在 figures[fig_no=2].provides，given 里同符号项标 source=figure，并进 input_sha256",
                "最大静摩擦力等于滑动摩擦力；F≤4 N 时两者相对静止（共同加速），F>4 N 时发生相对滑动",
                "取水平向左为正方向；轨道与地面间无摩擦，Q 点弹力指向圆心（竖直向下）",
                "7 m/s 是离开 Q 瞬间相对地面的速度；Q 点为半圆最高点，该处速度沿水平方向",
            ],
        },
        "nums": {"R": 0.4, "g": 10.0, "F": 8.0, "v1": 7.0, "M": 1.0, "m": 1.0, "mu": 0.2,
                 "k1": 0.5, "k2": 1.0, "b2": -2.0, "a1": 2.0, "a2": 6.0, "t": 1.5, "L": 4.5,
                 "Nf": 30.0, "v": 4.0, "v2p": 5.0},
        "allowed_symbols": ["R", "g", "F", "v1", "M", "m", "mu", "k1", "k2", "b2",
                            "a1", "a2", "t", "L", "Nf", "v", "v2p"],
        "prior": "high",
        "reason": "金标参考解：含临界（最大静摩擦）与图读数；L1 逐式数值回代、L2 量纲全过，14/14 满分，未触归零点。图读数来源见 figures[fig_no=2].provides 与 given 的 source=figure 标注",
        "steps": [
            dict(pid="B-20-S01", title="Q 点弹力只能向下", kind="judgment", score=1,
                 stmt="物块在 Q 点速度足够大，轨道对它的弹力只能指向圆心（竖直向下）；若弹力向上，物块早已脱离轨道。故 3mg 与 mg 同向。",
                 crit=dict(expr="Nf", expected="3*m*g", comparator="eq",
                           text="Q 点弹力只能指向圆心（竖直向下），故 Nf＝3mg 与 mg 同向；若弹力向上，物块早已脱离轨道。"),
                 l2="N",
                 l4="方向判定是第一个采分点：把 3mg 判成向上会得 3mg−mg＝mv²/R，速度变成 2 m/s（本步 0 分）",
                 laws=["L-06"]),
            dict(pid="B-20-S02", title="Q 点向心力方程", kind="equation", score=2,
                 stmt="最高点沿半径方向：N＋mg＝mv²/R，N＝3mg，故 4mg＝mv²/R。",
                 latex="3 m g + m g = \\frac{m v^{2}}{R}",
                 sympy="3*m*g + m*g - m*v**2/R",
                 l2="两边均为 N",
                 l4="重力与弹力同向（都指向圆心），故相加；漏重力项会得 v＝√(3gR)",
                 laws=["L-06"]),
            dict(pid="B-20-S03", title="v = 4 m/s", kind="value", score=1,
                 stmt="代入 R＝0.4 m、g＝10 m/s²：v²＝4×10×0.4＝16，v＝4 m/s（取正根，速率）。",
                 latex="v = 4",
                 sympy="v - 4",
                 l2="m/s",
                 l4="答 2 m/s 是 S01 方向判错的结果；只写 4 不写单位 m/s 本步 0 分",
                 val={"symbol": "v", "number": 4.0, "exact": "4", "unit": "m/s",
                      "direction": None, "sig_figs": 1},
                 laws=["L-06"]),
            dict(pid="B-20-S04", title="图乙的转折点 F=4 N", kind="judgment", score=1,
                 stmt="图乙在 F＝4 N 处折转：F≤4 N 时 a–F 为过原点直线（两者相对静止、共同加速）；F>4 N 后斜率变大（发生相对滑动，只有轨道被加速）。转折点即最大静摩擦力被克服的临界：F＝(M＋m)μg＝4 N。",
                 crit=dict(expr="(M + m)*mu*g", expected=4, comparator="eq",
                           text="图乙在 F＝4 N 处折转，折点即最大静摩擦力被克服的临界：F＝(M＋m)μg＝4 N。"),
                 l2="kg·(1)·m/s²＝N",
                 l4="折点不是「两个读数随便连」，它由 μg 与整体质量决定；未指出 F＝4 N 这个转折，后面两段斜率会用错（E-09）",
                 laws=["L-04", "L-05"]),
            dict(pid="B-20-S05", title="两段斜率与截距的物理含义", kind="equation", score=2,
                 stmt="整体段 a＝F/(M＋m)，斜率 k₁＝1/(M＋m)＝0.5 kg⁻¹；滑动段 a＝F/M−μmg/M，斜率 k₂＝1/M＝1 kg⁻¹、截距 b₂＝−μmg/M＝−2 m/s²。三条读数均来自图乙。",
                 latex="k_{1} = \\frac{1}{M + m}",
                 sympy="(k1*(M + m) - 1) + (k2*M - 1) + (b2*M + mu*m*g)",
                 l2="k₁·kg、k₂·kg 无量纲；b₂·M 为 N，与 μmg 同量纲",
                 l4="一式含三条读数，equation 记残差和（和为零）；逐条归零见判分口径。截距符号取正会解出负的 μ",
                 laws=["L-04", "L-05"]),
            dict(pid="B-20-S06", title="M=1 kg、m=1 kg、μ=0.2", kind="value", score=1,
                 stmt="由 k₂ 得 M＝1 kg；由 k₁ 得 M＋m＝2 kg，故 m＝1 kg；由 b₂ 得 μ＝−b₂M/(mg)＝2×1/(1×10)＝0.2。",
                 latex="M = 1",
                 sympy="(M - 1) + (m - 1) + (mu - Rational(1,5))",
                 l2="kg、kg、无量纲",
                 l4="三个结果同出一步，value 单槽只登记 M；m 与 μ 见 statement。m 取 2 kg（与 M 颠倒）本步 0 分",
                 val={"symbol": "M", "number": 1.0, "exact": "1", "unit": "kg",
                      "direction": None, "sig_figs": 1},
                 laws=["L-04", "L-05"]),
            dict(pid="B-20-S07", title="F=8 N 时两者的加速度", kind="value", score=1,
                 stmt="F＝8 N＞4 N，已相对滑动：轨道 a轨＝(F−μmg)/M＝(8−2)/1＝6 m/s²；物块只受摩擦力，a物＝μg＝2 m/s²（不是 (F−μmg)/m）。",
                 latex="a_{2} = \\frac{F - \\mu m g}{M}",
                 sympy="(a2 - (F - mu*m*g)/M) + (a1 - mu*g)",
                 l2="m/s²",
                 l4="物块的水平力只有轨道给它的摩擦力，故 a物＝μg；把 F 也算到物块上会得 6 m/s²（E-14）",
                 val={"symbol": "a2", "number": 6.0, "exact": "(F - mu*m*g)/M", "unit": "m/s^2",
                      "direction": "-x", "sig_figs": 1},
                 laws=["L-04", "L-05"]),
            dict(pid="B-20-S08", title="到 P 点：相对加速度定 L", kind="equation", score=2,
                 stmt="两者同向左移，相对加速度 a轨−a物＝4 m/s²，相对位移即水平段长度：L＝½(a轨−a物)t²＝2t²；此时 v物＝a物t＝2t、v轨＝a轨t＝6t。",
                 latex="L = \\frac{1}{2} (a_{2} - a_{1}) t^{2}",
                 sympy="L - Rational(1,2)*(a2 - a1)*t**2",
                 l2="m/s²·s²＝m",
                 l4="用相对加速度，不是任一物体的对地位移；整体直接用 v²＝2aL 会漏掉另一物体的位移（E-03）",
                 laws=["L-01", "L-04"]),
            dict(pid="B-20-S09", title="撤 F 后：动量与机械能守恒", kind="equation", score=2,
                 stmt="撤去 F 后水平方向无外力：M·6t＋m·2t＝M·v轨′＋m·7；系统机械能守恒：½M(6t)²＋½m(2t)²＝½M·v轨′²＋½m·7²＋mg·2R。",
                 latex="M a_{2} t + m a_{1} t = M v_{2p} + m v_{1}",
                 sympy="(M*a2*t + m*a1*t - M*v2p - m*v1) + (Rational(1,2)*M*(a2*t)**2 + Rational(1,2)*m*(a1*t)**2 - Rational(1,2)*M*v2p**2 - Rational(1,2)*m*v1**2 - m*g*2*R)",
                 l2="动量式 kg·m/s；能量式 J",
                 l4="两式同列，equation 记残差和。7 m/s 是离开 Q 瞬间的合速度，Q 点处它沿水平方向；漏 mg·2R 会把 L 算大约 20 m（E-13）",
                 laws=["L-12", "L-09"]),
            dict(pid="B-20-S10", title="t=1.5 s（舍 3.17 s），L=4.5 m", kind="discussion", score=1,
                 stmt="联立得 12t²−56t＋57＝0，t＝1.5 s 或 19/6 s。取 19/6 时 v轨′≈18.3 m/s＞7 m/s，物块比轨道慢、相对轨道后退，不可能从 Q 点离开，舍去。故 L＝2t²＝4.5 m。",
                 latex="L = \\frac{9}{2}",
                 sympy="(L - Rational(9,2)) + (t - Rational(3,2))",
                 l2="m；s",
                 l4="两根都满足方程，只有 1.5 s 符合「物块从 Q 点离开」的过程；取另一根得 L≈20 m。只写 4.5 不写单位 m 本步 0 分（E-07）",
                 val={"symbol": "L", "number": 4.5, "exact": "9/2", "unit": "m",
                      "direction": None, "sig_figs": 2},
                 laws=["L-01", "L-12"]),
        ],
    }
    for st, d in zip(cfg["steps"], [[], [1], [2], [], [4], [5], [6], [7], [8], [9]]):
        st["deps"] = d
    build(cfg)


# ---------------------------------------------------------------- A-02（全符号 + 多解舍根）

def a02():
    """2022 全国乙 25：27 题里唯一真多解题（S12 舍根）。

    同时踩两个坑：全符号（L1 只能 na）+ 图 (b) 读数（B 碰前 1.2v₀ 只在图上）。
    1.2：读数逐条进 figures[fig_no=2].provides（value=null，符号量写 text），
    given 里 v0/v2 标 source=figure。改任一读数 → input_sha256 失配。
    """
    stem = ("如图（a），一质量为 m 的物块 A 与轻质弹簧连接，静止在光滑水平面上；物块 B 向 A 运动，t＝0 时与弹簧接触，"
            "到 t＝2t₀ 时与弹簧分离，第一次碰撞结束，A、B 的 v-t 图像如图（b）所示。已知从 t＝0 到 t＝t₀ 时间内，"
            "物块 A 运动的距离为 0.36v₀t₀。A、B 分离后，A 滑上粗糙斜面，然后滑下，与一直在水平面上运动的 B 再次碰撞，"
            "之后 A 再次滑上斜面，达到的最高点与前一次相同。斜面倾角为 θ（sin θ＝0.6），与水平面光滑连接。"
            "碰撞过程中弹簧始终处于弹性限度内。求"
            "(1)第一次碰撞过程中，弹簧弹性势能的最大值；"
            "(2)第一次碰撞过程中，弹簧压缩量的最大值；"
            "(3)物块 A 与斜面间的动摩擦因数。")
    cfg = {
        "meta": {"answer_id": "A-02", "question_id": "A-02", "group": "A",
                 "source": "2022 全国乙卷", "question_no": 25, "full_score": 20,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T13:35:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [
                {"fig_no": 1,
                 "caption": "图 (a)：物块 A 与轻质弹簧相连静置于光滑水平面，物块 B 向其运动；原文无图题",
                 "caption_source": "none", "is_required": False},
                {"fig_no": 2,
                 "caption": "图 (b)：A、B 的 v–t 图（纵轴以 v₀ 为单位）。四处读数（B 碰前 1.2v₀、t₀ 处交于 v₀、2t₀ 处 A 为 2v₀、B 为 0.8v₀）"
                            "题干文字未给，逐条登记在 provides；原文无图题",
                 "caption_source": "human", "is_required": True,
                 "provides": [
                     {"symbol": "v2", "value": None, "unit": "m/s",
                      "read_from": "图 (b) 纵轴 t＝0 处 B 的截距",
                      "text": "由图 (b) 纵轴 t＝0 处读出 B 的碰前速度为 1.2v₀（符号读数，无数值）"},
                     {"symbol": "v0", "value": None, "unit": "m/s",
                      "read_from": "图 (b) t＝t₀ 处 A、B 两线的交点",
                      "text": "由图 (b) 读出 t＝t₀ 时两线交于 v₀，即弹簧压缩最短时两者共速（v₀ 同时是全图的纵轴单位）"},
                     {"symbol": "v1p", "value": None, "unit": "m/s",
                      "read_from": "图 (b) 纵轴 t＝2t₀ 处 A 的取值",
                      "text": "由图 (b) 读出 t＝2t₀ 时 A 的速度为 2v₀（分离后 A 的速度）"},
                     {"symbol": "v2p", "value": None, "unit": "m/s",
                      "read_from": "图 (b) 纵轴 t＝2t₀ 处 B 的取值",
                      "text": "由图 (b) 读出 t＝2t₀ 时 B 的速度为 0.8v₀（分离后 B 的速度）"},
                 ]},
            ],
            "subquestions": [
                {"no": "(1)", "text": "第一次碰撞过程中弹簧弹性势能的最大值。", "score": 6},
                {"no": "(2)", "text": "第一次碰撞过程中弹簧压缩量的最大值。", "score": 4},
                {"no": "(3)", "text": "物块 A 与斜面间的动摩擦因数。", "score": 10},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "物块 A", "mass_symbol": "m",
                 "note": "与轻质弹簧连接，静止在光滑水平面上；质量 m"},
                {"id": "obj2", "name": "物块 B", "mass_symbol": "M",
                 "note": "向 A 运动；题干未给质量，由动量守恒反解 M＝5m"},
                {"id": "obj3", "name": "轻质弹簧", "mass_symbol": "Mspring",
                 "note": "轻质（质量不计），只提供弹力与弹性势能；始终在弹性限度内"},
                {"id": "obj4", "name": "粗糙斜面", "mass_symbol": "Mface",
                 "note": "倾角 θ（sinθ＝0.6、cosθ＝0.8），与水平面光滑连接；质量远大于物块，视为固定"},
            ],
            "given": [
                {"symbol": "m", "value": None, "unit": "kg", "text": "物块 A 的质量 m（符号量）"},
                {"symbol": "M", "value": None, "unit": "kg", "text": "物块 B 的质量（题干未给，由动量守恒反解）"},
                {"symbol": "v0", "value": None, "unit": "m/s", "source": "figure",
                 "text": "速度以 v₀ 为单位，全题无一个数值；v₀ 由 t₀ 处两线交点读出（见 fig_no=2 的 provides）"},
                {"symbol": "v2", "value": None, "unit": "m/s", "source": "figure",
                 "text": "【图 (b) 读出】B 的碰前速度为 1.2v₀；题干文字未给（见 fig_no=2 的 provides 与 T05a2 的 D1 条）"},
                {"symbol": "t1", "value": None, "unit": "s",
                 "text": "0 到 t₀ 的时间（原文 t₀，按 T09 归一为 t1＝第一段过程时间）"},
                {"symbol": "s1", "value": None, "unit": "m",
                 "text": "0~t₀ 内 A 运动的距离：s_A＝0.36v₀t₀（题给 0.36 为纯数）"},
                {"symbol": "theta", "value": None, "unit": "rad", "text": "斜面倾角 θ，sinθ＝0.6（cosθ＝0.8）"},
            ],
            "process_segments": [
                {"no": 1, "name": "B 压缩弹簧（0→t₀）", "start": "t＝0，B 与弹簧接触",
                 "end": "t＝t₀，两者共速 v₀、压缩量最大"},
                {"no": 2, "name": "回弹分离（t₀→2t₀）", "start": "t＝t₀", "end": "t＝2t₀，弹簧恢复原长，A 以 2v₀ 向右、B 以 0.8v₀ 向右"},
                {"no": 3, "name": "A 沿斜面上滑", "start": "A 以 2v₀ 滑上斜面", "end": "A 到达最高点（速度为零）"},
                {"no": 4, "name": "A 下滑回水平面", "start": "A 从最高点下滑", "end": "A 回到水平面，以 v_A′ 向左运动"},
                {"no": 5, "name": "第二次碰撞与再次上滑", "start": "A 与 B 再次碰撞", "end": "A 以 2v₀ 再次上滑到同一最高点"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "Ep", "text": "弹簧弹性势能的最大值"},
                {"no": "(2)", "quantity": "ds", "text": "弹簧压缩量的最大值"},
                {"no": "(3)", "quantity": "mu", "text": "A 与斜面间的动摩擦因数"},
            ],
            "assumptions": [
                "水平面光滑；斜面与水平面光滑连接，连接处无能量损失",
                "弹簧轻质，碰撞过程中始终在弹性限度内；t₀ 时两者共速，压缩量最大",
                "物块 B 的质量题干未给，由动量守恒反解 M＝5m",
                "取水平向右为正方向；A 沿斜面上滑后返回时速度方向向左（第二次碰前 v₁ 取大小）",
                "图 (b) 的四处读数（B 碰前 1.2v₀、t₀ 处交于 v₀、2t₀ 处 A 为 2v₀、B 为 0.8v₀）只在图上，题干文字未给；1.2 起登记在 figures[fig_no=2].provides，given 的 v0/v2 标 source=figure",
                "sinθ＝0.6、cosθ＝0.8；第 (3) 问用「最高点与前一次相同」反推第二次碰后 A 的速度大小仍为 2v₀",
            ],
        },
        # 全题只有一个数值：μ＝0.45。其余全是符号 → L1 只有 S15 可回代
        "nums": {"mu": 0.45},
        "allowed_symbols": ["m", "M", "v0", "v2", "t1", "s1", "s2", "ds", "Ep",
                            "v1", "v1p", "v2p", "mu", "g", "L", "Fnet"],
        "prior": "high",
        "reason": "金标参考解：全符号 + 二次方程舍根；L1 仅 μ=0.45 一步可回代、其余 na，L2 逐式手判；20/20 满分，未触归零点",
        "steps": [
            dict(pid="A-02-S01", title="从 v–t 图读出 B 的碰前速度", kind="judgment", score=1,
                 stmt="图 (b)：B 的初速度为 1.2v₀；t₀ 处两线相交于 v₀，即弹簧压缩最短时两者共速。这两个读数题干文字未给。",
                 crit=dict(expr="v2", expected="Rational(6,5)*v0", comparator="eq",
                           text="由图 (b) 纵轴 t＝0 处读出 B 的碰前速度为 1.2v₀；t₀ 处两线交于 v₀，即弹簧压缩最短时两者共速。"),
                 l2="m/s",
                 l4="读图错则本问后续级联失效（E-20 归零点）：把 B 初速读成 v₀ 会得 M＝m，Ep 与压缩量全错",
                 val={"symbol": "v2", "number": None, "exact": "6/5*v0", "unit": "m/s",
                      "direction": None, "sig_figs": None},
                 laws=["L-12"]),
            dict(pid="A-02-S02", title="动量守恒解质量比", kind="equation", score=2,
                 stmt="弹簧压缩最短时两者共速：M·1.2v₀＝(M＋m)v₀ —— 弹力是内力，水平面光滑，系统水平动量守恒。",
                 latex="M \\cdot \\frac{6}{5} v_{0} = (M + m) v_{0}",
                 sympy="M*Rational(6,5)*v0 - (M + m)*v0",
                 l2="两边均为 kg·m/s",
                 l4="共速时刻即压缩量最大时刻（相对速度为零）；用能量式代替动量式会多一个未知量 Ep",
                 laws=["L-12"]),
            dict(pid="A-02-S03", title="M = 5m", kind="value", score=1,
                 stmt="约去 v₀：1.2M＝M＋m ⇒ M＝5m，即 B 的质量是 A 的 5 倍。",
                 latex="M = 5 m",
                 sympy="M - 5*m",
                 l2="kg",
                 l4="此式是后续全部计算的钥匙；质量比颠倒（m＝5M）会让 Ep 与压缩量同时错",
                 val={"symbol": "M", "number": None, "exact": "5*m", "unit": "kg",
                      "direction": None, "sig_figs": None},
                 laws=["L-12"]),
            dict(pid="A-02-S04", title="动能损失＝最大弹性势能", kind="equation", score=1,
                 stmt="压缩最短时动能损失全部转为弹性势能：Ep＝½M(1.2v₀)²−½(M＋m)v₀²。",
                 latex="E_{p} = \\frac{1}{2} M (1.2 v_{0})^{2} - \\frac{1}{2} (M + m) v_{0}^{2}",
                 sympy="Ep - (Rational(1,2)*M*(Rational(6,5)*v0)**2 - Rational(1,2)*(M + m)*v0**2)",
                 l2="J",
                 l4="弹簧压缩过程无摩擦，机械能守恒；「动能损失＝弹性势能」的文字表述亦给分",
                 laws=["L-09", "L-12"]),
            dict(pid="A-02-S05", title="Ep = 0.6mv₀²", kind="value", score=1,
                 stmt="代入 M＝5m：Ep＝½·5m·1.44v₀²−½·6m·v₀²＝3.6mv₀²−3mv₀²＝0.6mv₀²。",
                 latex="E_{p} = \\frac{3}{5} m v_{0}^{2}",
                 sympy="Ep - Rational(3,5)*m*v0**2",
                 l2="J",
                 l4="结果不再含 M；未化简也给满分（判分口径），但必须写成 v₀² 量纲，不能留 1.2² 的小数",
                 val={"symbol": "Ep", "number": None, "exact": "3/5*m*v0^2", "unit": "J",
                      "direction": None, "sig_figs": None},
                 laws=["L-09"]),
            dict(pid="A-02-S06", title="压缩量＝两图线间面积（质心匀速）", kind="judgment", score=2,
                 stmt="0~t₀ 内压缩量的最大值等于两条 v–t 线所夹面积；等价依据是「系统合外力为零 ⇒ 质心匀速 v₀」，故 m·s_A＋5m·s_B＝6m·v₀t₀。",
                 crit=dict(expr="Fnet", expected=0, comparator="eq",
                           text="系统水平方向合外力为零，故质心匀速 v₀；压缩量最大值等于两条 v–t 线所夹面积。"),
                 l2="N（水平方向合外力为零）",
                 l4="两种说法都要落到「质心匀速」这个依据上；只说「面积」不解释，判分口径给 1 分（满分 2 分）",
                 laws=["L-12"]),
            dict(pid="A-02-S07", title="质心位移定 s_B", kind="value", score=1,
                 stmt="质心匀速：m·s_A＋5m·s_B＝6m·v₀t₀，代入 s_A＝0.36v₀t₀ 得 s_B＝1.128v₀t₀。",
                 latex="m s_{1} + 5 m s_{2} = 6 m v_{0} t_{1}",
                 sympy="m*s1 + 5*m*s2 - 6*m*v0*t1",
                 l2="kg·m",
                 l4="系数 5、6 来自 M＝5m 与总质量 6m；把 s_A 当成压缩量会直接得 0.36v₀t₀（错）",
                 val={"symbol": "s2", "number": None, "exact": "141/125*v0*t1", "unit": "m",
                      "direction": None, "sig_figs": None},
                 laws=["L-12"]),
            dict(pid="A-02-S08", title="Δs = 0.768v₀t₀", kind="value", score=1,
                 stmt="压缩量最大值＝两物块位移之差：Δs＝s_B−s_A＝1.128v₀t₀−0.36v₀t₀＝0.768v₀t₀。",
                 latex="\\Delta s = s_{2} - s_{1}",
                 sympy="ds - s2 + s1",
                 l2="m",
                 l4="未减 s_A 不得分：面积法里 s_A 是 A 的位移，不是零；写成 0.77v₀t₀ 亦可",
                 val={"symbol": "ds", "number": None, "exact": "96/125*v0*t1", "unit": "m",
                      "direction": None, "sig_figs": None},
                 laws=["L-01", "L-12"]),
            dict(pid="A-02-S09", title="由「最高点相同」定第二次碰后 A 的速度", kind="judgment", score=1,
                 stmt="A 第二次滑上斜面达到的最高点与前一次相同 ⇒ 第二次碰后 A 的速度大小仍为 2v₀、方向水平向右（沿斜面向上）。2v₀ 由图 (b) 在 2t₀ 处读出，也可由 5:1 弹性碰撞算出。",
                 crit=dict(expr="v1p", expected="2*v0", comparator="eq",
                           text="A 第二次滑上斜面达到的最高点与前一次相同，故第二次碰后 A 的速度大小仍为 2v₀、方向水平向右。"),
                 l2="m/s",
                 l4="「最高点相同」只给速度大小，方向由「再次滑上斜面」确定为向右；不写这句而直接代 2v₀，后续错时无法补救",
                 val={"symbol": "v1p", "number": None, "exact": "2*v0", "unit": "m/s",
                      "direction": "+x", "sig_figs": None},
                 laws=["L-09", "L-12"]),
            dict(pid="A-02-S10", title="第二次碰撞的动量守恒", kind="equation", score=2,
                 stmt="碰前：B 以 0.8v₀ 向右（第一次碰后速度，由 M·1.2v₀＝M·0.8v₀＋m·2v₀ 或图上读出）、A 以 v_A′ 向左；碰后 A 以 2v₀ 向右、B 以 v_B′ 向右：M·0.8v₀−m·v_A′＝m·2v₀＋M·v_B′。",
                 latex="M \\cdot \\frac{4}{5} v_{0} - m v_{1} = m v_{1p} + M v_{2p}",
                 sympy="M*Rational(4,5)*v0 - m*v1 - (m*v1p + M*v2p)",
                 l2="kg·m/s",
                 l4="A 碰前速度方向向左，故取负号；这一项符号错是本题最典型的失分点（E-06，本步 0 分）",
                 laws=["L-12"]),
            dict(pid="A-02-S11", title="第二次碰撞的动能守恒", kind="equation", score=2,
                 stmt="两物块在水平面上弹性碰撞：½M(0.8v₀)²＋½m·v_A′²＝½m(2v₀)²＋½M·v_B′²。",
                 latex="\\frac{1}{2} M (\\frac{4}{5} v_{0})^{2} + \\frac{1}{2} m v_{1}^{2} = \\frac{1}{2} m v_{1p}^{2} + \\frac{1}{2} M v_{2p}^{2}",
                 sympy="Rational(1,2)*M*(Rational(4,5)*v0)**2 + Rational(1,2)*m*v1**2 - Rational(1,2)*m*v1p**2 - Rational(1,2)*M*v2p**2",
                 l2="J",
                 l4="弹簧已分离，第二次是直接碰撞（无弹簧储能），故用动能守恒；与 S10 重复写动量守恒不重复给分",
                 laws=["L-09", "L-12"]),
            dict(pid="A-02-S12", title="v_A′=v₀，另一解舍去", kind="discussion", score=1,
                 stmt="两式联立消去 v_B′ 得 v_A′²＋v₀v_A′−2v₀²＝0，即 (v_A′−v₀)(v_A′＋2v₀)＝0：v_A′＝v₀ 或 v_A′＝−2v₀。后者表示 A 仍以 2v₀ 向右运动，即 A 没有从斜面返回，与「再次碰撞」的前提矛盾，舍去。",
                 latex="v_{1}^{2} + v_{0} v_{1} - 2 v_{0}^{2} = 0",
                 sympy="v1**2 + v0*v1 - 2*v0**2",
                 l2="m²/s²",
                 l4="两个根都满足方程，只有 v₀ 符合过程（解集退化为单解，value 单槽够用）。判分口径：只给一个解未说明给 1 分，两解都写未取舍也给 1 分（本步满分 1 分）【待裁定】",
                 val={"symbol": "v1", "number": None, "exact": "v0", "unit": "m/s",
                      "direction": "-x", "sig_figs": None},
                 laws=["L-12", "L-09"]),
            dict(pid="A-02-S13", title="上滑动能定理", kind="equation", score=2,
                 stmt="A 以 2v₀ 沿斜面向上滑行 L 到最高点：−μmgLcosθ−mgLsinθ＝0−½m(2v₀)²，其中 cosθ＝4/5、sinθ＝3/5。",
                 latex="- \\mu m g L \\cdot \\frac{4}{5} - m g L \\cdot \\frac{3}{5} = 0 - \\frac{1}{2} m (2 v_{0})^{2}",
                 sympy="-mu*m*g*L*Rational(4,5) - m*g*L*Rational(3,5) - (0 - Rational(1,2)*m*(2*v0)**2)",
                 l2="各项均为 J",
                 l4="摩擦力与重力分量都做负功；sinθ 与 cosθ 配错会得 μ≠0.45（判分口径扣 1 分）",
                 laws=["L-08", "L-05"]),
            dict(pid="A-02-S14", title="下滑动能定理", kind="equation", score=1,
                 stmt="A 从最高点滑回水平面，末速 v₀：mgLsinθ−μmgLcosθ＝½mv₀²−0。",
                 latex="m g L \\cdot \\frac{3}{5} - \\mu m g L \\cdot \\frac{4}{5} = \\frac{1}{2} m v_{0}^{2}",
                 sympy="m*g*L*Rational(3,5) - mu*m*g*L*Rational(4,5) - Rational(1,2)*m*v0**2",
                 l2="J",
                 l4="与上滑式的符号相反（重力做正功、摩擦仍做负功），这是本步的采分关键",
                 laws=["L-08", "L-05"]),
            dict(pid="A-02-S15", title="μ = 0.45", kind="value", score=1,
                 stmt="两式相加得 1.2mgL＝2.5mv₀²，相减得 1.6μmgL＝1.5mv₀²，相比得 μ＝0.45（纯数，与 g、v₀ 无关）。",
                 latex="\\mu = \\frac{9}{20}",
                 sympy="mu - Rational(9,20)",
                 l2="无量纲",
                 l4="只有结果无过程，最高给本步 1 分；μ 是本题唯一的数值，也是全题唯一能 L1 回代的一步",
                 val={"symbol": "mu", "number": 0.45, "exact": "9/20", "unit": "1",
                      "direction": None, "sig_figs": 2},
                 laws=["L-08"]),
        ],
    }
    for st, d in zip(cfg["steps"],
                     [[], [1], [2], [3], [4], [3], [6], [7], [8], [9], [10], [11], [12], [13], [14]]):
        st["deps"] = d
    build(cfg)


# ---------------------------------------------------------------- A-01

def a01():
    """2021 全国甲 24：全符号 + 50 个减速带 + 不等式；L1 全 na。

    符号迁移（白名单无 ΔE/ΔE₀，也不许新登记）：
      ΔE  → W      （每过一次带损失的机械能＝克服减速带阻力做的功）
      ΔE₀ → Qheat （前 30 带上平均每次耗散的能量）
      s   → s1     （小车在水平面上的对地位移）
    """
    stem = ("如图，一倾角为 θ 的光滑斜面上有 50 个减速带（图中未完全画出），相邻减速带间的距离均为 d，"
            "减速带的宽度远小于 d；一质量为 m 的无动力小车（可视为质点）从距第一个减速带 L 处由静止释放。"
            "已知小车通过减速带损失的机械能与到达减速带时的速度有关。观察发现，小车通过第 30 个减速带后，"
            "在相邻减速带间的平均速度均相同。小车通过第 50 个减速带后立刻进入与斜面光滑连接的水平地面，"
            "继续滑行距离 s 后停下。已知小车与地面间的动摩擦因数为 μ，重力加速度大小为 g。")
    cfg = {
        "meta": {"answer_id": "A-01", "question_id": "A-01", "group": "A",
                 "source": "2021 全国甲卷", "question_no": 24, "full_score": 12,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T19:05:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [{"fig_no": 1,
                         "caption": "倾角 θ 的斜面上等间距 d 排列的减速带（宽远小于 d），小车自距第一带 L 处释放；"
                                    "原文无图题，图只示意排列，不作为读数来源",
                         "caption_source": "none", "is_required": False}],
            "subquestions": [
                {"no": "(1)", "text": "小车通过第 30 个减速带后，经过每一个减速带时损失的机械能。", "score": 3},
                {"no": "(2)", "text": "小车通过前 30 个减速带的过程中在每一个减速带上平均损失的机械能。", "score": 6},
                {"no": "(3)", "text": "若小车在前 30 个减速带上平均每一个损失的机械能大于之后每一个减速带上损失的机械能，"
                                      "L 应满足什么条件？", "score": 3},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "无动力小车", "mass_symbol": "m",
                 "note": "质量 m，视为质点；自距第一带 L 处静止释放，只在斜面与水平面上运动"},
                {"id": "obj2", "name": "减速带", "mass_symbol": "m",
                 "note": "斜面上共 50 个，等间距 d，宽度远小于 d；过带时损失机械能，不改变运动方向"},
            ],
            "given": [
                {"symbol": "theta", "value": None, "unit": "rad", "text": "斜面倾角 θ（符号量）"},
                {"symbol": "d", "value": None, "unit": "m", "text": "相邻减速带间的距离均为 d（符号量）"},
                {"symbol": "L", "value": None, "unit": "m", "text": "小车从距第一个减速带 L 处由静止释放（符号量）"},
                {"symbol": "s1", "value": None, "unit": "m",
                 "text": "过第 50 带后进入水平地面，继续滑行距离 s 后停下 —— 本档把原文的 s 记作 s1（s 不在符号白名单）"},
                {"symbol": "mu", "value": None, "unit": "1", "text": "小车与地面间的动摩擦因数 μ（符号量）"},
                {"symbol": "m", "value": None, "unit": "kg", "text": "小车质量 m（符号量）"},
                {"symbol": "g", "value": None, "unit": "m/s^2", "text": "重力加速度大小 g（符号量）"},
            ],
            "process_segments": [
                {"no": 1, "name": "斜面下滑（第 1 带至第 30 带）", "start": "小车自距第 1 带 L 处静止释放",
                 "end": "通过第 30 个减速带，此后相邻带间平均速度均相同"},
                {"no": 2, "name": "第 31～50 带（速度序列重复段）", "start": "通过第 30 带后",
                 "end": "通过第 50 带，立刻进入水平地面"},
                {"no": 3, "name": "水平地面滑行", "start": "过第 50 带进入水平地面", "end": "滑行 s 后停下"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "W", "text": "第 30 带后每过一次带损失的机械能"},
                {"no": "(2)", "quantity": "Qheat", "text": "前 30 带上平均每次损失的机械能"},
                {"no": "(3)", "quantity": "L", "text": "满足「前 30 带平均损失更大」的 L 范围"},
            ],
            "assumptions": [
                "斜面光滑：斜面上只有重力做功，机械能损失全部发生在减速带上，带宽远小于 d 故过带位移可忽略",
                "第 30 带后各段平均速度相同且段长同为 d ⇒ 每段用时相同、两端速度各自重复 ⇒ 每带损失相同（与速度大小无关）",
                "本题不给任何数值，L1 全步 na；不假设 g、θ 的具体值来凑回代",
                "符号迁移：ΔE 记作 W、ΔE₀ 记作 Qheat、原文 s 记作 s1 —— 白名单无这三个记号，未新登记（见回执 §需上报）",
                "第 50 带与水平面之间没有第 51 段：斜面总长按 L＋49d 计",
            ],
        },
        "nums": {},
        "allowed_symbols": ["m", "g", "d", "L", "theta", "mu", "s1", "W", "Qheat", "vavg"],
        "prior": "high",
        "reason": "金标参考解：全符号 + 50 带分段 + 不等式；L1 全步 na，L2 逐式手判；12/12 满分，未触归零点",
        "steps": [
            dict(pid="A-01-S01", title="判定第 30 带后每带损失相同", kind="judgment", score=1,
                 stmt="第 30 个减速带之后，相邻减速带间的平均速度均相同；各段长度同为 d，故每段用时相同，"
                      "「到达带时」与「过带后」的速度序列各自重复。每段速度变化相同 ⇒ 每过一次带损失的机械能相同。",
                 crit=dict(expr="vavg", expected=None, comparator="qualitative",
                           text="由「相邻段平均速度相同、段长相同」推得每段用时相同、两端速度各自重复，故每带损失相同 —— "
                                "判的是速度序列重复，不是「速度相同」四个字。"),
                 l2="m/s（平均速度 v̄）",
                 l4="只写「速度相同」未推出每段损失相同仍给分（口径）；完全不提则后续全错，故本步单列 1 分",
                 laws=["L-08"]),
            dict(pid="A-01-S02", title="每带损失 ΔE = mgd sinθ", kind="equation", score=2,
                 stmt="第 30 带后各段速度序列重复，故每段动能变化为零；该段重力势能减少 mgd sinθ 全部在过带时损失："
                      "W＝mgd sinθ（W 即原文 ΔE）。",
                 latex="\\Delta E = m g d \\sin\\theta",
                 sympy="W - m*g*d*sin(theta)",
                 l2="kg·m/s²·m＝J",
                 l4="漏 sinθ、写成 mgd 或 mgL 不得分；无说明给 1 分（口径）",
                 val={"symbol": "W", "number": None, "exact": "m*g*d*sin(theta)", "unit": "J",
                      "direction": None, "sig_figs": None},
                 laws=["L-08"]),
            dict(pid="A-01-S03", title="全程动能定理", kind="equation", score=3,
                 stmt="从释放到水平面停下列全程动能定理：重力做正功 mg(L＋49d)sinθ，前 30 带损失 30ΔE₀、"
                      "后 20 带损失 20ΔE，水平段摩擦做负功 −μmgs；初、末动能均为零。",
                 latex="m g (L + 49 d) \\sin\\theta - 30 \\Delta E_{0} - 20 \\Delta E - \\mu m g s = 0",
                 sympy="m*g*(L+49*d)*sin(theta) - 30*Qheat - 20*W - mu*m*g*s1",
                 l2="各项均为 J",
                 l4="位移写 50d 扣 1（第 50 带之后就是水平面，没有第 51 段）；漏 20ΔE 扣 2；末动能 0 项移项等价给分。"
                    "本档 Qheat＝ΔE₀、W＝ΔE",
                 laws=["L-08"]),
            dict(pid="A-01-S04", title="ΔE₀ 是前 30 带总损失除以 30", kind="judgment", score=1,
                 stmt="前 30 个减速带上的总损失除以 30 才是「平均每一个」的损失 ΔE₀；除以 50 会把后 20 带也算进来，"
                      "是整题归零高发点。",
                 crit=dict(expr="30*Qheat", expected="m*g*(L+29*d)*sin(theta) - mu*m*g*s1", comparator="eq",
                           text="ΔE₀ 的定义是前 30 个减速带上的总损失除以 30 —— 30ΔE₀＝mg(L＋29d)sinθ−μmgs，不是除以 50。"),
                 l2="J",
                 l4="除以 50 不得分（E-01 整题归零高发点）",
                 laws=["L-08"]),
            dict(pid="A-01-S05", title="解出 ΔE₀", kind="equation", score=2,
                 stmt="把 20ΔE＝20mgd sinθ 移项：30ΔE₀＝mg(L＋49d−20d)sinθ−μmgs＝mg(L＋29d)sinθ−μmgs，"
                      "故 ΔE₀＝[mg(L＋29d)sinθ−μmgs]/30。",
                 latex="\\Delta E_{0} = \\frac{m g (L + 29 d) \\sin\\theta - \\mu m g s}{30}",
                 sympy="30*Qheat - (m*g*(L+29*d)*sin(theta) - mu*m*g*s1)",
                 l2="J",
                 l4="等价形式（先由水平段 −μmgs＝0−½mv₁² 求 v₁ 再回代）给满分；只列式未解出给 1 分",
                 val={"symbol": "Qheat", "number": None,
                      "exact": "(m*g*(L+29*d)*sin(theta)-mu*m*g*s1)/30", "unit": "J",
                      "direction": None, "sig_figs": None},
                 laws=["L-08"]),
            dict(pid="A-01-S06", title="判据：ΔE₀ > ΔE", kind="critical", score=1,
                 stmt="「前 30 个减速带上平均每一个损失的机械能大于之后每一个减速带上损失的机械能」即 ΔE₀＞ΔE；"
                      "这是第 (3) 问的不等式起点，本身不给 L 的范围。",
                 crit=dict(expr="Qheat", expected="W", comparator="gt",
                           text="前 30 带的平均损失 ΔE₀ 大于之后每带的损失 ΔE，即 ΔE₀＞ΔE；用文字「平均损失更大」表述亦可。"),
                 l2="J",
                 l4="用文字「平均损失更大」表述亦可（口径）；本步只判不等号方向，不要求解出 L",
                 laws=["L-08"]),
            dict(pid="A-01-S07", title="解不等式得 L > d + μs/sinθ", kind="critical", score=2,
                 stmt="把 ΔE₀、ΔE 代入 ΔE₀＞ΔE，约去 mg：L＋29d−μs/sinθ＞30d ⇒ L＞d＋μs/sinθ。",
                 crit=dict(expr="L", expected="d + mu*s1/sin(theta)", comparator="gt",
                           text="ΔE₀＞ΔE 等价于 mg(L＋29d)sinθ−μmgs＞30mgd sinθ，约去 mg sinθ 得 L＞d＋μs/sinθ。"),
                 l2="m（d 与 μs/sinθ 均为长度）",
                 l4="不等号方向错扣 1；量纲不对不得分（口径）",
                 laws=["L-08"]),
        ],
    }
    build(cfg)


# ---------------------------------------------------------------- A-03

def a03():
    """2023 全国乙 25：全符号 + 连续弹性碰撞 + 归纳与范围；L1 全 na。

    符号迁移：原文 l（盘到端口距离、管长 20l 的单位）→ L。
    v1p/v2p 表示「最近一次碰撞后的速度」：S02～S04 记第一次，S10 记第二次。
    n 借用为「间隔序号」（1..4），白名单无序号符号。
    """
    stem = ("如图，一竖直固定的长直圆管内有一质量为 M 的静止薄圆盘，圆盘与管的上端口距离为 l，圆管长度为 20l。"
            "一质量为 m＝M/3 的小球从管的上端口由静止下落，并撞在圆盘中心，圆盘向下滑动，所受滑动摩擦力与其所受重力大小相等。"
            "小球在管内运动时与管壁不接触，圆盘始终水平，小球与圆盘发生的碰撞均为弹性碰撞且碰撞时间极短。"
            "不计空气阻力，重力加速度大小为 g。求")
    cfg = {
        "meta": {"answer_id": "A-03", "question_id": "A-03", "group": "A",
                 "source": "2023 全国乙卷", "question_no": 25, "full_score": 20,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T19:10:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [{"fig_no": 1,
                         "caption": "竖直长直圆管（长 20l）内有薄圆盘，盘距上端口 l，小球自端口静止下落；原文无图题",
                         "caption_source": "none", "is_required": False}],
            "subquestions": [
                {"no": "(1)", "text": "第一次碰撞后瞬间小球和圆盘的速度大小。", "score": 7},
                {"no": "(2)", "text": "在第一次碰撞到第二次碰撞之间，小球与圆盘间的最远距离。", "score": 6},
                {"no": "(3)", "text": "圆盘在管内运动过程中，小球与圆盘碰撞的次数。", "score": 7},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "小球", "mass_symbol": "m",
                 "note": "质量 m＝M/3，自管口静止下落；与盘弹性碰撞，碰后做竖直上抛/下落"},
                {"id": "obj2", "name": "薄圆盘", "mass_symbol": "M",
                 "note": "质量 M，初始静止于端口下 l 处；所受滑动摩擦力与重力等大，碰后匀速下滑"},
                {"id": "obj3", "name": "长直圆管", "mass_symbol": "M",
                 "note": "竖直固定，长 20l；只提供约束，不参与动量交换"},
            ],
            "given": [
                {"symbol": "M", "value": None, "unit": "kg", "text": "薄圆盘质量 M（符号量）"},
                {"symbol": "m", "value": None, "unit": "kg", "text": "小球质量 m＝M/3（比值给定，无具体数值）"},
                {"symbol": "L", "value": None, "unit": "m",
                 "text": "圆盘与管的上端口距离为 l，圆管长度为 20l —— 本档把 l 记作 L，管长即 20L"},
                {"symbol": "g", "value": None, "unit": "m/s^2", "text": "重力加速度大小 g（符号量）"},
            ],
            "process_segments": [
                {"no": 1, "name": "自由下落", "start": "小球自管口由静止下落", "end": "小球到达盘面（速度 v₀＝√(2gL)）"},
                {"no": 2, "name": "第一次弹性碰撞", "start": "球与盘接触的瞬间", "end": "碰后球以 v₀/2 向上、盘以 v₀/2 向下"},
                {"no": 3, "name": "碰后相对运动至第二次碰撞", "start": "第一次碰后瞬间",
                 "end": "球先上抛、回落到碰点后再追 l，追上盘（第二次碰撞）"},
                {"no": 4, "name": "后续碰撞与盘下滑", "start": "第二次碰后", "end": "盘到达管下端，共发生 4 次碰撞"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "v2p", "text": "第一次碰后小球与圆盘的速度大小"},
                {"no": "(2)", "quantity": "ds", "text": "第一次到第二次碰撞之间球与盘的最远距离"},
                {"no": "(3)", "quantity": "n", "text": "盘在管内运动过程中球与盘碰撞的次数"},
            ],
            "assumptions": [
                "取竖直向下为正方向；球碰后速度为负表示反弹向上",
                "盘所受滑动摩擦力与重力等大反向 ⇒ 盘碰后匀速下滑（这是「盘匀速、球匀变速」的成立前提）",
                "碰撞均为弹性碰撞且时间极短：每次碰中动量与动能同时守恒，位置不变",
                "球在管内不与管壁接触，盘始终水平，两者只沿竖直方向运动（一维）",
                "符号迁移：原文 l 记作 L（管长 20L）；v₁′/v₂′ 记作 v1p/v2p 且按「最近一次碰撞后」复用；n 借用为间隔序号（见回执 §需上报）",
            ],
        },
        "nums": {},
        "allowed_symbols": ["m", "M", "g", "L", "v0", "v1", "v2", "v1p", "v2p",
                            "t", "t2", "x", "s1", "s2", "ds", "n"],
        "prior": "high",
        "reason": "金标参考解：全符号 + 连续弹性碰撞 + 位移归纳与管长判据；L1 全步 na，L2 逐式手判；20/20 满分，未触归零点",
        "steps": [
            dict(pid="A-03-S01", title="自由下落求碰前速度", kind="equation", score=2,
                 stmt="小球自管口静止下落 L 到盘面，只有重力做功：v₀²＝2gL，得 v₀＝√(2gL)。",
                 latex="v_{0}^{2} = 2 g L",
                 sympy="v0**2 - 2*g*L",
                 l2="m²/s²",
                 l4="直接写 √(2gl) 也给（口径）",
                 val={"symbol": "v0", "number": None, "exact": "sqrt(2*g*L)", "unit": "m/s",
                      "direction": "-y", "sig_figs": None},
                 laws=["L-02"]),
            dict(pid="A-03-S02", title="碰撞动量守恒", kind="equation", score=2,
                 stmt="取竖直向下为正：碰前球速 v₀、盘静止；碰后球 v₁′、盘 v₂′，m v₀＝m v₁′＋M v₂′。",
                 latex="m v_{0} = m v_{1p} + M v_{2p}",
                 sympy="m*v0 - m*v1p - M*v2p",
                 l2="kg·m/s",
                 l4="未规定正方向但符号自洽不扣（口径）；向下为正，故 v₁′ 解出为负表示球反弹向上",
                 laws=["L-12"]),
            dict(pid="A-03-S03", title="弹性碰撞动能守恒", kind="equation", score=2,
                 stmt="碰撞时间极短、弹性碰撞：½mv₀²＝½mv₁′²＋½Mv₂′²（写「机械能守恒」同等）。",
                 latex="\\frac{1}{2} m v_{0}^{2} = \\frac{1}{2} m v_{1p}^{2} + \\frac{1}{2} M v_{2p}^{2}",
                 sympy="Rational(1,2)*m*v0**2 - Rational(1,2)*m*v1p**2 - Rational(1,2)*M*v2p**2",
                 l2="J",
                 l4="两式联立才能定两个未知量；只列动量式不足以定速度",
                 laws=["L-12", "L-09"]),
            dict(pid="A-03-S04", title="代入 m＝M/3 得两者速度大小", kind="value", score=1,
                 stmt="m＝M/3 代入一动一静弹性碰撞结果：v₁′＝(m−M)/(m＋M)·v₀＝−v₀/2（向上），"
                      "v₂′＝2m/(m＋M)·v₀＝v₀/2（向下），大小均为 √(2gl)/2。",
                 latex="v_{2p} = \\frac{v_{0}}{2}",
                 sympy="v2p - v0/2",
                 l2="m/s",
                 l4="只求一个、或漏「大小」而带负号未说明，给 1 分（口径）；v₁′＝−v₀/2 由同一组式子给出",
                 val={"symbol": "v2p", "number": None, "exact": "v0/2", "unit": "m/s",
                      "direction": "-y", "sig_figs": None},
                 laws=["L-12"]),
            dict(pid="A-03-S05", title="判定共速时相距最远", kind="judgment", score=2,
                 stmt="碰后盘匀速下滑、球先向上后向下做匀变速运动；两者速度相等（同向同速）的瞬间相对速度为零，"
                      "间距由增大转为减小，故此刻相距最远。",
                 crit=dict(expr="v1", expected="v2", comparator="eq",
                           text="间距最大 ⇔ 两者速度相同（同向同速）：此前球相对盘向上、间距增大，此后球速超过盘、间距减小。"),
                 l2="m/s",
                 l4="只说速度相等未说明最远条件给 1 分（口径）；这是第 (2) 问最关键的判断",
                 laws=["L-01"]),
            dict(pid="A-03-S06", title="由速度相等求共速时刻", kind="equation", score=1,
                 stmt="碰后球速 v₁′＋gt、盘速 v₂′（匀速）；令二者相等：−v₀/2＋gt＝v₀/2，得 t＝v₀/g＝√(2gl)/g。",
                 latex="v_{1p} + g t = v_{2p}",
                 sympy="v1p + g*t - v2p",
                 l2="m/s",
                 l4="用相对速度 2·(v₀/2) 求解亦可（口径）；盘受摩擦力与重力等大，故匀速，不加 g t",
                 laws=["L-01", "L-03"]),
            dict(pid="A-03-S07", title="求两者位移：球回到碰点、盘下落 l", kind="equation", score=2,
                 stmt="共速时 t＝v₀/g：球位移 s₁＝v₁′t＋½gt²＝−v₀²/(2g)＋v₀²/(2g)＝0（回到碰点）；"
                      "盘位移 s₂＝v₂′t＝v₀²/(2g)＝l。相对位移 Δs＝s₂−s₁＝l。",
                 latex="\\Delta s = v_{2p} t - (v_{1p} t + \\frac{1}{2} g t^{2})",
                 sympy="ds - (v2p*t - (v1p*t + Rational(1,2)*g*t**2))",
                 l2="m",
                 l4="只算盘、漏球位移扣 1；相对位移 v₀²/2g 一次算得 l 亦满分（口径）",
                 val={"symbol": "ds", "number": None, "exact": "v0^2/(2*g)", "unit": "m",
                      "direction": None, "sig_figs": None},
                 laws=["L-01"]),
            dict(pid="A-03-S08", title="最远距离 = l", kind="discussion", score=1,
                 stmt="Δs＝v₀²/(2g)＝l，故第一次碰撞到第二次碰撞之间小球与圆盘间的最远距离为 l。",
                 latex="\\Delta s = L",
                 sympy="ds - L",
                 l2="m",
                 l4="结果不等于 l 本步 0 分；写成 2l、l/2 这类未取到 l 的中间量不得分；距离为标量，未注明方向不扣（口径）",
                 val={"symbol": "ds", "number": None, "exact": "L", "unit": "m",
                      "direction": None, "sig_figs": None},
                 laws=["L-01"]),
            dict(pid="A-03-S09", title="第二次碰前速度：球 3v₀/2、盘 v₀/2", kind="equation", score=2,
                 stmt="球回到碰点后继续下落追盘：从共速时刻起再经 t₂＝v₀/g，球速增加 gt₂＝v₀、达 3v₀/2，"
                      "盘仍 v₀/2；两者速度差 v₁−v₂＝v₀＝g t₂。",
                 latex="v_{1} - v_{2} = g t_{2}",
                 sympy="v1 - v2 - g*t2",
                 l2="m/s",
                 l4="需体现「球回到碰点后再追 l」（口径）；追及距离 l 与相对加速度 g 也可直接得 t₂＝√(2l/g)",
                 laws=["L-01"]),
            dict(pid="A-03-S10", title="第二次碰后：球静止、盘 v₀", kind="equation", score=1,
                 stmt="第二次碰撞仍为弹性碰撞（m＝M/3、同向）：碰前球 3v₀/2、盘 v₀/2，碰后球静止、盘以 v₀ 下滑。",
                 latex="v_{2p} = v_{0}",
                 sympy="v2p - v0",
                 l2="m/s",
                 l4="速度互换结论正确即给满（口径）；此处 v₁′、v₂′ 记第二次碰后的速度（复用同一对符号）",
                 val={"symbol": "v2p", "number": None, "exact": "v0", "unit": "m/s",
                      "direction": "-y", "sig_figs": None},
                 laws=["L-12", "L-09"]),
            dict(pid="A-03-S11", title="相邻两次碰撞间盘的位移规律 x_n = 2nl", kind="equation", score=2,
                 stmt="每次碰撞后到下次碰撞，两者位移相等：盘匀速、球匀加速，解得相邻两次碰撞间盘的下降量依次为 "
                      "2l、4l、6l、8l，即第 n 个间隔 x_n＝2nl（n＝1,2,3,4）。",
                 latex="x_{n} = 2 n L",
                 sympy="x - 2*n*L",
                 l2="m",
                 l4="只算到第二次未归纳给 1 分（口径）；n 是间隔序号（1..4），不是 A-10 的半径比 —— 白名单无「序号」符号，借用 n",
                 val={"symbol": "x", "number": None, "exact": "2*n*L", "unit": "m",
                      "direction": None, "sig_figs": None},
                 laws=["L-12", "L-01"]),
            dict(pid="A-03-S12", title="累计 21l > 20l，故只碰 4 次", kind="critical", score=2,
                 stmt="盘自端口下 l 处起算：第 1 次碰撞在 l，之后每次再降 2l、4l、6l、8l。前四次碰撞累计 "
                      "1l＋2l＋4l＋6l＝13l，距下端 7l；第五次需再降 8l＞7l，管内已无空间，故共碰撞 4 次。",
                 crit=dict(expr="L + 2*L + 4*L + 6*L + 8*L", expected="20*L", comparator="gt",
                           text="第 5 次碰撞需盘累计下降 l＋2l＋4l＋6l＋8l＝21l，已超过管长 20l，故第 5 次不发生，共碰 4 次。"),
                 l2="m",
                 l4="用 20l 与管长 20l 直接比较扣 1（盘起始距口 l，第 1 次碰撞已用掉 l）（口径）",
                 laws=["L-01"]),
        ],
    }
    build(cfg)


# ---------------------------------------------------------------- A-04

def a04():
    """2024 全国甲 24：声波追及，题面有数值；L1 逐式可回代。

    符号迁移：声速 v₀ → v2（v0 在白名单里是「初速度」，而小车初速为 0）；
    加速段位移 → s1；停止鸣笛时刻 → t（原文未给符号，只有一个「某时刻」）；
    车距出发处 → x。原文解析要点里的「t₃＝30 s」与答案 680 m 不自洽，见回执 §需上报。
    """
    stem = ("为抢救病人，一辆救护车紧急出发，鸣着笛沿水平直路从 t＝0 时由静止开始做匀加速运动，"
            "加速度大小 a＝2 m/s²，在 t₁＝10 s 时停止加速开始做匀速运动，之后某时刻救护车停止鸣笛，"
            "t₂＝41 s 时在救护车出发处的人听到救护车发出的最后的鸣笛声。已知声速 v₀＝340 m/s，求")
    cfg = {
        "meta": {"answer_id": "A-04", "question_id": "A-04", "group": "A",
                 "source": "2024 全国甲卷", "question_no": 24, "full_score": 12,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T19:15:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [],
            "subquestions": [
                {"no": "(1)", "text": "救护车匀速运动时的速度大小。", "score": 4},
                {"no": "(2)", "text": "在停止鸣笛时救护车距出发处的距离。", "score": 8},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "救护车", "mass_symbol": "m",
                 "note": "自 t＝0 由静止匀加速（a＝2 m/s²）10 s，随后匀速；质量不参与计算"},
                {"id": "obj2", "name": "声波", "mass_symbol": "m",
                 "note": "在静止空气中以 340 m/s 匀速传播，不随车运动"},
            ],
            "given": [
                {"symbol": "a", "value": 2, "unit": "m/s^2", "text": "加速度大小 a＝2 m/s²"},
                {"symbol": "t1", "value": 10, "unit": "s", "text": "在 t₁＝10 s 时停止加速开始做匀速运动"},
                {"symbol": "t2", "value": 41, "unit": "s", "text": "t₂＝41 s 时在出发处听到最后的鸣笛声"},
                {"symbol": "v2", "value": 340, "unit": "m/s",
                 "text": "声速 v₀＝340 m/s —— 本档记作 v2（v0 在白名单里指初速度，而小车初速为 0）"},
            ],
            "process_segments": [
                {"no": 1, "name": "匀加速段（0～10 s）", "start": "t＝0 由静止出发", "end": "t₁＝10 s，速度达 20 m/s，位移 100 m"},
                {"no": 2, "name": "匀速段与声波传播", "start": "t₁＝10 s 起匀速",
                 "end": "某时刻 t 停止鸣笛（x＝680 m），最后一声再经 2 s 于 t₂＝41 s 传到出发点"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "v1", "text": "匀速运动时的速度大小"},
                {"no": "(2)", "quantity": "x", "text": "停止鸣笛时车距出发处的距离"},
            ],
            "assumptions": [
                "以出发处为原点、沿车运动方向为正；t＝0 为出发时刻",
                "加速段 a 恒定、t₁＝10 s 后 a＝0；匀速段速度由 v₁＝a t₁ 给出",
                "声波相对地面以 v2＝340 m/s 匀速传播，传播距离等于鸣笛时车到出发处的距离 x",
                "「听到最后的鸣笛声」的时刻 = 停止鸣笛时刻 t ＋ 声波传播时间 x/v2，故 t＋x/v2＝t₂",
            ],
        },
        "nums": {"a": 2.0, "t1": 10.0, "t2": 41.0, "v2": 340.0,
                 "v1": 20.0, "s1": 100.0, "t": 39.0, "x": 680.0},
        "allowed_symbols": ["a", "t1", "t2", "v1", "v2", "s1", "t", "x"],
        "prior": "high",
        "reason": "金标参考解：匀加速＋匀速＋声波传播的时间方程；L1 逐式数值回代，12/12 满分",
        "steps": [
            dict(pid="A-04-S01", title="加速段末速度 v₁ = a t₁", kind="equation", score=2,
                 stmt="0～10 s 匀加速，初速为零：v₁＝a t₁＝2×10＝20 m/s。",
                 latex="v_{1} = a t_{1}",
                 sympy="v1 - a*t1",
                 l2="m/s²·s＝m/s",
                 l4="只写 20 m/s 无公式给 1 分（口径）；a 取 2、t₁ 取 10，不能用 t₂＝41 s 代入",
                 val={"symbol": "v1", "number": 20.0, "exact": "a*t1", "unit": "m/s",
                      "direction": "+x", "sig_figs": 2},
                 laws=["L-01"]),
            dict(pid="A-04-S02", title="匀速运动速度 20 m/s", kind="discussion", score=2,
                 stmt="救护车匀速运动时的速度大小为 20 m/s（方向沿出发点指向远处）。",
                 latex="v_{1} = 20",
                 sympy="v1 - 20",
                 l2="m/s",
                 l4="无单位扣 1（口径）；「大小」已明示，方向可不在答案中重复",
                 val={"symbol": "v1", "number": 20.0, "exact": "a*t1", "unit": "m/s",
                      "direction": "+x", "sig_figs": 2},
                 laws=["L-01"]),
            dict(pid="A-04-S03", title="加速段位移 s₁ = ½at₁²", kind="equation", score=2,
                 stmt="0～10 s 匀加速、初速为零：s₁＝½a t₁²＝½×2×10²＝100 m。",
                 latex="s_{1} = \\frac{1}{2} a t_{1}^{2}",
                 sympy="s1 - Rational(1,2)*a*t1**2",
                 l2="m/s²·s²＝m",
                 l4="漏写则无法建第 (2) 问的位移式（口径）；加速段位移只能用 ½at₁²，不能用 v₁t₁",
                 val={"symbol": "s1", "number": 100.0, "exact": "a*t1^2/2", "unit": "m",
                      "direction": "+x", "sig_figs": 2},
                 laws=["L-01"]),
            dict(pid="A-04-S04", title="匀速段位移与总距离 x", kind="equation", score=2,
                 stmt="设 t 时刻停止鸣笛，则匀速段时间为 t−t₁：x＝s₁＋v₁(t−t₁)＝100＋20(t−10)。",
                 latex="x = s_{1} + v_{1} (t - t_{1})",
                 sympy="x - s1 - v1*(t - t1)",
                 l2="m＋m/s·s＝m",
                 l4="符号含义清楚即可（口径）；t 是「停止鸣笛」的时刻，不是总时间 41 s",
                 val={"symbol": "x", "number": 680.0, "exact": "s1 + v1*(t - t1)", "unit": "m",
                      "direction": "+x", "sig_figs": 3},
                 laws=["L-01"]),
            dict(pid="A-04-S05", title="声波传播时间与总时刻联立", kind="equation", score=3,
                 stmt="最后一声从 x 处传回出发点需 x/v2；听到时刻等于鸣笛时刻加传播时间：t＋x/v2＝t₂，"
                      "即 680/340＋t＝41。",
                 latex="t + \\frac{x}{v_{2}} = t_{2}",
                 sympy="t2 - x/v2 - t",
                 l2="s＋m/(m/s)＝s",
                 l4="唯一难点：发出时刻＋传播时间，写成 41−x/340＝t 等价（口径）",
                 laws=["L-01"]),
            dict(pid="A-04-S06", title="解得 x = 680 m", kind="discussion", score=1,
                 stmt="代入 s₁＝100 m、v₁＝20 m/s、v2＝340 m/s 解 t＋x/340＝41 与 x＝100＋20(t−10)，"
                      "得 t＝39 s、x＝680 m。",
                 latex="x = 680",
                 sympy="x - 680",
                 l2="m",
                 l4="无单位视为结果不完整，给 0.5 分（按整分记则不给）（口径）",
                 val={"symbol": "x", "number": 680.0, "exact": "680", "unit": "m",
                      "direction": "+x", "sig_figs": 3},
                 laws=["L-01"]),
        ],
    }
    build(cfg)


# ---------------------------------------------------------------- A-05

def a05():
    """2025 全国甲 25：全符号 + 圆弧＋弹簧＋动量；L1 全 na。

    符号迁移：Q 的质量 M（第 (3) 问）、M′ 记作 Mp（第 (4) 问）；
    v0＝与弹簧刚接触时的速度；v2＝第 (4) 问 Q 的速度；vc＝共速。
    S10 是总表认定的「合步」（动量＋能量两式一步），note 里留痕。
    """
    stem = ("如图，物块 P 固定在水平面上，其上表面有半径为 R 的圆弧轨道。P 右端与薄板 Q 连在一起，"
            "圆弧轨道与 Q 上表面平滑连接。一轻弹簧的右端固定在 Q 上，另一端自由。质量为 m 的小球自圆弧顶端 "
            "A 点上方的 B 点自由下落，落到 A 点后沿圆弧轨道下滑，小球与弹簧接触后，当速度减小至刚接触时的 1/3 时"
            "弹簧的弹性势能为 2mgR，此时断开 P 和 Q 的连接，Q 从静止开始向右滑动。g 为重力加速度大小，"
            "忽略空气阻力，圆弧轨道及 Q 的上、下表面均光滑，弹簧长度的变化始终在弹性限度内。")
    cfg = {
        "meta": {"answer_id": "A-05", "question_id": "A-05", "group": "A",
                 "source": "2025 全国甲卷", "question_no": 25, "full_score": 20,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T19:20:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [{"fig_no": 1,
                         "caption": "物块 P 上的半径 R 圆弧（顶端 A）、与之相连的薄板 Q、右端固定在 Q 上的水平轻弹簧；"
                                    "原文无图题，几何关系已由文字给全",
                         "caption_source": "none", "is_required": False}],
            "subquestions": [
                {"no": "(1)", "text": "小球从落入圆弧轨道至离开圆弧轨道，重力对其做的功。", "score": 3},
                {"no": "(2)", "text": "小球与弹簧刚接触时速度的大小及 B、A 两点间的距离。", "score": 7},
                {"no": "(3)", "text": "欲使 P 和 Q 断开后弹簧的最大弹性势能等于 2.2mgR，Q 的质量应为多大？", "score": 6},
                {"no": "(4)", "text": "欲使 P 和 Q 断开后 Q 的最终动能最大，Q 的质量应为多大？", "score": 4},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "小球", "mass_symbol": "m", "note": "质量 m，自 B 点自由下落，经圆弧后压缩弹簧"},
                {"id": "obj2", "name": "薄板 Q", "mass_symbol": "M", "note": "质量 M（第 (3) 问）、M′（第 (4) 问）；断开后开始滑动"},
                {"id": "obj3", "name": "物块 P 与圆弧", "mass_symbol": "M", "note": "固定不动，只提供半径 R 的圆弧与支撑面"},
            ],
            "given": [
                {"symbol": "R", "value": None, "unit": "m", "text": "圆弧轨道半径 R（符号量）"},
                {"symbol": "m", "value": None, "unit": "kg", "text": "小球质量 m（符号量）"},
                {"symbol": "M", "value": None, "unit": "kg", "text": "第 (3) 问中薄板 Q 的质量 M（待求，符号量）"},
                {"symbol": "Mp", "value": None, "unit": "kg", "text": "第 (4) 问中薄板 Q 的质量 M′（待求，符号量）"},
                {"symbol": "g", "value": None, "unit": "m/s^2", "text": "重力加速度大小 g（符号量）"},
            ],
            "process_segments": [
                {"no": 1, "name": "B→A 自由落体", "start": "小球自 B 点由静止下落", "end": "到达圆弧顶端 A（速度零基线的终点）"},
                {"no": 2, "name": "沿圆弧下滑 A→Q 上表面", "start": "小球在 A 点", "end": "离开圆弧、进入 Q 的上表面（竖直落差 R）"},
                {"no": 3, "name": "压缩弹簧至球速 1/3、断开 P/Q", "start": "小球与弹簧刚接触（速度 v₀）",
                 "end": "球速降为 v₀/3，弹簧弹性势能 2mgR，P、Q 断开"},
                {"no": 4, "name": "断开后球与 Q 的相对运动", "start": "P、Q 断开瞬间", "end": "弹簧达到最大压缩（共速）或球速为零且弹簧恢复原长"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "W", "text": "重力对小球做的功"},
                {"no": "(2)", "quantity": "v0", "text": "小球与弹簧刚接触时的速度"},
                {"no": "(2)", "quantity": "h", "text": "B、A 两点间的距离"},
                {"no": "(3)", "quantity": "M", "text": "使最大弹性势能为 2.2mgR 的 Q 质量"},
                {"no": "(4)", "quantity": "Mp", "text": "使 Q 最终动能最大的 Q 质量"},
            ],
            "assumptions": [
                "圆弧光滑、Q 上下表面光滑：除弹簧弹力外无其他做功因素，机械能守恒",
                "圆弧顶端 A 到 Q 上表面的竖直落差为 R（半径 R、「平滑连接」两条件合成），与 B 到 A 的距离 h 无关",
                "弹簧右端固定在 Q 上、左端自由；球压缩弹簧时 Q 尚未运动（P、Q 仍连接）",
                "断开瞬间 Q 从静止开始，此后球＋Q＋弹簧系统动量守恒、机械能守恒",
                "本题不给数值：L1 全步 na，不假设 R、m、g 的具体值来凑回代",
            ],
        },
        "nums": {},
        "allowed_symbols": ["m", "M", "Mp", "R", "g", "h", "v0", "v1", "v2", "vc", "W", "Epmax"],
        "prior": "high",
        "reason": "金标参考解：全符号 + 圆弧重力功 + 弹簧两极值态；L1 全步 na，L2 逐式手判；20/20 满分",
        "steps": [
            dict(pid="A-05-S01", title="重力做功 W = mgR", kind="equation", score=3,
                 stmt="小球从圆弧顶端 A 滑到 Q 的上表面，竖直下降高度恰为半径 R：重力做功 W＝mgR。",
                 latex="W = m g R",
                 sympy="W - m*g*R",
                 l2="kg·m/s²·m＝J",
                 l4="写成 mg(h+R) 或 mgH 不得分；只给 mgR 无说明给 2 分（口径）；h 是 B 到 A，不是 A 到 Q 表面",
                 val={"symbol": "W", "number": None, "exact": "m*g*R", "unit": "J",
                      "direction": None, "sig_figs": None},
                 laws=["L-08"]),
            dict(pid="A-05-S02", title="接触后能量守恒（含 1/3 时仍有动能）", kind="equation", score=3,
                 stmt="从刚接触（v₀）到速度减为 v₀/3：½mv₀²＝2mgR＋½m(v₀/3)²——速度减为 1/3 时球仍有动能，"
                      "不能把 ½mv₀² 全部记为弹性势能。",
                 latex="\\frac{1}{2} m v_{0}^{2} = 2 m g R + \\frac{1}{2} m (\\frac{v_{0}}{3})^{2}",
                 sympy="Rational(1,2)*m*v0**2 - 2*m*g*R - Rational(1,2)*m*(v0/3)**2",
                 l2="各项均为 J",
                 l4="漏「速度减为 1/3 时仍有动能」扣 2（最常见错误）（口径）",
                 laws=["L-09"]),
            dict(pid="A-05-S03", title="解出 v₀ = (3/2)√(2gR)", kind="discussion", score=1,
                 stmt="由 ½mv₀²−½m(v₀/3)²＝2mgR 得 (4/9)mv₀²＝2mgR，v₀²＝9gR/2，故 v₀＝(3/2)√(2gR)。",
                 latex="v_{0} = \\frac{3}{2} \\sqrt{2 g R}",
                 sympy="v0**2 - Rational(9,2)*g*R",
                 l2="m²/s²",
                 l4="未开方、写成 3√(gR) 不得分（口径）；(3/2)√(2gR) 与 √(9gR/2) 等价",
                 val={"symbol": "v0", "number": None, "exact": "3*sqrt(2*g*R)/2", "unit": "m/s",
                      "direction": "+x", "sig_figs": None},
                 laws=["L-09"]),
            dict(pid="A-05-S04", title="自由下落段 mg(h+R) = ½mv₀²", kind="equation", score=2,
                 stmt="从 B 点静止下落到刚接触弹簧，竖直下降 h＋R：mg(h＋R)＝½mv₀²。",
                 latex="m g (h + R) = \\frac{1}{2} m v_{0}^{2}",
                 sympy="m*g*(h + R) - Rational(1,2)*m*v0**2",
                 l2="J",
                 l4="写成 mgh＝½mv₀²（漏 R）扣 1（口径）；R 是 A 到 Q 表面的落差，必须计入",
                 laws=["L-09"]),
            dict(pid="A-05-S05", title="h = 5R/4", kind="discussion", score=1,
                 stmt="代入 v₀²＝9gR/2：h＋R＝9R/4，故 h＝5R/4。",
                 latex="h = \\frac{5}{4} R",
                 sympy="h - Rational(5,4)*R",
                 l2="m",
                 l4="不等于 5R/4 的等价形式（1.25R、R＋R/4 可）不得分；只写 5/4 漏 R 本步 0 分（口径）",
                 val={"symbol": "h", "number": None, "exact": "5*R/4", "unit": "m",
                      "direction": None, "sig_figs": None},
                 laws=["L-09"]),
            dict(pid="A-05-S06", title="断开后动量守恒（球速取 v₀/3）", kind="equation", score=2,
                 stmt="断开瞬间球速 v₀/3、Q 静止；此后水平方向无外力，到弹簧压缩最大（共速 vc）时："
                      "m(v₀/3)＝(m＋M)vc。",
                 latex="m \\frac{v_{0}}{3} = (m + M) v_{c}",
                 sympy="m*v0/3 - (m + M)*vc",
                 l2="kg·m/s",
                 l4="用 v₀ 而非 v₀/3 扣 1（口径）；断开时球速已不是 v₀，这是本题第二个高发错点",
                 laws=["L-12"]),
            dict(pid="A-05-S07", title="断开后能量守恒（2.2mgR 写在末态）", kind="equation", score=2,
                 stmt="从刚接触弹簧到最大压缩：½mv₀²＝2.2mgR＋½(m＋M)vc²，弹性势能最大值写在末态。",
                 latex="\\frac{1}{2} m v_{0}^{2} = 2.2 m g R + \\frac{1}{2} (m + M) v_{c}^{2}",
                 sympy="Rational(1,2)*m*v0**2 - Rational(11,5)*m*g*R - Rational(1,2)*(m + M)*vc**2",
                 l2="各项均为 J",
                 l4="2.2mgR 须写在末态（口径）；写成初态或漏掉共速动能都会解不出 M＝4m",
                 laws=["L-09"]),
            dict(pid="A-05-S08", title="解得 M = 4m", kind="discussion", score=2,
                 stmt="联立 m v₀/3＝(m＋M)vc 与 ½mv₀²＝2.2mgR＋½(m＋M)vc²，代入 v₀²＝9gR/2 得 M＝4m。",
                 latex="M = 4 m",
                 sympy="M - 4*m",
                 l2="kg",
                 l4="只有结果无式给 1 分（口径）；M＝4m 与 (3) 的「最大弹性势能 2.2mgR」绑定，换 2mgR 会得别的值",
                 val={"symbol": "M", "number": None, "exact": "4*m", "unit": "kg",
                      "direction": None, "sig_figs": None},
                 laws=["L-12", "L-09"]),
            dict(pid="A-05-S09", title="判定 Q 动能最大的条件", kind="judgment", score=2,
                 stmt="弹簧恢复原长后不再推 Q，此后 Q 匀速，故 Q 动能最大的时刻是弹簧刚恢复原长、且球速恰为零；"
                      "「共速」只是弹簧压缩量最大、弹性势能最大，不是 Q 动能最大。",
                 crit=dict(expr="v", expected=None, comparator="qualitative",
                           text="Q 动能最大 ⇔ 球速恰为零且弹簧恢复原长：此后弹簧不再推 Q，Q 速度达最大；"
                                "共速对应的是弹簧压缩量最大（弹性势能最大），不是 Q 动能最大。"),
                 l2="m/s（球速 v）",
                 l4="说「共速」错（共速对应势能最大）；本问唯一物理采分点（口径）",
                 laws=["L-09", "L-12"]),
            dict(pid="A-05-S10", title="动量守恒与动能守恒联立", kind="equation", score=1,
                 stmt="球速为零、弹簧恢复原长时 Q 速度记 v₂：动量 m(v₀/3)＝M′v₂，能量 ½mv₀²＝½M′v₂²，两式联立。",
                 latex="m \\frac{v_{0}}{3} = M_{p} v_{2}",
                 sympy="m*v0/3 - Mp*v2",
                 l2="kg·m/s",
                 l4="两式缺一不给（口径）；本步是合步，承载动量式与能量式两个事实，见 note",
                 note="合步：承载「动量守恒 m(v₀/3)＝M′v₂」与「能量守恒 ½mv₀²＝½M′v₂²」两个事实，"
                      "分不清各占几分（总表 A-05-S10 亦为合步）；equation 只写动量式，能量式写在 statement",
                 laws=["L-12", "L-09"]),
            dict(pid="A-05-S11", title="解得 M′ = m/9", kind="discussion", score=1,
                 stmt="两式消去 v₂：½mv₀²＝½M′(m v₀/(3M′))² ⇒ 1＝m/(9M′)，故 M′＝m/9。",
                 latex="M_{p} = \\frac{m}{9}",
                 sympy="Mp - m/9",
                 l2="kg",
                 l4="写成 9m（质量比颠倒）不得分（口径）；M′ 越小 Q 分到的速度越大，m/9 方向自洽",
                 val={"symbol": "Mp", "number": None, "exact": "m/9", "unit": "kg",
                      "direction": None, "sig_figs": None},
                 laws=["L-12", "L-09"]),
        ],
    }
    build(cfg)


# ---------------------------------------------------------------- A-06

def a06():
    """2024 新课标 25：板块模型＋平抛，有数值；L1 逐式回代。

    符号迁移：板长 l → L；薄板位移 Δl → s2（物体 2 的对地位移）；板速 → v1；
    平抛飞行时间 → t2（白名单 t2 即「第二段过程的时间」）。
    质量相等且不出现在方程里：a₁、a₂ 都用 μg 表示，不设 m。
    """
    stem = ("如图，一长度 l＝1.0 m 的均匀薄板初始时静止在一光滑平台上，薄板的右端与平台的边缘 O 对齐。"
            "薄板上的一小物块从薄板的左端以某一初速度向右滑动，当薄板运动的距离 Δl＝l/6 时，"
            "物块从薄板右端水平飞出；当物块落到地面时，薄板中心恰好运动到 O 点。"
            "已知物块与薄板的质量相等，它们之间的动摩擦因数 μ＝0.3，重力加速度大小 g＝10 m/s²。求")
    cfg = {
        "meta": {"answer_id": "A-06", "question_id": "A-06", "group": "A",
                 "source": "2024 新课标卷", "question_no": 25, "full_score": 14,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T19:25:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [{"fig_no": 1,
                         "caption": "长 l 的薄板静置于光滑平台，右端与边缘 O 对齐，物块自板左端向右滑；"
                                    "原文无图题，几何关系已由文字给全",
                         "caption_source": "none", "is_required": False}],
            "subquestions": [
                {"no": "(1)", "text": "物块初速度大小及其在薄板上运动的时间。", "score": 10},
                {"no": "(2)", "text": "平台距地面的高度。", "score": 4},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "小物块", "mass_symbol": "m", "note": "与薄板等质量；相对板向右滑，受向左摩擦力"},
                {"id": "obj2", "name": "薄板", "mass_symbol": "m", "note": "长 L＝1.0 m，初始静止；受物块向右的摩擦力而加速"},
                {"id": "obj3", "name": "平台", "mass_symbol": "m", "note": "光滑，无摩擦；右缘为 O 点，物块从 O 外水平飞出"},
            ],
            "given": [
                {"symbol": "L", "value": 1.0, "unit": "m", "text": "薄板长度 l＝1.0 m —— 本档记作 L"},
                {"symbol": "mu", "value": 0.3, "unit": "1", "text": "物块与薄板间的动摩擦因数 μ＝0.3"},
                {"symbol": "g", "value": 10, "unit": "m/s^2", "text": "重力加速度大小 g＝10 m/s²"},
                {"symbol": "m", "value": None, "unit": "kg",
                 "text": "物块与薄板质量相等，同记作 m（比值给定；方程中约去，不出现数值）"},
            ],
            "process_segments": [
                {"no": 1, "name": "板间相对滑动", "start": "物块以 v₀ 自板左端向右滑", "end": "板前进 Δl＝L/6，物块从板右端飞出"},
                {"no": 2, "name": "物块飞出后板匀速", "start": "物块离板瞬间", "end": "板中心到达 O 点（板再前进 L/3）"},
                {"no": 3, "name": "物块平抛", "start": "物块自板右端水平飞出", "end": "落到地面（与板中心到 O 同时）"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "v0", "text": "物块初速度"},
                {"no": "(1)", "quantity": "t", "text": "物块在薄板上运动的时间"},
                {"no": "(2)", "quantity": "h", "text": "平台距地面的高度"},
            ],
            "assumptions": [
                "物块与板间为滑动摩擦：正压力等于物块重力 mg，摩擦力 μmg；平台光滑无摩擦",
                "两物体质量相等 ⇒ 同一对摩擦力产生的加速度大小相等：a₁＝a₂＝μg＝3 m/s²，方向相反",
                "物块在板上运动期间板从静止加速，位移 s2＝½a₂t²；物块对地位移为 L＋s2（相对板滑过整块板长）",
                "物块飞出后不再受板的作用：板匀速（v1＝a₂t），物块做平抛；两者运动时间相同（等时性）",
                "板中心初始在 O 左侧 L/2 处，飞出时已前进 s2，剩余到 O 的距离为 L/2−s2＝L/3",
            ],
        },
        "nums": {"L": 1.0, "mu": 0.3, "g": 10.0, "s2": 1.0/6, "a1": 3.0, "a2": 3.0,
                 "t": 1.0/3, "v0": 4.0, "v1": 1.0, "t2": 1.0/3, "h": 5.0/9},
        "allowed_symbols": ["L", "mu", "g", "m", "s2", "a1", "a2", "t", "v0", "v1", "t2", "h"],
        "prior": "high",
        "reason": "金标参考解：板块相对滑动＋飞出后匀速＋平抛等时；L1 逐式数值回代，14/14 满分",
        "steps": [
            dict(pid="A-06-S01", title="判定物块减速、薄板加速（同一对摩擦力）", kind="judgment", score=1,
                 stmt="物块相对薄板向右滑动，板对物块的摩擦力向左（物块减速）；物块对板的摩擦力向右（板加速）。"
                      "两力是同一对相互作用，大小同为 μmg。",
                 crit=dict(expr="f", expected=None, comparator="qualitative",
                           text="物块相对板向右滑，故板对物块的摩擦力向左、物块对板的摩擦力向右；两力是同一对相互作用，"
                                "大小同为 μmg，分别驱动 a₁（减速）与 a₂（加速）。"),
                 l2="N（摩擦力 f）",
                 l4="只说「物块减速」未提薄板加速，本步 0 分；未点明摩擦力为二者间相互作用，本步 0 分（口径）",
                 laws=["L-04", "L-05"]),
            dict(pid="A-06-S02", title="物块：μmg = m a₁", kind="equation", score=2,
                 stmt="对物块：水平方向只受板的摩擦力 μmg（向左），μmg＝m a₁ ⇒ a₁＝μg＝3 m/s²。",
                 latex="\\mu m g = m a_{1}",
                 sympy="mu*g - a1",
                 l2="无量纲×m/s²＝m/s²",
                 l4="写成 M a₁ 或漏 μ 不得分（口径）；a₁ 方向向左，未注明不扣分",
                 val={"symbol": "a1", "number": 3.0, "exact": "mu*g", "unit": "m/s^2",
                      "direction": "-x", "sig_figs": 1},
                 laws=["L-04", "L-05"]),
            dict(pid="A-06-S03", title="薄板：同一摩擦力驱动 a₂ = μg", kind="equation", score=2,
                 stmt="对薄板：水平方向只受物块给的摩擦力 μmg（向右），μmg＝M a₂；因 M＝m，a₂＝μg＝3 m/s²。",
                 latex="\\mu m g = M a_{2}",
                 sympy="mu*g - a2",
                 l2="无量纲×m/s²＝m/s²",
                 l4="因 M＝m 故 a₂ 与 a₁ 等大；写成 a₂＝μg/2 或 a₂＝μmg/2m 化简错，本步 0 分（口径）",
                 val={"symbol": "a2", "number": 3.0, "exact": "mu*g", "unit": "m/s^2",
                      "direction": "+x", "sig_figs": 1},
                 laws=["L-04", "L-05"]),
            dict(pid="A-06-S04", title="板位移 Δl = ½a₂t² 求 t", kind="value", score=1,
                 stmt="板自静止加速，位移 s2＝½a₂t²＝L/6＝1/6 m，代入 a₂＝3 m/s² 得 t＝1/3 s。",
                 latex="s_{2} = \\frac{1}{2} a_{2} t^{2}",
                 sympy="s2 - Rational(1,2)*a2*t**2",
                 l2="m",
                 l4="Δl 取成 L 或 L/2 不得分；只列式未解出 t 给 0 分（本步即求 t）（口径）",
                 val={"symbol": "t", "number": 1.0/3, "exact": "1/3", "unit": "s",
                      "direction": None, "sig_figs": 2},
                 laws=["L-01"]),
            dict(pid="A-06-S05", title="物块对地位移 L＋Δl = v₀t − ½a₁t²", kind="equation", score=3,
                 stmt="物块在板上滑过整块板长，同时对地随板前移：物块对地位移为 L＋s2＝1＋1/6 m；"
                      "匀减速：L＋s2＝v₀t−½a₁t²。",
                 latex="L + s_{2} = v_{0} t - \\frac{1}{2} a_{1} t^{2}",
                 sympy="L + s2 - v0*t + Rational(1,2)*a1*t**2",
                 l2="m",
                 l4="位移写 L 本步最高给 1 分；写 L−Δl 本步 0 分；方程对但代入 t 错给 1 分（口径）",
                 laws=["L-01"]),
            dict(pid="A-06-S06", title="解得 v₀ = 4 m/s", kind="discussion", score=1,
                 stmt="代入 t＝1/3 s、a₁＝3 m/s²：v₀×(1/3)−½×3×(1/3)²＝7/6，得 v₀＝4 m/s（方向向右）。",
                 latex="v_{0} = 4",
                 sympy="v0 - 4",
                 l2="m/s",
                 l4="只写 4 不写单位、方向写反（向左）、结果与方程不自洽（如 3 m/s）均为本步 0 分（口径）",
                 val={"symbol": "v0", "number": 4.0, "exact": "4", "unit": "m/s",
                      "direction": "+x", "sig_figs": 1},
                 laws=["L-01"]),
            dict(pid="A-06-S07", title="判定飞出后板匀速、物块平抛", kind="judgment", score=1,
                 stmt="物块离开板后，板不再受水平摩擦力，按 v1 匀速前进；物块只受重力，初速度水平，做平抛运动。"
                      "两者运动时间相同（同时开始、同时结束）。",
                 crit=dict(expr="f", expected=None, comparator="qualitative",
                           text="物块飞出后与板脱离，板水平方向不受力 ⇒ 匀速；物块只受重力且初速水平 ⇒ 平抛。"
                                "仍按板继续加速列式，本步 0 分且后续时间必错。"),
                 l2="N（水平力 f）",
                 l4="仍按薄板继续加速列式，本步 0 分且后续时间必错（口径）",
                 laws=["L-03", "L-02"]),
            dict(pid="A-06-S08", title="飞出瞬间板速 v₁ = a₂t", kind="equation", score=1,
                 stmt="板从静止匀加速 t＝1/3 s：v1＝a₂t＝3×1/3＝1 m/s。",
                 latex="v_{1} = a_{2} t",
                 sympy="v1 - a2*t",
                 l2="m/s²·s＝m/s",
                 l4="用 v₂＝v₀ 或未由 a₂t 求出，本步 0 分（口径）",
                 val={"symbol": "v1", "number": 1.0, "exact": "a2*t", "unit": "m/s",
                      "direction": "+x", "sig_figs": 1},
                 laws=["L-01"]),
            dict(pid="A-06-S09", title="等时性：板中心到 O 的距离 = v₁t′", kind="equation", score=1,
                 stmt="板中心初始在 O 左侧 L/2＝0.5 m，飞出时已前进 s2＝1/6 m，尚余 L/2−s2＝1/3 m；"
                      "板匀速走完这段的时间 t′：L/2−s2＝v1 t′。",
                 latex="\\frac{L}{2} - s_{2} = v_{1} t_{2}",
                 sympy="L/2 - s2 - v1*t2",
                 l2="m",
                 l4="须写出 (L/2−L/6)＝L/3 的来历；直接取板中心到 O 的距离为 L/2（未减薄板已走的 Δl）本步 0 分（口径）",
                 val={"symbol": "t2", "number": 1.0/3, "exact": "1/3", "unit": "s",
                      "direction": None, "sig_figs": 2},
                 laws=["L-01"]),
            dict(pid="A-06-S10", title="平抛高度 h = ½gt′²", kind="equation", score=1,
                 stmt="物块平抛时间与板匀速时间相同 t′＝1/3 s：h＝½g t′²＝½×10×(1/3)²＝5/9 m。",
                 latex="h = \\frac{1}{2} g t_{2}^{2}",
                 sympy="h - Rational(1,2)*g*t2**2",
                 l2="m/s²·s²＝m",
                 l4="用 h＝½g(t＋t′)² 不得分（口径）；等时性是本步成立的前提",
                 val={"symbol": "h", "number": 5.0/9, "exact": "5/9", "unit": "m",
                      "direction": None, "sig_figs": 2},
                 laws=["L-02"]),
        ],
    }
    build(cfg)


# ---------------------------------------------------------------- A-09

def a09():
    """2025 安徽 14：变半径圆周（绳绕双钉）＋平抛＋绳不松弛临界；有数值。

    原文「初速度 v₀」在第 (3) 问被改变，故第 (3) 问的新初速度另记 v（v0 只用于 10 m/s）。
    """
    stem = ("如图，M、N 为固定在竖直平面内同一高度的两根细钉，间距 L＝0.5 m。一根长为 3L 的轻绳一端系在 M 上，"
            "另一端竖直悬挂质量 m＝0.1 kg 的小球，小球与水平地面接触但无压力。t＝0 时，小球以水平向右的初速度 "
            "v₀＝10 m/s 开始在竖直平面内做圆周运动。小球牵引着绳子绕过 N、M，运动到 M 正下方与 M 相距 L 的位置时，"
            "绳子刚好被拉断，小球开始做平抛运动。小球可视为质点，绳子不可伸长，不计空气阻力，重力加速度 g 取 10 m/s²。")
    cfg = {
        "meta": {"answer_id": "A-09", "question_id": "A-09", "group": "A",
                 "source": "2025 安徽卷", "question_no": 14, "full_score": 14,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T19:35:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [{"fig_no": 1,
                         "caption": "同一高度的两细钉 M、N（间距 L），长 3L 的轻绳系于 M、悬挂小球；原文无图题，"
                                    "绕钉次序与断绳位置已由文字给定",
                         "caption_source": "none", "is_required": False}],
            "subquestions": [
                {"no": "(1)", "text": "绳子被拉断时小球的速度大小，及绳子所受的最大拉力大小。", "score": 6},
                {"no": "(2)", "text": "小球做平抛运动时抛出点到落地点的水平距离。", "score": 3},
                {"no": "(3)", "text": "若在 t＝0 时只改变小球的初速度大小，使小球能通过 N 的正上方且绳子不松弛，"
                                      "求初速度的最小值。", "score": 5},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "小球", "mass_symbol": "m", "note": "质量 0.1 kg，视为质点；被绳牵引做变半径圆周运动"},
                {"id": "obj2", "name": "细钉 M、N", "mass_symbol": "m",
                 "note": "同一高度、间距 L＝0.5 m；绳依次绕 M、N、M，半径 3L→2L→L"},
                {"id": "obj3", "name": "轻绳", "mass_symbol": "m", "note": "长 3L，不可伸长；绕钉处半径突变，拉力提供向心力"},
            ],
            "given": [
                {"symbol": "L", "value": 0.5, "unit": "m", "text": "M、N 间距 L＝0.5 m；绳长 3L"},
                {"symbol": "m", "value": 0.1, "unit": "kg", "text": "小球质量 m＝0.1 kg"},
                {"symbol": "v0", "value": 10, "unit": "m/s", "text": "t＝0 时水平向右的初速度 v₀＝10 m/s（第 (3) 问改为待求的 v）"},
                {"symbol": "g", "value": 10, "unit": "m/s^2", "text": "重力加速度 g 取 10 m/s²"},
            ],
            "process_segments": [
                {"no": 1, "name": "绕 M、半径 3L", "start": "t＝0 小球在最低点、绳竖直", "end": "绳碰到 N，绕点变为 N"},
                {"no": 2, "name": "绕 N、半径 2L", "start": "绳绕 N", "end": "绳再碰到 M，绕点回到 M"},
                {"no": 3, "name": "绕 M、半径 L，至断绳后平抛", "start": "绳绕 M、半径减为 L",
                 "end": "到达 M 正下方 L 处绳断，小球平抛落地"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "v1", "text": "断绳时小球速度大小"},
                {"no": "(1)", "quantity": "FT", "text": "绳所受最大拉力"},
                {"no": "(2)", "quantity": "x", "text": "平抛水平距离"},
                {"no": "(3)", "quantity": "v", "text": "能过 N 正上方且绳不松弛的最小初速度"},
            ],
            "assumptions": [
                "小球初始与地面接触但无压力 ⇒ M 距地面 3L；断绳点在 M 正下方 L 处，距地 2L",
                "绕钉处半径瞬间由 3L 减为 2L、再减为 L；每次半径突变瞬间速度大小不变（绳不可伸长、无切向冲量）",
                "断绳前只有重力做功，机械能守恒；断绳后只受重力，平抛",
                "第 (3) 问的临界位置在 N 正上方（半径 2L），该点距地 3L＋2L＝5L",
                "第 (3) 问改变的是初速度，另记作 v（v0 仍指第 (1)(2) 问的 10 m/s）",
            ],
        },
        "nums": {"L": 0.5, "m": 0.1, "v0": 10.0, "g": 10.0,
                 "v1": 8.94427190999916, "FT": 17.0, "t": 0.447213595499958,
                 "x": 4.0, "v2": 3.1622776601683795, "v": 7.745966692414834},
        "allowed_symbols": ["L", "m", "v0", "v1", "v", "v2", "g", "FT", "x", "t"],
        "prior": "high",
        "reason": "金标参考解：变半径圆周三段 + 平抛 + 绳不松弛临界；L1 逐式回代，14/14 满分",
        "steps": [
            dict(pid="A-09-S01", title="判定绕钉次序与各段半径", kind="judgment", score=1,
                 stmt="绳依次绕 M、N、M 转动：第一段绕 M、半径 3L；碰到 N 后绕 N、半径 2L；再碰到 M 后绕 M、"
                      "半径减为 L。断绳点在 M 正下方与 M 相距 L 处，正是半径 L 的最低点。",
                 crit=dict(expr="R", expected=None, comparator="qualitative",
                           text="绳依次绕 M、N、M，转动半径由 3L 依次减为 2L、L；断绳点在 M 正下方 L 处，"
                                "是绕 M、半径 L 的最低点，不是 3L 或 2L。"),
                 l2="m（半径 R）",
                 l4="把断绳点半径当作 3L 或 2L（未识别第三次绕 M 后半径减为 L），本步 0 分；只说「做圆周运动」"
                    "未指出半径随绕钉改变，本步 0 分（口径）",
                 laws=["L-06"]),
            dict(pid="A-09-S02", title="初始到断绳点机械能守恒", kind="equation", score=2,
                 stmt="初始小球在地面（速度 v₀、高度 0），断绳点在 M 正下方 L 处、距地 2L："
                      "½mv₀²＝mg·2L＋½mv₁²。",
                 latex="\\frac{1}{2} m v_{0}^{2} = m g \\cdot 2 L + \\frac{1}{2} m v_{1}^{2}",
                 sympy="Rational(1,2)*m*v0**2 - m*g*2*L - Rational(1,2)*m*v1**2",
                 l2="各项均为 J",
                 l4="高度差取 3L（把断绳点当作地面）或 L，本步 0 分；漏 ½mv₀² 项或把 v₁ 当作 v₀ 代入，本步 0 分（口径）",
                 laws=["L-09"]),
            dict(pid="A-09-S03", title="解得 v₁ = 4√5 m/s", kind="value", score=1,
                 stmt="代入 v₀＝10 m/s、L＝0.5 m：½×0.1×100＝0.1×10×1＋½×0.1×v₁²，得 v₁²＝80，v₁＝4√5 m/s≈8.9 m/s。",
                 latex="v_{1} = 4 \\sqrt{5}",
                 sympy="v1**2 - 80",
                 l2="m²/s²",
                 l4="停在 v₁²＝80 未开方，本步 0 分；只写 4√5 不写单位 m/s，本步 0 分；8.9 m/s 三位有效数字不扣（口径）",
                 val={"symbol": "v1", "number": 8.94427190999916, "exact": "4*sqrt(5)", "unit": "m/s",
                      "direction": None, "sig_figs": 3},
                 laws=["L-09"]),
            dict(pid="A-09-S04", title="断绳点沿半径列向心力式", kind="equation", score=2,
                 stmt="断绳点在最低点，绳拉力与重力合力提供向心力：F_T−mg＝mv₁²/L；代入得 F_T＝17 N，"
                      "由牛顿第三定律绳所受最大拉力亦为 17 N。",
                 latex="F_{T} - m g = m \\frac{v_{1}^{2}}{L}",
                 sympy="FT - m*g - m*v1**2/L",
                 l2="N−N＝kg·(m/s)²/m＝N",
                 l4="写成 F_T＝mv₁²/L（漏重力项）或 F_T＋mg＝mv₁²/L（重力方向反）本步 0 分；分母用 3L 或 2L 本步 0 分（口径）",
                 val={"symbol": "FT", "number": 17.0, "exact": "17", "unit": "N",
                      "direction": "+y", "sig_figs": 2},
                 laws=["L-06"]),
            dict(pid="A-09-S05", title="平抛：竖直 2L = ½gt²、水平 x = v₁t", kind="equation", score=2,
                 stmt="抛出点距地 2L：竖直方向 2L＝½gt²，水平方向 x＝v₁t；消去 t 得 x＝v₁√(4L/g)。",
                 latex="x = v_{1} \\sqrt{\\frac{4 L}{g}}",
                 sympy="x - v1*sqrt(4*L/g)",
                 l2="m/s·s＝m",
                 l4="高度用 3L 或 L（未识别抛出点距地 2L），本步 0 分；水平速度用 v₀＝10 m/s 而非 v₁，本步 0 分（口径）",
                 val={"symbol": "x", "number": 4.0, "exact": "v1*sqrt(4*L/g)", "unit": "m",
                      "direction": "+x", "sig_figs": 2},
                 laws=["L-02", "L-01"]),
            dict(pid="A-09-S06", title="x = 4 m", kind="discussion", score=1,
                 stmt="代入 v₁＝4√5 m/s、L＝0.5 m、g＝10 m/s²：t＝√0.2 s≈0.447 s，x＝4√5×0.447≈4.0 m。",
                 latex="x = 4",
                 sympy="x - 4",
                 l2="m",
                 l4="只写 4 不写单位 m，本步 0 分；用 v₀ 代入得 4.5 m 左右、写成 40 m，本步 0 分（口径）",
                 val={"symbol": "x", "number": 4.0, "exact": "4", "unit": "m",
                      "direction": "+x", "sig_figs": 1},
                 laws=["L-02"]),
            dict(pid="A-09-S07", title="绳不松弛的临界条件", kind="critical", score=2,
                 stmt="恰好通过 N 正上方且绳不松弛：该点半径 2L，重力恰提供向心力 mg＝mv₂²/(2L)，得 v₂²＝2gL。"
                      "临界位置在 N 正上方，不是 M 正上方或断绳点。",
                 crit=dict(expr="m*g", expected="m*v2**2/(2*L)", comparator="eq",
                           text="绳不松弛的临界条件是「重力恰提供向心力」：mg＝mv₂²/(2L)，临界点取 N 正上方、半径 2L。"),
                 l2="N",
                 l4="半径写成 3L 或 L、把临界点判在 M 正上方或断绳点，本步 0 分；只写「恰好不松弛」未给出等式，本步 0 分（口径）",
                 laws=["L-06"]),
            dict(pid="A-09-S08", title="初始到 N 正上方机械能守恒", kind="equation", score=2,
                 stmt="N 正上方距地 5L（M 距地 3L＋半径 2L）：½mv²＝mg·5L＋½mv₂²。",
                 latex="\\frac{1}{2} m v^{2} = m g \\cdot 5 L + \\frac{1}{2} m v_{2}^{2}",
                 sympy="Rational(1,2)*m*v**2 - m*g*5*L - Rational(1,2)*m*v2**2",
                 l2="各项均为 J",
                 l4="高度差取 2L（只算到 N 的高度）或 3L，本步 0 分；把最高点速度当零（漏 ½mv₂² 项），本步 0 分（口径）",
                 laws=["L-09"]),
            dict(pid="A-09-S09", title="v = 2√15 m/s", kind="discussion", score=1,
                 stmt="代入 v₂²＝2gL、L＝0.5 m：½×0.1×v²＝0.1×10×2.5＋½×0.1×10，得 v²＝60，v＝2√15 m/s≈7.7 m/s。",
                 latex="v = 2 \\sqrt{15}",
                 sympy="v**2 - 60",
                 l2="m²/s²",
                 l4="只写 2√15 不写单位 m/s，本步 0 分；v² 误取 20 得 2√5 m/s，本步 0 分；7.75 m/s 两位小数不扣（口径）",
                 val={"symbol": "v", "number": 7.745966692414834, "exact": "2*sqrt(15)", "unit": "m/s",
                      "direction": "+x", "sig_figs": 3},
                 laws=["L-09"]),
        ],
    }
    build(cfg)


# ---------------------------------------------------------------- B-01

def b01():
    """2024 广西 13：平均速度＝中间时刻速度＋速度位移式＋锥筒编号判断；有数值。"""
    stem = ("如图，轮滑训练场沿直线等间距地摆放着若干个定位锥筒，锥筒间距 d＝0.9 m，某同学穿着轮滑鞋向右匀减速滑行。"
            "现测出他从 1 号锥筒运动到 2 号锥筒用时 t₁＝0.4 s，从 2 号锥筒运动到 3 号锥筒用时 t₂＝0.5 s。求该同学：")
    cfg = {
        "meta": {"answer_id": "B-01", "question_id": "B-01", "group": "B",
                 "source": "2024 广西卷", "question_no": 13, "full_score": 10,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T19:40:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [{"fig_no": 1,
                         "caption": "沿直线等间距 d＝0.9 m 摆放的编号锥筒，同学向右匀减速滑行；原文无图题",
                         "caption_source": "none", "is_required": False}],
            "subquestions": [
                {"no": "(1)", "text": "滑行的加速度大小。", "score": 4},
                {"no": "(2)", "text": "最远能经过几号锥筒。", "score": 6},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "轮滑同学", "mass_symbol": "m", "note": "向右匀减速滑行，视为质点；质量不参与计算"},
                {"id": "obj2", "name": "定位锥筒", "mass_symbol": "m",
                 "note": "等间距 d＝0.9 m 沿直线摆放，1 号在最左；编号 n 的锥筒距 1 号 (n−1)d"},
            ],
            "given": [
                {"symbol": "d", "value": 0.9, "unit": "m", "text": "锥筒间距 d＝0.9 m"},
                {"symbol": "t1", "value": 0.4, "unit": "s", "text": "1 号到 2 号用时 t₁＝0.4 s"},
                {"symbol": "t2", "value": 0.5, "unit": "s", "text": "2 号到 3 号用时 t₂＝0.5 s"},
            ],
            "process_segments": [
                {"no": 1, "name": "单段匀减速至停止", "start": "经过 1 号锥筒（速度 v）", "end": "滑行 x 后停止，落在 4 号与 5 号之间"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "a", "text": "滑行加速度大小"},
                {"no": "(2)", "quantity": "x", "text": "从 1 号起算的停止距离，并据此判断最远经过几号"},
            ],
            "assumptions": [
                "向右为正，匀减速故 a 取负值；本题只问大小，a 记正值、方向另注",
                "每段位移均为 d＝0.9 m；某段平均速度等于该段中间时刻的瞬时速度",
                "两段中间时刻相隔 t₁/2＋t₂/2＝0.45 s，不是 t₁＋t₂＝0.9 s",
                "锥筒编号 n 的位置为 (n−1)d：4 号在 2.7 m、5 号在 3.6 m",
            ],
        },
        "nums": {"d": 0.9, "t1": 0.4, "t2": 0.5, "v1": 2.25, "v2": 1.8,
                 "a": 1.0, "v": 2.45, "x": 3.00125},
        "allowed_symbols": ["d", "t1", "t2", "v1", "v2", "a", "v", "x"],
        "prior": "high",
        "reason": "金标参考解：平均速度＝中间时刻速度 + 速度位移式 + 编号判断；L1 逐式回代，10/10 满分",
        "steps": [
            dict(pid="B-01-S01", title="两段平均速度即两中间时刻速度", kind="equation", score=3,
                 stmt="每段位移均为 d：第一段平均速度 v₁＝d/t₁＝0.9/0.4＝2.25 m/s，第二段 v₂＝d/t₂＝0.9/0.5＝1.8 m/s；"
                      "匀变速下平均速度等于该段中间时刻的瞬时速度。",
                 latex="v_{1} = \\frac{d}{t_{1}}",
                 sympy="v1 - d/t1",
                 l2="m/s",
                 l4="把 v₁、v₂ 当作区间两端点的瞬时速度本步 0 分；只写平均速度定义未代入数值本步 0 分（口径）",
                 val={"symbol": "v1", "number": 2.25, "exact": "d/t1", "unit": "m/s",
                      "direction": "+x", "sig_figs": 3},
                 laws=["L-01"]),
            dict(pid="B-01-S02", title="两中间时刻相隔 0.45 s，a = 1 m/s²", kind="discussion", score=1,
                 stmt="两中间时刻相隔 t₁/2＋t₂/2＝0.2＋0.25＝0.45 s；a＝(v₁−v₂)/0.45＝0.45/0.45＝1 m/s²。",
                 latex="a = \\frac{v_{1} - v_{2}}{\\frac{t_{1}}{2} + \\frac{t_{2}}{2}}",
                 sympy="a - (v1 - v2)/(t1/2 + t2/2)",
                 l2="(m/s)/s＝m/s²",
                 l4="时间间隔取 t₁＋t₂＝0.9 s（未取半）本步 0 分；只写 1 不写单位 m/s² 本步 0 分（口径）",
                 val={"symbol": "a", "number": 1.0, "exact": "1", "unit": "m/s^2",
                      "direction": "-x", "sig_figs": 1},
                 laws=["L-01"]),
            dict(pid="B-01-S03", title="回到 1 号锥筒时刻的速度 v = 2.45 m/s", kind="value", score=2,
                 stmt="v₁ 是 t₁ 中间时刻（0.2 s）的速度，回到 1 号锥筒（t＝0）还要加上 a·t₁/2："
                      "v＝v₁＋a·t₁/2＝2.25＋1×0.2＝2.45 m/s。",
                 latex="v = v_{1} + a \\frac{t_{1}}{2}",
                 sympy="v - v1 - a*t1/2",
                 l2="m/s",
                 l4="直接用 v₁＝2.25 m/s 作为初速度本步 0 分；用 v＝v₁＋a·t₁（时间取整段）本步 0 分（口径）",
                 val={"symbol": "v", "number": 2.45, "exact": "v1 + a*t1/2", "unit": "m/s",
                      "direction": "+x", "sig_figs": 3},
                 laws=["L-01"]),
            dict(pid="B-01-S04", title="停止距离 x = v²/(2a)", kind="equation", score=2,
                 stmt="从 1 号锥筒到停止：0−v²＝−2ax，故 x＝v²/(2a)＝2.45²/2＝3.001 25 m≈3.00 m。",
                 latex="x = \\frac{v^{2}}{2 a}",
                 sympy="x - v**2/(2*a)",
                 l2="(m/s)²/(m/s²)＝m",
                 l4="用 v₁ 代入得 2.53 m 本步 0 分；写成 x＝v²/a（漏 2）本步 0 分（口径）",
                 val={"symbol": "x", "number": 3.00125, "exact": "2401/800", "unit": "m",
                      "direction": "+x", "sig_figs": 3},
                 laws=["L-01"]),
            dict(pid="B-01-S05", title="位置判断：落在 4 号与 5 号之间", kind="judgment", score=1,
                 stmt="4 号锥筒在 3d＝2.7 m，5 号在 4d＝3.6 m；停止点 x≈3.00 m 介于两者之间，"
                      "故最远经过 4 号锥筒，到不了 5 号。",
                 crit=dict(expr="x", expected="3*d", comparator="gt",
                           text="停止点 x≈3.00 m 大于 4 号锥筒的 3d＝2.7 m、小于 5 号的 4d＝3.6 m，故最远经过 4 号。"),
                 l2="m",
                 l4="只把 x 与 3.3 m 或与 d 比较本步 0 分；未建立「锥筒编号—距离」对应本步 0 分（口径）",
                 laws=["L-01"]),
            dict(pid="B-01-S06", title="最远经过 4 号锥筒", kind="discussion", score=1,
                 stmt="最远经过 4 号锥筒（停止点在 4 号与 5 号之间，3.00 m 处）。",
                 latex="x = \\frac{2401}{800}",
                 sympy="x - Rational(2401,800)",
                 l2="m",
                 l4="答 3 号或 5 号本步 0 分；只写 4 不说明「号」本步 0 分（口径）",
                 val={"symbol": "x", "number": 3.00125, "exact": "2401/800", "unit": "m",
                      "direction": "+x", "sig_figs": 3},
                 laws=["L-01"]),
        ],
    }
    build(cfg)


# ---------------------------------------------------------------- B-03

def b03():
    """2022 浙江 6 月 19：斜面＋水平面两段；有数值。

    符号迁移：原文 l₁→s1、l₂→s2（白名单无 l 与下标长度），末端速度上限 2 m/s→v1。
    """
    stem = ("物流公司通过滑轨把货物直接装运到卡车中。如图所示，倾斜滑轨与水平面成 24° 角，长度 l₁＝4 m，"
            "水平滑轨长度可调，两滑轨间平滑连接。若货物从倾斜滑轨顶端由静止开始下滑，其与滑轨间的动摩擦因数均为 "
            "μ＝2/9，货物可视为质点（取 cos 24°＝0.9，sin 24°＝0.4，重力加速度 g 取 10 m/s²）。")
    cfg = {
        "meta": {"answer_id": "B-03", "question_id": "B-03", "group": "B",
                 "source": "2022 浙江 6 月卷", "question_no": 19, "full_score": 9,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T19:45:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [{"fig_no": 1,
                         "caption": "倾角 24° 的倾斜滑轨（长 4 m）与可调长度的水平滑轨平滑连接；原文无图题",
                         "caption_source": "none", "is_required": False}],
            "subquestions": [
                {"no": "(1)", "text": "货物在倾斜滑轨上滑行时加速度 a₁ 的大小。", "score": 2},
                {"no": "(2)", "text": "货物在倾斜滑轨末端时速度 v 的大小。", "score": 3},
                {"no": "(3)", "text": "若货物滑离水平滑轨末端时的速度不超过 2 m/s，求水平滑轨的最短长度 l₂。", "score": 4},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "货物", "mass_symbol": "m", "note": "视为质点；质量在方程中约去"},
                {"id": "obj2", "name": "滑轨", "mass_symbol": "m", "note": "倾斜段长 4 m、倾角 24°，水平段长度可调，两段平滑连接"},
            ],
            "given": [
                {"symbol": "s1", "value": 4, "unit": "m", "text": "倾斜滑轨长度 l₁＝4 m —— 本档记作 s1"},
                {"symbol": "mu", "value": 2.0/9, "unit": "1", "text": "动摩擦因数 μ＝2/9（两段相同）"},
                {"symbol": "g", "value": 10, "unit": "m/s^2", "text": "重力加速度 g 取 10 m/s²"},
                {"symbol": "v1", "value": 2, "unit": "m/s", "text": "滑离水平滑轨末端的速度上限 2 m/s（记作 v1）"},
            ],
            "process_segments": [
                {"no": 1, "name": "斜轨匀加速", "start": "货物自斜轨顶端由静止下滑", "end": "到达斜轨末端，速度 v"},
                {"no": 2, "name": "水平轨匀减速", "start": "经平滑连接进入水平轨", "end": "滑离末端，速度不超过 2 m/s"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "a1", "text": "斜轨上的加速度大小"},
                {"no": "(2)", "quantity": "v", "text": "斜轨末端速度"},
                {"no": "(3)", "quantity": "s2", "text": "水平轨的最短长度"},
            ],
            "assumptions": [
                "sin 24°＝0.4、cos 24°＝0.9 直接取题给值，不用角度符号做三角运算",
                "斜轨上正压力 mg cos 24°，摩擦力 μmg cos 24°；水平轨上正压力 mg，摩擦力 μmg（不含 cos 项）",
                "两轨平滑连接：速度大小不变、方向由沿斜面变为水平（不计连接处能量损失）",
                "「不超过 2 m/s」是位移的边界取值，不涉及「恰好」类临界过程",
            ],
        },
        "nums": {"s1": 4.0, "mu": 2.0/9, "g": 10.0, "v1": 2.0,
                 "a1": 2.0, "v": 4.0, "a2": 20.0/9, "s2": 2.7},
        "allowed_symbols": ["s1", "s2", "mu", "g", "a1", "a2", "v", "v1"],
        "prior": "high",
        "reason": "金标参考解：斜面牛顿第二定律 + 速度位移式 + 水平段减速；L1 逐式回代，9/9 满分",
        "steps": [
            dict(pid="B-03-S01", title="斜面：mg sin24° − μmg cos24° = ma₁", kind="equation", score=2,
                 stmt="沿斜面方向：mg sin 24°−μmg cos 24°＝ma₁，约去 m 得 a₁＝10×(0.4−2/9×0.9)＝2 m/s²。",
                 latex="m g \\sin 24° - \\mu m g \\cos 24° = m a_{1}",
                 sympy="g*Rational(2,5) - mu*g*Rational(9,10) - a1",
                 l2="N/kg＝m/s²",
                 l4="漏 cos24° 或把 sin、cos 配错本步 0 分；μ 取 0.2（应为 2/9）本步 0 分（口径）",
                 val={"symbol": "a1", "number": 2.0, "exact": "2", "unit": "m/s^2",
                      "direction": None, "sig_figs": 1},
                 laws=["L-04", "L-05"]),
            dict(pid="B-03-S02", title="v² = 2a₁l₁，v = 4 m/s", kind="equation", score=2,
                 stmt="自静止匀加速 4 m：v²＝2a₁s1＝2×2×4＝16，v＝4 m/s。",
                 latex="v^{2} = 2 a_{1} s_{1}",
                 sympy="v**2 - 2*a1*s1",
                 l2="m²/s²",
                 l4="写成 v＝a₁t 又未求 t 本步 0 分；用水平段长度代替 s1 本步 0 分（口径）",
                 val={"symbol": "v", "number": 4.0, "exact": "4", "unit": "m/s",
                      "direction": None, "sig_figs": 1},
                 laws=["L-01"]),
            dict(pid="B-03-S03", title="v 的方向：沿斜面向下，进入水平段后变水平", kind="discussion", score=1,
                 stmt="v 的方向沿斜面向下；经平滑连接进入水平段后方向变为水平（大小不变，仍为 4 m/s）。",
                 latex="v = 4",
                 sympy="v - 4",
                 l2="m/s",
                 l4="把 v 的方向写成竖直本步 0 分；只写 4 不写单位 m/s 本步 0 分（口径）",
                 val={"symbol": "v", "number": 4.0, "exact": "4", "unit": "m/s",
                      "direction": None, "sig_figs": 1},
                 laws=["L-01"]),
            dict(pid="B-03-S04", title="水平段 a₂ = μg = 20/9 m/s²", kind="value", score=1,
                 stmt="水平段只受滑动摩擦力 μmg，正压力为 mg（不是 mg cos 24°）：a₂＝μg＝20/9 m/s²≈2.2 m/s²。",
                 latex="a_{2} = \\mu g",
                 sympy="a2 - mu*g",
                 l2="无量纲×m/s²＝m/s²",
                 l4="沿用 a₁＝2 m/s² 本步 0 分；写成 a₂＝μg cos24° 本步 0 分（口径）",
                 val={"symbol": "a2", "number": 20.0/9, "exact": "20/9", "unit": "m/s^2",
                      "direction": None, "sig_figs": 2},
                 laws=["L-04", "L-05"]),
            dict(pid="B-03-S05", title="v₁² − v² = −2a₂l₂", kind="equation", score=2,
                 stmt="水平段匀减速：v1²−v²＝−2a₂s2，代入 v1＝2 m/s、v＝4 m/s 得 s2＝(16−4)/(2×20/9)＝2.7 m。",
                 latex="v_{1}^{2} - v^{2} = - 2 a_{2} s_{2}",
                 sympy="v1**2 - v**2 + 2*a2*s2",
                 l2="m²/s²",
                 l4="不等号方向取反后仍得正解不扣分，但得出负长度本步 0 分；漏 2 倍本步 0 分（口径）",
                 val={"symbol": "s2", "number": 2.7, "exact": "27/10", "unit": "m",
                      "direction": None, "sig_figs": 2},
                 laws=["L-01"]),
            dict(pid="B-03-S06", title="l₂ = 2.7 m", kind="discussion", score=1,
                 stmt="水平滑轨的最短长度为 2.7 m。",
                 latex="s_{2} = \\frac{27}{10}",
                 sympy="s2 - Rational(27,10)",
                 l2="m",
                 l4="只写 2.7 不写单位 m 本步 0 分；写成 2.4 m 本步 0 分（口径）",
                 val={"symbol": "s2", "number": 2.7, "exact": "27/10", "unit": "m",
                      "direction": None, "sig_figs": 2},
                 laws=["L-01"]),
        ],
    }
    build(cfg)


# ---------------------------------------------------------------- B-04

def b04():
    """2024 新课标 24：共点力平衡（正交分解）＋缓慢过程动能定理；有数值。

    依赖图＝是，但工作区没有 B-04 的题图 ⇒ file 双 null + W-fig（任务卡允许的唯一 W）。
    符号迁移：两绳拉力 F_P/F_Q → F1/F2；两绳与竖直方向夹角 α/β → angA/angB。
    """
    stem = ("将重物从高层楼房的窗外运到地面时，为安全起见，要求下降过程中重物与楼墙保持一定的距离。如图，"
            "一种简单的操作方法是一人在高处控制一端系在重物上的绳子 P，另一人在地面控制另一根一端系在重物上的绳子 Q，"
            "二人配合可使重物缓慢竖直下降。若重物的质量 m＝42 kg，重力加速度大小 g＝10 m/s²。"
            "当 P 绳与竖直方向的夹角 α＝37° 时，Q 绳与竖直方向的夹角 β＝53°。(sin 37°＝0.6)")
    cfg = {
        "meta": {"answer_id": "B-04", "question_id": "B-04", "group": "B",
                 "source": "2024 新课标卷", "question_no": 24, "full_score": 10,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T19:50:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [{"fig_no": 1,
                         "caption": "重物由高处的 P 绳与地面的 Q 绳共同悬吊，两绳与竖直方向夹角分别为 37°、53°；"
                                    "原文无图题，两绳方位需图才能唯一确定（依赖图＝是），工作区暂无该题图文件",
                         "caption_source": "none", "is_required": True}],
            "subquestions": [
                {"no": "(1)", "text": "此时 P、Q 绳中拉力的大小。", "score": 6},
                {"no": "(2)", "text": "若开始竖直下降时重物距地面的高度 h＝10 m，求在重物下降到地面的过程中，"
                                      "两根绳子拉力对重物做的总功。", "score": 4},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "重物", "mass_symbol": "m", "note": "质量 42 kg，缓慢竖直下降，任一时刻处于平衡"},
                {"id": "obj2", "name": "P 绳", "mass_symbol": "m", "note": "高处的人控制，与竖直方向夹角 α＝37°，拉力 F1"},
                {"id": "obj3", "name": "Q 绳", "mass_symbol": "m", "note": "地面的人控制，与竖直方向夹角 β＝53°，拉力 F2"},
            ],
            "given": [
                {"symbol": "m", "value": 42, "unit": "kg", "text": "重物质量 m＝42 kg"},
                {"symbol": "g", "value": 10, "unit": "m/s^2", "text": "重力加速度 g＝10 m/s²"},
                {"symbol": "angA", "value": 37, "unit": "deg", "text": "P 绳与竖直方向夹角 α＝37°"},
                {"symbol": "angB", "value": 53, "unit": "deg", "text": "Q 绳与竖直方向夹角 β＝53°"},
                {"symbol": "h", "value": 10, "unit": "m", "text": "开始下降时重物距地面高度 h＝10 m"},
            ],
            "process_segments": [
                {"no": 1, "name": "缓慢竖直下降", "start": "重物在高处以 α＝37°、β＝53° 平衡", "end": "到达地面（下降 h＝10 m）"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "F1", "text": "P 绳拉力"},
                {"no": "(1)", "quantity": "F2", "text": "Q 绳拉力"},
                {"no": "(2)", "quantity": "W", "text": "两绳拉力对重物做的总功"},
            ],
            "assumptions": [
                "「缓慢」⇒ 每一时刻加速度为零，重物处于平衡态；动能始终为零",
                "P 绳斜向上、Q 绳斜向下拉（一人在高处、一人在地面），两绳都在竖直平面内",
                "水平方向两绳拉力分量等大反向；竖直方向两拉力分量之和与重力平衡",
                "两绳拉力做总功按动能定理求：W＋mgh＝ΔEk＝0，不分别求两绳的功",
                "sin 37°＝0.6、cos 37°＝0.8，故 sin 53°＝0.8、cos 53°＝0.6",
            ],
        },
        "nums": {"m": 42.0, "g": 10.0, "F1": 1200.0, "F2": 900.0, "h": 10.0, "W": -4200.0},
        "allowed_symbols": ["m", "g", "F1", "F2", "W", "h"],
        "prior": "high",
        "reason": "金标参考解：正交分解求两拉力 + 缓慢过程动能定理；L1 逐式回代，10/10 满分",
        "steps": [
            dict(pid="B-04-S01", title="缓慢下降 ⇒ 任一时刻平衡", kind="judgment", score=1,
                 stmt="「缓慢」意味着下降过程中速度始终极小、加速度为零，重物在任一位置都处于平衡态："
                      "重力与两绳拉力的合力为零，可对两绳拉力做正交分解。",
                 crit=dict(expr="Fnet", expected=0, comparator="eq",
                           text="缓慢下降 ⇒ 加速度为零，重物任一时刻处于平衡态，合力为零，可用正交分解求两绳拉力。"),
                 l2="N",
                 l4="把「缓慢」当作有加速度本步 0 分；只写「平衡」未说明由缓慢所致本步给分（口径）",
                 laws=["L-03"]),
            dict(pid="B-04-S02", title="水平方向：0.6F₁ = 0.8F₂", kind="equation", score=2,
                 stmt="水平方向合力为零：F1 sin 37°＝F2 sin 53°，即 0.6F1＝0.8F2。",
                 latex="F_{1} \\sin 37° = F_{2} \\sin 53°",
                 sympy="Rational(3,5)*F1 - Rational(4,5)*F2",
                 l2="N",
                 l4="sin、cos 配错本步 0 分；把 P 绳与 53° 对应（角标搞反）本步 0 分（口径）",
                 laws=["L-03"]),
            dict(pid="B-04-S03", title="竖直方向：0.8F₁ = 0.6F₂ + mg", kind="equation", score=2,
                 stmt="竖直方向合力为零：F1 cos 37°＝F2 cos 53°＋mg，即 0.8F1＝0.6F2＋420。",
                 latex="F_{1} \\cos 37° = F_{2} \\cos 53° + m g",
                 sympy="Rational(4,5)*F1 - Rational(3,5)*F2 - m*g",
                 l2="N",
                 l4="漏 mg 本步 0 分；两绳竖直分量都写成向上本步 0 分（口径）",
                 laws=["L-03"]),
            dict(pid="B-04-S04", title="F₁ = 1 200 N、F₂ = 900 N", kind="discussion", score=1,
                 stmt="联立 0.6F1＝0.8F2 与 0.8F1＝0.6F2＋420，得 F1＝1 200 N、F2＝900 N。",
                 latex="F_{1} = 1200",
                 sympy="F1 - 1200",
                 l2="N",
                 l4="只解出一个力本步 0 分；只写数值不写单位 N 本步 0 分（口径）",
                 val={"symbol": "F1", "number": 1200.0, "exact": "1200", "unit": "N",
                      "direction": None, "sig_figs": 2},
                 laws=["L-03"]),
            dict(pid="B-04-S05", title="缓慢 ⇒ 动能不变，W + mgh = 0", kind="judgment", score=1,
                 stmt="缓慢下降 ⇒ 动能始终为零、不变；由动能定理，重力做的正功 mgh 与两绳拉力做的总功 W 之和为零。",
                 crit=dict(expr="W + m*g*h", expected=0, comparator="eq",
                           text="缓慢下降 ⇒ 动能变化为零，动能定理给出 W＋mgh＝0；拉力总功必为负。"),
                 l2="J",
                 l4="把拉力做功当作正功本步 0 分；漏 mgh 项本步 0 分（口径）",
                 laws=["L-08"]),
            dict(pid="B-04-S06", title="W = −mgh = −4 200 J", kind="equation", score=2,
                 stmt="W＝−mgh＝−42×10×10 J＝−4 200 J。",
                 latex="W = - m g h",
                 sympy="W + m*g*h",
                 l2="J",
                 l4="漏负号本步 0 分；按单绳计算或除以 2 本步 0 分（口径）",
                 val={"symbol": "W", "number": -4200.0, "exact": "-4200", "unit": "J",
                      "direction": None, "sig_figs": 2},
                 laws=["L-08"]),
            dict(pid="B-04-S07", title="写作 −4 200 J，负号表示负功", kind="discussion", score=1,
                 stmt="结果写作 −4 200 J，负号表示两绳拉力对重物做负功（拉力方向与下降方向相反）。",
                 latex="W = -4200",
                 sympy="W + 4200",
                 l2="J",
                 l4="只写 4 200 J 未说明是负功本步 0 分（口径）",
                 val={"symbol": "W", "number": -4200.0, "exact": "-4200", "unit": "J",
                      "direction": None, "sig_figs": 2},
                 laws=["L-08"]),
        ],
    }
    build(cfg)


# ---------------------------------------------------------------- B-05

def b05():
    """2025 黑吉辽蒙 13：屋顶匀加速＋斜抛（机械能守恒＋速度分解）；有数值。

    符号迁移：A 点离开速度 v₀ → v（v0 在白名单里指初速度，而 O 点初速为 0）；
    落地速度 v₁ → v1；落地速度与水平方向夹角 α → angA（弧度入 nums，角度入 value）。
    """
    stem = ("如图，一雪块从倾角 θ＝37° 的屋顶上的 O 点由静止开始下滑，滑到 A 点后离开屋顶。O、A 间距离 x＝2.5 m，"
            "A 点距地面的高度 h＝1.95 m，雪块与屋顶的动摩擦因数 μ＝0.125。不计空气阻力，雪块质量不变，"
            "取 sin 37°＝0.6，重力加速度大小 g＝10 m/s²。求：")
    cfg = {
        "meta": {"answer_id": "B-05", "question_id": "B-05", "group": "B",
                 "source": "2025 黑吉辽蒙卷", "question_no": 13, "full_score": 10,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T19:55:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [{"fig_no": 1,
                         "caption": "倾角 37° 的屋顶，雪块自 O 点下滑至 A 点后离开，A 距地面 h；原文无图题",
                         "caption_source": "none", "is_required": False}],
            "subquestions": [
                {"no": "(1)", "text": "雪块从 A 点离开屋顶时的速度大小 v₀。", "score": 4},
                {"no": "(2)", "text": "雪块落地时的速度大小 v₁，及其速度方向与水平方向的夹角 α。", "score": 6},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "雪块", "mass_symbol": "m", "note": "质量不变（不融化），视为质点；先沿屋顶下滑、后斜抛"},
                {"id": "obj2", "name": "屋顶", "mass_symbol": "m", "note": "倾角 37°，O 到 A 长 2.5 m"},
            ],
            "given": [
                {"symbol": "x", "value": 2.5, "unit": "m", "text": "O、A 间距离 x＝2.5 m"},
                {"symbol": "h", "value": 1.95, "unit": "m", "text": "A 点距地面高度 h＝1.95 m"},
                {"symbol": "mu", "value": 0.125, "unit": "1", "text": "雪块与屋顶动摩擦因数 μ＝0.125"},
                {"symbol": "g", "value": 10, "unit": "m/s^2", "text": "重力加速度 g＝10 m/s²"},
                {"symbol": "theta", "value": 37, "unit": "deg", "text": "屋顶倾角 θ＝37°（sin 37°＝0.6、cos 37°＝0.8）"},
            ],
            "process_segments": [
                {"no": 1, "name": "屋顶匀加速下滑", "start": "雪块在 O 点由静止", "end": "到达 A 点，速度 v（沿屋面向下）"},
                {"no": 2, "name": "离屋顶后斜抛落地", "start": "雪块以 v 沿 37° 向下飞出", "end": "落到地面，速度 v1"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "v", "text": "离开屋顶时的速度"},
                {"no": "(2)", "quantity": "v1", "text": "落地速度"},
                {"no": "(2)", "quantity": "angA", "text": "落地速度与水平方向的夹角"},
            ],
            "assumptions": [
                "沿屋顶下滑时正压力 mg cos 37°，摩擦力 μmg cos 37°；sin 37°＝0.6、cos 37°＝0.8",
                "离开屋顶后只受重力，机械能守恒；斜抛的水平分速度不变",
                "离开速度与水平方向夹角为 37°（沿屋面向下），故水平分量 v cos 37°＝0.8v",
                "角度符号 angA 在 nums 中以弧度代入三角函数，在 value 中以度为单位作答",
            ],
        },
        "nums": {"x": 2.5, "h": 1.95, "mu": 0.125, "g": 10.0,
                 "a": 5.0, "v": 5.0, "v1": 8.0, "angA": 1.0471975511965976},
        "allowed_symbols": ["x", "h", "mu", "g", "a", "v", "v1", "angA", "m"],
        "prior": "high",
        "reason": "金标参考解：斜面匀加速 + 斜抛机械能守恒与速度分解；L1 逐式回代，10/10 满分",
        "steps": [
            dict(pid="B-05-S01", title="沿屋顶：mg sin37° − μmg cos37° = ma", kind="equation", score=2,
                 stmt="沿屋面向下：mg sin 37°−μmg cos 37°＝ma，约去 m 得 a＝10×(0.6−0.125×0.8)＝5 m/s²。",
                 latex="m g \\sin 37° - \\mu m g \\cos 37° = m a",
                 sympy="g*Rational(3,5) - mu*g*Rational(4,5) - a",
                 l2="N/kg＝m/s²",
                 l4="漏 cos 项或 sin、cos 配错本步 0 分；μ 未取 0.125 本步 0 分；方程对即给分，结果错扣 0.5（1 分步记 0）（口径）",
                 val={"symbol": "a", "number": 5.0, "exact": "5", "unit": "m/s^2",
                      "direction": None, "sig_figs": 1},
                 laws=["L-04", "L-05"]),
            dict(pid="B-05-S02", title="v₀² = 2ax，v = 5 m/s", kind="equation", score=2,
                 stmt="自 O 点静止匀加速 2.5 m：v²＝2ax＝2×5×2.5＝25，v＝5 m/s。",
                 latex="v^{2} = 2 a x",
                 sympy="v**2 - 2*a*x",
                 l2="m²/s²",
                 l4="写成 v＝at 又未求 t 本步 0 分；只写 5 不写单位 m/s 本步 0 分（口径）",
                 val={"symbol": "v", "number": 5.0, "exact": "5", "unit": "m/s",
                      "direction": None, "sig_figs": 1},
                 laws=["L-01"]),
            dict(pid="B-05-S03", title="离屋顶后机械能守恒", kind="equation", score=2,
                 stmt="从 A 点到落地只有重力做功：½mv1²＝½mv²＋mgh，即 ½v1²＝½×25＋10×1.95。",
                 latex="\\frac{1}{2} m v_{1}^{2} = \\frac{1}{2} m v^{2} + m g h",
                 sympy="Rational(1,2)*v1**2 - Rational(1,2)*v**2 - g*h",
                 l2="各项均为 J",
                 l4="漏 ½mv² 项（把离屋顶速度当作零）本步 0 分；高度差取 h 以外的值本步 0 分（口径）",
                 laws=["L-09"]),
            dict(pid="B-05-S04", title="v₁ = 8 m/s", kind="discussion", score=1,
                 stmt="v1²＝25＋39＝64，故 v1＝8 m/s。",
                 latex="v_{1} = 8",
                 sympy="v1 - 8",
                 l2="m/s",
                 l4="只写 8 不写单位 m/s 本步 0 分；写成 √25+19.5 未化简本步 0 分（口径）",
                 val={"symbol": "v1", "number": 8.0, "exact": "8", "unit": "m/s",
                      "direction": None, "sig_figs": 1},
                 laws=["L-09"]),
            dict(pid="B-05-S05", title="水平分速度不变：v₁cos α = v cos37°", kind="equation", score=2,
                 stmt="斜抛中水平分速度不变：v1 cos α＝v cos 37°＝5×0.8＝4 m/s。",
                 latex="v_{1} \\cos\\alpha = v \\cos 37°",
                 sympy="v1*cos(angA) - v*Rational(4,5)",
                 l2="m/s",
                 l4="把 α 当作速度与竖直方向夹角（得 30°）本步 0 分；用 v1 sin α 本步 0 分（口径）",
                 laws=["L-02"]),
            dict(pid="B-05-S06", title="cos α = 0.5，α = 60°", kind="discussion", score=1,
                 stmt="cos α＝4/8＝0.5，故 α＝60°。",
                 latex="\\cos\\alpha = \\frac{1}{2}",
                 sympy="cos(angA) - Rational(1,2)",
                 l2="无量纲",
                 l4="只写 60 不写单位、或写成 60 rad 本步 0 分；答 30° 本步 0 分（口径）",
                 val={"symbol": "angA", "number": 60.0, "exact": "60", "unit": "deg",
                      "direction": None, "sig_figs": 2},
                 laws=["L-02"]),
        ],
    }
    build(cfg)


# ---------------------------------------------------------------- B-06

def b06():
    """2024 福建 14：共点力平衡（水平）＋功的定义＋平均功率；有数值。

    两图为 (a) 情境图与 (b) 模型图，均非解题必需；原文 20 m 记作 x（白名单无 l）。
    """
    stem = ("我国古代劳动人民创造了璀璨的农耕文明。图(a)为《天工开物》中描绘的利用耕牛整理田地的场景，"
            "简化的物理模型如图(b)所示，人站立的农具视为与水平地面平行的木板，两条绳子相互平行且垂直于木板边缘。"
            "已知绳子与水平地面夹角 θ 为 25.5°，sin 25.5°＝0.43，cos 25.5°＝0.90。当每条绳子拉力 F 的大小为 250 N 时，"
            "人与木板沿直线匀速前进，在 15 s 内前进了 20 m，求此过程中：")
    cfg = {
        "meta": {"answer_id": "B-06", "question_id": "B-06", "group": "B",
                 "source": "2024 福建卷", "question_no": 14, "full_score": 14,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T20:05:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [
                {"fig_no": 1, "caption": "图(a)：《天工开物》农耕场景（情境图，不含解题数据）；原文无图题",
                 "caption_source": "none", "is_required": False},
                {"fig_no": 2, "caption": "图(b)：木板、两条平行绳与水平面成 θ＝25.5°；原文无图题，θ 与两绳平行已由文字给出",
                 "caption_source": "none", "is_required": False},
            ],
            "subquestions": [
                {"no": "(1)", "text": "地面对木板的阻力大小。", "score": 4},
                {"no": "(2)", "text": "两条绳子拉力所做的总功。", "score": 5},
                {"no": "(3)", "text": "两条绳子拉力的总功率。", "score": 5},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "人与木板", "mass_symbol": "m", "note": "作为整体沿直线匀速前进；受地面阻力 f"},
                {"id": "obj2", "name": "两条绳", "mass_symbol": "m", "note": "相互平行、垂直于木板边缘，与水平面成 25.5°，每条拉力 250 N"},
            ],
            "given": [
                {"symbol": "F", "value": 250, "unit": "N", "text": "每条绳子拉力 F＝250 N（两条共 2F）"},
                {"symbol": "x", "value": 20, "unit": "m", "text": "15 s 内前进了 20 m —— 位移记作 x"},
                {"symbol": "t", "value": 15, "unit": "s", "text": "所用时间 t＝15 s"},
                {"symbol": "theta", "value": 25.5, "unit": "deg",
                 "text": "绳与水平地面夹角 θ＝25.5°（cos 25.5°＝0.90、sin 25.5°＝0.43）"},
            ],
            "process_segments": [
                {"no": 1, "name": "匀速直线前进", "start": "两绳各以 250 N 拉木板", "end": "15 s 内前进 20 m"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "f", "text": "地面对木板的阻力"},
                {"no": "(2)", "quantity": "W", "text": "两绳拉力做的总功"},
                {"no": "(3)", "quantity": "P", "text": "两绳拉力的总功率"},
            ],
            "assumptions": [
                "匀速前进 ⇒ 水平方向合力为零；竖直方向的支持力与重力不参与本题求解",
                "两绳平行且各与水平面成 25.5°，水平分量各为 F cos 25.5°、共 2F cos 25.5°",
                "功按定义式算：W＝2F·x·cos 25.5°（位移沿水平方向，取拉力在位移方向上的投影）",
                "第 (3) 问求 15 s 内的平均功率 P＝W/t；t 取 15 s（不是 20 s），位移取 20 m（不是 15 m）",
            ],
        },
        "nums": {"F": 250.0, "x": 20.0, "t": 15.0, "f": 450.0, "W": 9000.0, "P": 600.0},
        "allowed_symbols": ["F", "f", "W", "P", "x", "t"],
        "prior": "high",
        "reason": "金标参考解：水平方向平衡 + 功的定义 + 平均功率；L1 逐式回代，14/14 满分",
        "steps": [
            dict(pid="B-06-S01", title="匀速前进 ⇒ 水平方向合力为零", kind="judgment", score=1,
                 stmt="人与木板沿直线匀速前进，加速度为零；水平方向只有两绳拉力的水平分量与地面阻力，二者等大反向。",
                 crit=dict(expr="Fnet", expected=0, comparator="eq",
                           text="匀速前进 ⇒ 水平方向合力为零：两绳拉力的水平分量之和等于地面阻力。"),
                 l2="N",
                 l4="把匀速当作有加速度本步 0 分；只写「平衡」未指明水平方向本步 0 分（口径）",
                 laws=["L-03"]),
            dict(pid="B-06-S02", title="2F cos25.5° = f", kind="equation", score=2,
                 stmt="水平方向：两条绳的水平分量之和等于阻力，2F cos 25.5°＝f，即 2×250×0.90＝450 N。",
                 latex="2 F \\cos 25.5° = f",
                 sympy="2*F*Rational(9,10) - f",
                 l2="N",
                 l4="漏系数 2（按单绳算）本步 0 分；用 sin25.5° 本步 0 分（口径）",
                 laws=["L-03"]),
            dict(pid="B-06-S03", title="f = 450 N", kind="discussion", score=1,
                 stmt="地面对木板的阻力大小为 450 N（方向与前进方向相反）。",
                 latex="f = 450",
                 sympy="f - 450",
                 l2="N",
                 l4="只写 450 不写单位 N 本步 0 分；写成 225 N（单绳）本步 0 分（口径）",
                 val={"symbol": "f", "number": 450.0, "exact": "450", "unit": "N",
                      "direction": None, "sig_figs": 2},
                 laws=["L-03"]),
            dict(pid="B-06-S04", title="W = 2F·x·cos25.5°", kind="equation", score=3,
                 stmt="两绳拉力做的总功：W＝2F·x·cos 25.5°（位移沿水平方向，取拉力在位移方向的投影），"
                      "即 2×250×20×0.90。",
                 latex="W = 2 F x \\cos 25.5°",
                 sympy="W - 2*F*x*Rational(9,10)",
                 l2="N·m＝J",
                 l4="漏位移投影直接写 W＝2Fx 本步 0 分；只算一根绳本步 0 分（口径）",
                 laws=["L-08"]),
            dict(pid="B-06-S05", title="W = 9.0×10³ J", kind="discussion", score=2,
                 stmt="W＝450×20 J＝9.0×10³ J。",
                 latex="W = 9000",
                 sympy="W - 9000",
                 l2="J",
                 l4="数量级错（9.0×10² 或 9.0×10⁴）本步 0 分；只写 9000 不写单位 J 本步 0 分（口径）",
                 val={"symbol": "W", "number": 9000.0, "exact": "9000", "unit": "J",
                      "direction": None, "sig_figs": 2},
                 laws=["L-08"]),
            dict(pid="B-06-S06", title="所求为 15 s 内的平均功率", kind="judgment", score=1,
                 stmt="题目问「此过程中」的功率，即 15 s 内的平均功率，用 P＝W/t；不是某一时刻的瞬时功率 P＝Fv"
                      "（这里的 v 是平均速度，含义需说明）。",
                 crit=dict(expr="P", expected=None, comparator="qualitative",
                           text="「此过程中」的功率指 15 s 内的平均功率，用 P＝W/t 求；若用 P＝Fv，v 必须说明是平均速度。"),
                 l2="W（功率 P）",
                 l4="把 t 取成 20 s（或把位移取成 15 m）本步 0 分；只写 P＝Fv 未说明 v 的含义本步 0 分；"
                    "本步只判是否辨识为平均功率，列式分在 S07（口径）",
                 laws=["L-08"]),
            dict(pid="B-06-S07", title="P = W/t = 9.0×10³/15", kind="equation", score=2,
                 stmt="平均功率 P＝W/t＝9.0×10³/15 W。",
                 latex="P = \\frac{W}{t}",
                 sympy="P - W/t",
                 l2="J/s＝W",
                 l4="时间取 20 s 或位移取 15 m 本步 0 分；用 (1) 的 f 代替 2F 本步 0 分（口径）",
                 laws=["L-08"]),
            dict(pid="B-06-S08", title="P = 600 W", kind="discussion", score=2,
                 stmt="P＝600 W。",
                 latex="P = 600",
                 sympy="P - 600",
                 l2="W",
                 l4="只写 600 不写单位 W 本步 0 分；写成 60 W（数量级错）本步 0 分（口径）",
                 val={"symbol": "P", "number": 600.0, "exact": "600", "unit": "W",
                      "direction": None, "sig_figs": 2},
                 laws=["L-08"]),
        ],
    }
    build(cfg)


# ---------------------------------------------------------------- B-07

def b07():
    """2023 北京 18：摆球下落＋最低点向心力＋完全非弹性碰撞；全符号，L1 全 na。

    碰撞损失的机械能记作 Qheat（白名单无 ΔE）。
    """
    stem = ("如图所示，质量为 m 的小球 A 用一不可伸长的轻绳悬挂在 O 点，在 O 点正下方的光滑桌面上有一个与 A "
            "完全相同的静止小球 B，B 距 O 点的距离等于绳长 L。现将 A 拉至某一高度，由静止释放，A 以速度 v "
            "在水平方向和 B 发生正碰并粘在一起。重力加速度为 g。求：")
    cfg = {
        "meta": {"answer_id": "B-07", "question_id": "B-07", "group": "B",
                 "source": "2023 北京卷", "question_no": 18, "full_score": 9,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T20:10:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [{"fig_no": 1,
                         "caption": "轻绳悬于 O 点、球 A 拉至高度 H 释放，O 正下方桌面上的球 B；原文无图题",
                         "caption_source": "none", "is_required": False}],
            "subquestions": [
                {"no": "(1)", "text": "A 释放时距桌面的高度 H。", "score": 2},
                {"no": "(2)", "text": "碰撞前瞬间绳子的拉力大小 F。", "score": 3},
                {"no": "(3)", "text": "碰撞过程中系统损失的机械能 ΔE。", "score": 4},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "小球 A", "mass_symbol": "m", "note": "质量 m，用长 L 的轻绳悬于 O 点，自高度 H 释放"},
                {"id": "obj2", "name": "小球 B", "mass_symbol": "m", "note": "与 A 完全相同（质量 m），静止在 O 正下方桌面"},
            ],
            "given": [
                {"symbol": "m", "value": None, "unit": "kg", "text": "A、B 质量均为 m（符号量）"},
                {"symbol": "L", "value": None, "unit": "m", "text": "绳长 L，B 距 O 点也为 L（符号量）"},
                {"symbol": "v", "value": None, "unit": "m/s", "text": "A 与 B 碰前的速度 v（符号量）"},
                {"symbol": "g", "value": None, "unit": "m/s^2", "text": "重力加速度 g（符号量）"},
            ],
            "process_segments": [
                {"no": 1, "name": "A 下摆至最低点", "start": "A 在高度 H 处静止释放", "end": "A 到达最低点，速度 v"},
                {"no": 2, "name": "A 与 B 完全非弹性碰撞", "start": "A 在最低点与静止的 B 接触", "end": "两者粘在一起，共同速度 v′"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "H", "text": "释放高度"},
                {"no": "(2)", "quantity": "F", "text": "碰前瞬间绳的拉力"},
                {"no": "(3)", "quantity": "Qheat", "text": "碰撞损失的机械能"},
            ],
            "assumptions": [
                "绳不可伸长、下摆过程拉力始终与速度垂直，不做功；只有重力做功，机械能守恒",
                "最低点绳竖直，向心方向竖直向上：F−mg 提供向心力",
                "碰后粘在一起 ⇒ 完全非弹性碰撞：动量守恒、动能减少，共同速度 v′＝v/2",
                "损失机械能记作 Qheat（白名单无 ΔE，见回执 §需上报）",
            ],
        },
        "nums": {},
        "allowed_symbols": ["m", "g", "H", "v", "L", "F", "v1", "Qheat"],
        "prior": "high",
        "reason": "金标参考解：全符号 + 摆球机械能守恒 + 最低点向心力 + 完全非弹性碰撞；L1 全步 na",
        "steps": [
            dict(pid="B-07-S01", title="A 下摆：mgH = ½mv²", kind="equation", score=2,
                 stmt="A 自高度 H 静止下摆到最低点，绳拉力不做功：mgH＝½mv²。",
                 latex="m g H = \\frac{1}{2} m v^{2}",
                 sympy="m*g*H - Rational(1,2)*m*v**2",
                 l2="J",
                 l4="用绳长 L 代替高度 H 本步 0 分；写成 mgH＝mv²（漏 ½）本步 0 分（口径）",
                 laws=["L-09"]),
            dict(pid="B-07-S02", title="最低点沿绳方向列向心力式", kind="equation", score=2,
                 stmt="最低点绳竖直向上，拉力与重力的合力提供向心力：F−mg＝mv²/L。",
                 latex="F - m g = m \\frac{v^{2}}{L}",
                 sympy="F - m*g - m*v**2/L",
                 l2="N",
                 l4="写成 F＝mv²/L（漏重力）本步 0 分；分母用 H 本步 0 分（口径）",
                 laws=["L-06"]),
            dict(pid="B-07-S03", title="F = mg + mv²/L", kind="discussion", score=1,
                 stmt="F＝mg＋mv²/L；若用 H 表示，由 v²＝2gH 得 F＝mg＋2mgH/L，但最终结果不得含未消去的 H。",
                 latex="F = m g + m \\frac{v^{2}}{L}",
                 sympy="F - m*g - m*v**2/L",
                 l2="N",
                 l4="结果含未消去的 H 本步 0 分；写成 F＝mg−mv²/L 本步 0 分（口径）",
                 val={"symbol": "F", "number": None, "exact": "m*g + m*v^2/L", "unit": "N",
                      "direction": "+y", "sig_figs": None},
                 laws=["L-06"]),
            dict(pid="B-07-S04", title="粘在一起 ⇒ 完全非弹性，v′ = v/2", kind="judgment", score=1,
                 stmt="两球碰后粘在一起，是完全非弹性碰撞：动量守恒 mv＝2mv′，故共同速度 v′＝v/2（不是弹性碰撞的"
                      "「B 得 v、A 停」）。",
                 crit=dict(expr="v1", expected="v/2", comparator="eq",
                           text="粘在一起 ⇒ 完全非弹性碰撞，动量守恒 mv＝2mv′，得 v′＝v/2；弹性碰撞的结论不适用。"),
                 l2="m/s",
                 l4="把碰撞当作弹性（B 得 v、A 停）本步 0 分；只写「动量守恒」未给出 v′ 本步 0 分（口径）",
                 laws=["L-12"]),
            dict(pid="B-07-S05", title="ΔE = ½mv² − ½·2m·v′²", kind="equation", score=2,
                 stmt="碰撞损失的机械能等于碰前总动能减碰后总动能：ΔE＝½mv²−½·2m·v′²。",
                 latex="\\Delta E = \\frac{1}{2} m v^{2} - \\frac{1}{2} \\cdot 2 m v_{1}^{2}",
                 sympy="Qheat - (Rational(1,2)*m*v**2 - Rational(1,2)*2*m*v1**2)",
                 l2="J",
                 l4="漏碰后动能项（把 ΔE 写成 ½mv²）本步 0 分；碰后质量写成 m 本步 0 分（口径）",
                 laws=["L-12", "L-10"]),
            dict(pid="B-07-S06", title="ΔE = ¼mv²", kind="discussion", score=1,
                 stmt="代入 v′＝v/2：ΔE＝½mv²−m·(v²/4)＝¼mv²。",
                 latex="\\Delta E = \\frac{1}{4} m v^{2}",
                 sympy="Qheat - Rational(1,4)*m*v**2",
                 l2="J",
                 l4="写成 ½mv² 或 ⅛mv² 本步 0 分；结果含 v′ 未消去本步 0 分（口径）",
                 val={"symbol": "Qheat", "number": None, "exact": "m*v^2/4", "unit": "J",
                      "direction": None, "sig_figs": None},
                 laws=["L-12", "L-10"]),
        ],
    }
    build(cfg)


# ---------------------------------------------------------------- B-08

def b08():
    """2023 全国甲 24：弹簧弹射＋平抛＋反弹衰减；全符号，L1 全 na。

    落地前竖直分速度记 vdown、反弹后记 vup（白名单无 vy/vy′）。
    """
    stem = ("如图，光滑水平桌面上有一轻质弹簧，其一端固定在墙上。用质量为 m 的小球压弹簧的另一端，"
            "使弹簧的弹性势能为 E_p。释放后，小球在弹簧作用下从静止开始在桌面上运动，与弹簧分离后，从桌面水平飞出。"
            "小球与水平地面碰撞后瞬间，其平行于地面的速度分量与碰撞前瞬间相等；垂直于地面的速度分量大小变为碰撞前瞬间的 4/5。"
            "小球与地面碰撞后，弹起的最大高度为 h。重力加速度大小为 g，忽略空气阻力。求：")
    cfg = {
        "meta": {"answer_id": "B-08", "question_id": "B-08", "group": "B",
                 "source": "2023 全国甲卷", "question_no": 24, "full_score": 12,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T20:15:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [{"fig_no": 1,
                         "caption": "墙上弹簧、桌面、小球平抛与地面反弹；原文无图题，过程与几何量已由文字给出",
                         "caption_source": "none", "is_required": False}],
            "subquestions": [
                {"no": "(1)", "text": "小球离开桌面时的速度大小。", "score": 4},
                {"no": "(2)", "text": "小球第一次落地点距桌面上其飞出点的水平距离。", "score": 8},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "小球", "mass_symbol": "m", "note": "质量 m；被弹簧弹出后平抛，落地反弹"},
                {"id": "obj2", "name": "轻质弹簧", "mass_symbol": "m", "note": "一端固定于墙，初始弹性势能 E_p，全部转化为小球动能"},
            ],
            "given": [
                {"symbol": "m", "value": None, "unit": "kg", "text": "小球质量 m（符号量）"},
                {"symbol": "Ep", "value": None, "unit": "J", "text": "弹簧初始弹性势能 E_p（符号量）"},
                {"symbol": "h", "value": None, "unit": "m", "text": "碰撞后弹起的最大高度 h（符号量）"},
                {"symbol": "g", "value": None, "unit": "m/s^2", "text": "重力加速度 g（符号量）"},
            ],
            "process_segments": [
                {"no": 1, "name": "弹簧弹射（桌面段）", "start": "压紧弹簧、小球静止", "end": "弹簧恢复原长，小球以 v 水平飞出"},
                {"no": 2, "name": "平抛与反弹", "start": "小球自桌面水平飞出", "end": "落地反弹至最大高度 h（水平分速度不变、竖直分量变 4/5）"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "v", "text": "离开桌面时的速度"},
                {"no": "(2)", "quantity": "x", "text": "第一次落地点到飞出点的水平距离"},
            ],
            "assumptions": [
                "桌面光滑：弹簧弹性势能全部转化为小球动能，无摩擦损失",
                "离开桌面后只受重力：水平分速度不变，竖直方向自由落体",
                "落地反弹只改变竖直分速度（变为碰前的 4/5），水平分速度不变；反弹高度只由竖直分量决定",
                "竖直分速度记 vdown（碰前）、vup（反弹后），白名单无 vy/vy′ 记号",
            ],
        },
        "nums": {},
        "allowed_symbols": ["m", "Ep", "h", "g", "v", "vdown", "vup", "x"],
        "prior": "high",
        "reason": "金标参考解：全符号 + 弹簧势能转动能 + 平抛 + 反弹竖直分量衰减；L1 全步 na",
        "steps": [
            dict(pid="B-08-S01", title="E_p = ½mv²", kind="equation", score=2,
                 stmt="桌面光滑，弹簧的弹性势能全部转化为小球动能：E_p＝½mv²（不再另加 mgh，桌面水平）。",
                 latex="E_{p} = \\frac{1}{2} m v^{2}",
                 sympy="Ep - Rational(1,2)*m*v**2",
                 l2="J",
                 l4="漏 ½ 本步 0 分；把弹簧做的功另加 mgh 本步 0 分（口径）",
                 laws=["L-09"]),
            dict(pid="B-08-S02", title="v = √(2E_p/m)", kind="discussion", score=2,
                 stmt="v＝√(2E_p/m)。",
                 latex="v = \\sqrt{\\frac{2 E_{p}}{m}}",
                 sympy="v**2 - 2*Ep/m",
                 l2="m²/s²",
                 l4="根号内写成 E_p/m（漏 2）本步 0 分；结果含未消去的量本步 0 分（口径）",
                 val={"symbol": "v", "number": None, "exact": "sqrt(2*Ep/m)", "unit": "m/s",
                      "direction": "+x", "sig_figs": None},
                 laws=["L-09"]),
            dict(pid="B-08-S03", title="反弹高度只由竖直分量决定", kind="judgment", score=1,
                 stmt="碰后水平分速度不变、竖直分量变为碰前的 4/5；反弹的最大高度只由反弹后的竖直分量决定，"
                      "与水平分量无关。",
                 crit=dict(expr="vup", expected="Rational(4,5)*vdown", comparator="eq",
                           text="碰后竖直分量变为碰前的 4/5（vup＝4vdown/5），水平分量不变；反弹高度 h 只由 vup 决定。"),
                 l2="m/s",
                 l4="把 4/5 用到水平分量本步 0 分；认为反弹高度由合速度决定本步 0 分（口径）",
                 laws=["L-02"]),
            dict(pid="B-08-S04", title="h = v_y′²/(2g) 反解 v_y", kind="equation", score=2,
                 stmt="反弹段：h＝vup²/(2g)，而 vup＝(4/5)vdown，故 vdown＝(5/4)√(2gh)。",
                 latex="h = \\frac{v_{up}^{2}}{2 g}",
                 sympy="vdown - Rational(5,4)*sqrt(2*g*h)",
                 l2="m",
                 l4="漏 (4/5) 系数（把 vup 当作 vdown）本步 0 分；写成 h＝vup/g 本步 0 分（口径）",
                 laws=["L-02"]),
            dict(pid="B-08-S05", title="平抛：x = vt、v_y = gt", kind="equation", score=2,
                 stmt="平抛段：水平 x＝vt，竖直 vdown＝gt；消去 t 得 x＝v·vdown/g。",
                 latex="x = v \\frac{v_{down}}{g}",
                 sympy="x - v*vdown/g",
                 l2="m/s·(m/s)/(m/s²)＝m",
                 l4="漏竖直方向求 t 本步 0 分；t 直接取 √(2h/g)（用反弹高度）本步 0 分（口径）",
                 laws=["L-02", "L-01"]),
            dict(pid="B-08-S06", title="x = (5/2)√(hE_p/(mg))", kind="discussion", score=3,
                 stmt="代入 v＝√(2E_p/m)、vdown＝(5/4)√(2gh)：x＝(5/2)√(hE_p/(mg))。",
                 latex="x = \\frac{5}{2} \\sqrt{\\frac{h E_{p}}{m g}}",
                 sympy="x - Rational(5,2)*sqrt(h*Ep/(m*g))",
                 l2="m",
                 l4="系数错（5/4 或 5）本步 0 分；根号内漏 m 本步 0 分；（5/4)√(2hE_p/(mg)) 与正解差 √2 倍，同样 0 分（口径）",
                 val={"symbol": "x", "number": None, "exact": "5*sqrt(h*Ep/(m*g))/2", "unit": "m",
                      "direction": "+x", "sig_figs": None},
                 laws=["L-02"]),
        ],
    }
    build(cfg)


# ---------------------------------------------------------------- B-13

def b13():
    """2021 河北 13：斜面下滑＋追及相遇＋动量守恒；有数值。

    v0 是滑雪者的初速度（1.5 m/s），v 是拎起后的共同速度。
    """
    stem = ("如图，一滑雪道由 AB 和 BC 两段滑道组成，其中 AB 段倾角为 θ，BC 段水平，AB 段和 BC 段由一小段光滑圆弧连接。"
            "一个质量为 2 kg 的背包在滑道顶端 A 处由静止滑下，若 1 s 后质量为 48 kg 的滑雪者从顶端以 1.5 m/s 的初速度、"
            "3 m/s² 的加速度匀加速追赶，恰好在坡底光滑圆弧的水平处追上背包并立即将其拎起。"
            "背包与滑道的动摩擦因数为 μ＝1/12，重力加速度取 g＝10 m/s²，sin θ＝7/25，cos θ＝24/25，"
            "忽略空气阻力及拎包过程中滑雪者与背包的重心变化。求：")
    cfg = {
        "meta": {"answer_id": "B-13", "question_id": "B-13", "group": "B",
                 "source": "2021 河北卷", "question_no": 13, "full_score": 11,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T20:20:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [{"fig_no": 1,
                         "caption": "AB 段倾角 θ、BC 段水平，两段以光滑圆弧连接；背包与滑雪者先后自 A 出发；原文无图题",
                         "caption_source": "none", "is_required": False}],
            "subquestions": [
                {"no": "(1)", "text": "滑道 AB 段的长度。", "score": 5},
                {"no": "(2)", "text": "滑雪者拎起背包时这一瞬间的速度。", "score": 6},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "背包", "mass_symbol": "m", "note": "质量 2 kg，自 A 由静止滑下，a₁＝2 m/s²"},
                {"id": "obj2", "name": "滑雪者", "mass_symbol": "M", "note": "质量 48 kg，晚 1 s 出发，v₀＝1.5 m/s、a₂＝3 m/s²"},
            ],
            "given": [
                {"symbol": "m", "value": 2, "unit": "kg", "text": "背包质量 m＝2 kg"},
                {"symbol": "M", "value": 48, "unit": "kg", "text": "滑雪者质量 M＝48 kg"},
                {"symbol": "mu", "value": 1.0/12, "unit": "1", "text": "背包与滑道的动摩擦因数 μ＝1/12"},
                {"symbol": "g", "value": 10, "unit": "m/s^2", "text": "重力加速度 g＝10 m/s²"},
                {"symbol": "v0", "value": 1.5, "unit": "m/s", "text": "滑雪者初速度 v₀＝1.5 m/s（晚 1 s 出发）"},
                {"symbol": "a2", "value": 3, "unit": "m/s^2", "text": "滑雪者加速度 a₂＝3 m/s²"},
            ],
            "process_segments": [
                {"no": 1, "name": "背包沿 AB 下滑", "start": "背包在 A 点由静止释放（t＝0）", "end": "到达坡底圆弧处"},
                {"no": 2, "name": "滑雪者追赶", "start": "t＝1 s 滑雪者自 A 以 1.5 m/s 出发", "end": "在坡底追上背包"},
                {"no": 3, "name": "拎起背包（瞬间）", "start": "两者在坡底接触", "end": "以共同速度 v 继续运动"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "x", "text": "AB 段长度"},
                {"no": "(2)", "quantity": "v", "text": "拎起瞬间的共同速度"},
            ],
            "assumptions": [
                "sin θ＝7/25、cos θ＝24/25 取题给值；背包下滑时正压力 mg cos θ",
                "计时起点取背包出发时刻：背包滑行 t，滑雪者滑行 t−1（因晚 1 s 出发）",
                "追上时两者位移相同（同一段 AB），背包位移 ½a₁t²、滑雪者位移 v₀(t−1)＋½a₂(t−1)²",
                "拎起瞬间极短，沿滑道方向动量守恒；两者同向运动，速度方向一致",
            ],
        },
        "nums": {"m": 2.0, "M": 48.0, "mu": 1.0/12, "g": 10.0, "v0": 1.5, "a2": 3.0,
                 "a1": 2.0, "t": 3.0, "x": 9.0, "v1": 6.0, "v2": 7.5, "v": 7.44},
        "allowed_symbols": ["m", "M", "mu", "g", "v0", "a1", "a2", "t", "x", "v1", "v2", "v"],
        "prior": "high",
        "reason": "金标参考解：斜面牛顿第二定律 + 追及方程 + 动量守恒；L1 逐式回代，11/11 满分",
        "steps": [
            dict(pid="B-13-S01", title="背包下滑：a₁ = 2 m/s²", kind="equation", score=2,
                 stmt="沿 AB：mg sin θ−μmg cos θ＝m a1，即 10×(7/25)−(1/12)×10×(24/25)＝2 m/s²。",
                 latex="m g \\sin\\theta - \\mu m g \\cos\\theta = m a_{1}",
                 sympy="g*Rational(7,25) - mu*g*Rational(24,25) - a1",
                 l2="N/kg＝m/s²",
                 l4="μ 代入 1/12 时漏 cosθ 本步 0 分；sin、cos 配错本步 0 分；方程对即给分，结果错扣 0.5（口径）",
                 val={"symbol": "a1", "number": 2.0, "exact": "2", "unit": "m/s^2",
                      "direction": None, "sig_figs": 1},
                 laws=["L-04", "L-05"]),
            dict(pid="B-13-S02", title="追及条件：两段位移相等", kind="equation", score=2,
                 stmt="设背包滑行 t 后追上，滑雪者只滑了 t−1：½a1t²＝v0(t−1)＋½a2(t−1)²。",
                 latex="\\frac{1}{2} a_{1} t^{2} = v_{0} (t - 1) + \\frac{1}{2} a_{2} (t - 1)^{2}",
                 sympy="Rational(1,2)*a1*t**2 - v0*(t - 1) - Rational(1,2)*a2*(t - 1)**2",
                 l2="m",
                 l4="滑雪者时间也取 t（漏晚 1 s）本步 0 分；漏初速度 v₀ 项本步 0 分（口径）",
                 laws=["L-01"]),
            dict(pid="B-13-S03", title="t = 3 s，AB 段长 x = 9 m", kind="discussion", score=1,
                 stmt="解方程得 t＝3 s（另一根为负舍去），AB 段长 x＝½a1t²＝9 m。",
                 latex="x = \\frac{1}{2} a_{1} t^{2}",
                 sympy="x - Rational(1,2)*a1*t**2",
                 l2="m",
                 l4="只写 9 不写单位 m 本步 0 分；t 取 2 s 本步 0 分（口径）",
                 val={"symbol": "x", "number": 9.0, "exact": "9", "unit": "m",
                      "direction": None, "sig_figs": 1},
                 laws=["L-01"]),
            dict(pid="B-13-S04", title="拎起瞬间沿滑道方向动量守恒", kind="judgment", score=1,
                 stmt="拎起过程极短，沿滑道方向的摩擦冲量可忽略；背包与滑雪者同向运动，系统沿滑道方向动量守恒。",
                 crit=dict(expr="p", expected=None, comparator="qualitative",
                           text="拎起瞬间极短，沿滑道方向合外力冲量远小于内力冲量、可不计；两者同向，故沿滑道方向动量守恒，"
                                "不能用弹性碰撞的结论。"),
                 l2="kg·m/s（动量 p）",
                 l4="把拎起当作弹性碰撞本步 0 分；漏「同向」说明本步 0 分（口径）",
                 laws=["L-12"]),
            dict(pid="B-13-S05", title="到坡底速度 v₁ = 6、v₂ = 7.5 m/s", kind="value", score=2,
                 stmt="背包 v1＝a1t＝6 m/s；滑雪者 v2＝v0＋a2(t−1)＝1.5＋3×2＝7.5 m/s。",
                 latex="v_{1} = a_{1} t",
                 sympy="v1 - a1*t",
                 l2="m/s",
                 l4="两者用同一速度代入本步 0 分；滑雪者时间取 3 s（应为 2 s）本步 0 分（口径）",
                 val={"symbol": "v1", "number": 6.0, "exact": "6", "unit": "m/s",
                      "direction": None, "sig_figs": 1},
                 laws=["L-01"]),
            dict(pid="B-13-S06", title="mv₁ + Mv₂ = (M+m)v", kind="equation", score=2,
                 stmt="沿滑道方向动量守恒：m v1＋M v2＝(M＋m)v，即 2×6＋48×7.5＝50v。",
                 latex="m v_{1} + M v_{2} = (M + m) v",
                 sympy="m*v1 + M*v2 - (M + m)*v",
                 l2="kg·m/s",
                 l4="漏背包动量项本步 0 分；质量取 2 kg 与 48 kg 之外的值本步 0 分（口径）",
                 laws=["L-12"]),
            dict(pid="B-13-S07", title="v ≈ 7.44 m/s", kind="discussion", score=1,
                 stmt="v＝(12＋360)/50＝7.44 m/s。",
                 latex="v = 7.44",
                 sympy="v - Rational(186,25)",
                 l2="m/s",
                 l4="只写 7.44 不写单位 m/s 本步 0 分；直接写 7.5 m/s（用滑雪者速度）本步 0 分（口径）",
                 val={"symbol": "v", "number": 7.44, "exact": "7.44", "unit": "m/s",
                      "direction": None, "sig_figs": 3},
                 laws=["L-12"]),
        ],
    }
    build(cfg)


# ---------------------------------------------------------------- B-10

def b10():
    """2022 山东 16：电动机功率＋两次匀速平衡＋关闭电动机后整体法；有数值。

    符号迁移：电流 I → Icur（I 是 sympy 虚数单位）、电压 U → Uvolt、内阻 R → Rr（R 已被半径占用）、
    配重 m₀ → M、绳拉力 T₁ → FT（白名单 FT 即张力）。
    这三枚符号是 T08f 新登记进白名单的，见回执 §需上报。
    """
    stem = ("某粮库使用额定电压 U＝380 V，内阻 R＝0.25 Ω 的电动机运粮，如图所示，配重和电动机连接小车的缆绳均平行于斜坡，"
            "装满粮食的小车以速度 v＝2 m/s 沿斜坡匀速上行，此时电流 I＝40 A，关闭电动机后，小车又沿斜坡上行路程 L "
            "到达卸粮点时，速度恰好为零。卸粮后，给小车一个向下的初速度，小车沿斜坡刚好匀速下行。"
            "已知小车质量 m₁＝100 kg，车上粮食质量 m₂＝1 200 kg，配重质量 m₀＝40 kg，取重力加速度 g＝10 m/s²，"
            "小车运动时受到的摩擦阻力与车及车上粮食总重力成正比，比例系数为 k，配重始终未接触地面，"
            "不计电动机自身机械摩擦损耗及缆绳质量。求：")
    cfg = {
        "meta": {"answer_id": "B-10", "question_id": "B-10", "group": "B",
                 "source": "2022 山东卷", "question_no": 16, "full_score": 9,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T20:30:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [{"fig_no": 1,
                         "caption": "斜坡上的小车（载粮）经缆绳与电动机、配重相连，缆绳平行于斜坡；原文无图题",
                         "caption_source": "none", "is_required": False}],
            "subquestions": [
                {"no": "(1)", "text": "比例系数 k 值。", "score": 5},
                {"no": "(2)", "text": "上行路程 L 值。", "score": 4},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "小车与粮食", "mass_symbol": "m1", "note": "车 100 kg、粮 1200 kg；沿斜坡上行，受摩擦阻力 k(m₁+m₂)g"},
                {"id": "obj2", "name": "配重", "mass_symbol": "M", "note": "质量 m₀＝40 kg，经缆绳与小车相连，始终未触地"},
                {"id": "obj3", "name": "电动机", "mass_symbol": "M", "note": "额定电压 380 V、内阻 0.25 Ω，工作时电流 40 A"},
            ],
            "given": [
                {"symbol": "Uvolt", "value": 380, "unit": "V", "text": "电动机额定电压 U＝380 V —— 记作 Uvolt"},
                {"symbol": "Icur", "value": 40, "unit": "A", "text": "工作电流 I＝40 A —— 记作 Icur（I 是 sympy 虚数单位）"},
                {"symbol": "Rr", "value": 0.25, "unit": "ohm", "text": "电动机内阻 R＝0.25 Ω —— 记作 Rr（R 已被半径占用）"},
                {"symbol": "v", "value": 2, "unit": "m/s", "text": "装满粮食时匀速上行的速度 v＝2 m/s"},
                {"symbol": "m1", "value": 100, "unit": "kg", "text": "小车质量 m₁＝100 kg"},
                {"symbol": "m2", "value": 1200, "unit": "kg", "text": "车上粮食质量 m₂＝1 200 kg"},
                {"symbol": "M", "value": 40, "unit": "kg", "text": "配重质量 m₀＝40 kg —— 记作 M"},
                {"symbol": "g", "value": 10, "unit": "m/s^2", "text": "重力加速度 g＝10 m/s²"},
            ],
            "process_segments": [
                {"no": 1, "name": "电动机牵引、满载匀速上行", "start": "电动机工作，电流 40 A", "end": "小车以 2 m/s 匀速上行（卸粮点之前）"},
                {"no": 2, "name": "关闭电动机后匀减速上行", "start": "关闭电动机、卸粮前", "end": "上行 L 后速度恰为零（到达卸粮点）"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "k", "text": "摩擦阻力比例系数"},
                {"no": "(2)", "quantity": "L", "text": "关闭电动机后上行的路程"},
            ],
            "assumptions": [
                "缆绳平行于斜坡：绳拉力沿斜面方向，配重拉力 M g 沿斜面向上（配重下行）",
                "满载匀速上行：T₁＋T₂＝(m₁＋m₂)g sin θ＋k(m₁＋m₂)g",
                "卸粮后匀速下行（只有车与配重）：m₁g sin θ＝M g＋k m₁ g，由此解出 sin θ 与 k",
                "关闭电动机后，车、粮、配重由缆绳连成一体、加速度大小相同，可作为整体；合外力为 (m₁＋m₂)g sinθ＋k(m₁＋m₂)g−Mg",
                "电动机功率分配按 UI＝I²R＋T₁v（不计机械摩擦损耗）",
            ],
        },
        "nums": {"Uvolt": 380.0, "Icur": 40.0, "Rr": 0.25, "v": 2.0, "m1": 100.0, "m2": 1200.0,
                 "M": 40.0, "g": 10.0, "FT": 7400.0, "theta": 0.5235987755982988, "k": 0.1,
                 "a": 5.522388059701493, "L": 0.36216216216216217},
        "allowed_symbols": ["Uvolt", "Icur", "Rr", "v", "m1", "m2", "M", "g",
                            "FT", "theta", "k", "a", "L"],
        "prior": "high",
        "reason": "金标参考解：电动机功率分配 + 两次匀速平衡 + 关闭电动机后整体法；L1 逐式回代，9/9 满分",
        "steps": [
            dict(pid="B-10-S01", title="电动机功率分配 UI = I²R + T₁v", kind="equation", score=1,
                 stmt="电动机输入功率 UI，其中 I²R 为内阻发热、T₁v 为牵引功率：UI＝I²R＋T₁v。",
                 latex="U I = I^{2} R_{r} + F_{T} v",
                 sympy="Uvolt*Icur - Icur**2*Rr - FT*v",
                 l2="V·A＝W；A²·Ω＝W；N·m/s＝W",
                 l4="漏 I²R 项（把输入功率全当机械功率）本步 0 分；写成 UI＝I²R＋T₁ 本步 0 分（口径）",
                 laws=["L-08"]),
            dict(pid="B-10-S02", title="T₁ = 7 400 N，配重 T₂ = 400 N", kind="value", score=1,
                 stmt="T₁＝(UI−I²R)/v＝(15 200−400)/2＝7 400 N；配重拉力 T₂＝Mg＝400 N。",
                 latex="F_{T} = \\frac{U I - I^{2} R_{r}}{v}",
                 sympy="FT - 7400",
                 l2="W/(m/s)＝N",
                 l4="漏配重拉力本步 0 分；T₁ 计算时把 v 取成 1 m/s 本步 0 分（口径）",
                 val={"symbol": "FT", "number": 7400.0, "exact": "7400", "unit": "N",
                      "direction": None, "sig_figs": 2},
                 laws=["L-08"]),
            dict(pid="B-10-S03", title="满载匀速上行沿斜面平衡", kind="equation", score=1,
                 stmt="满载匀速上行，沿斜面方向合力为零：T₁＋T₂＝(m₁＋m₂)g sin θ＋k(m₁＋m₂)g。",
                 latex="F_{T} + M g = (m_{1} + m_{2}) g \\sin\\theta + k (m_{1} + m_{2}) g",
                 sympy="FT + M*g - (m1 + m2)*g*sin(theta) - k*(m1 + m2)*g",
                 l2="N",
                 l4="漏 k 项或漏配重拉力本步 0 分；把 (m₁+m₂)g 写成 (m₁+m₀)g 本步 0 分（口径）",
                 laws=["L-03"]),
            dict(pid="B-10-S04", title="卸粮后匀速下行：m₁g sinθ = Mg + k m₁g", kind="equation", score=1,
                 stmt="卸粮后只有车与配重，匀速下行：m₁g sin θ＝M g＋k m₁ g。",
                 latex="m_{1} g \\sin\\theta = M g + k m_{1} g",
                 sympy="m1*g*sin(theta) - M*g - k*m1*g",
                 l2="N",
                 l4="把 m₂ 留在下行式里本步 0 分；漏 k 项本步 0 分（口径）",
                 laws=["L-03"]),
            dict(pid="B-10-S05", title="联立得 sinθ = 0.5、k = 0.1", kind="value", score=1,
                 stmt="两式联立：由下行式得 sin θ＝M/m₁＋k＝0.4＋k；代入上行式解得 k＝0.1、sin θ＝0.5。",
                 latex="k = \\frac{1}{10}",
                 sympy="k - Rational(1,10)",
                 l2="无量纲",
                 l4="只用上行式（缺方程）本步 0 分；k 取 0.2 本步 0 分（口径）",
                 val={"symbol": "k", "number": 0.1, "exact": "1/10", "unit": "1",
                      "direction": None, "sig_figs": 1},
                 laws=["L-03"]),
            dict(pid="B-10-S06", title="关闭电动机后车＋粮＋配重可作为整体", kind="judgment", score=1,
                 stmt="关闭电动机后，车、粮、配重由缆绳连成一体，沿斜面方向的加速度大小相同，可作为整体；"
                      "合外力为 (m₁＋m₂)g sin θ＋k(m₁＋m₂)g−M g。",
                 crit=dict(expr="Fnet", expected=None, comparator="qualitative",
                           text="关闭电动机后三者由缆绳相连、加速度相同，可作整体；合外力沿斜面向下为正："
                                "(m₁＋m₂)g sinθ＋k(m₁＋m₂)g−Mg。"),
                 l2="N",
                 l4="漏配重（把系统当成只有车与粮）本步 0 分；k 项符号取反本步 0 分（口径）",
                 laws=["L-04", "L-03"]),
            dict(pid="B-10-S07", title="a = F_合/(m₀+m₁+m₂)，再由 v² = 2aL", kind="equation", score=2,
                 stmt="对整体：F_合＝(m₁＋m₂)g sinθ＋k(m₁＋m₂)g−Mg＝7 400 N，总质量 m₀＋m₁＋m₂＝1 340 kg，"
                      "a＝7 400/1 340＝370/67 m/s²；再由 v²＝2aL 求 L。",
                 latex="a = \\frac{(m_{1} + m_{2}) g \\sin\\theta + k (m_{1} + m_{2}) g - M g}{M + m_{1} + m_{2}}",
                 sympy="(m1 + m2)*g*sin(theta) + k*(m1 + m2)*g - M*g - (M + m1 + m2)*a",
                 l2="N/kg＝m/s²",
                 l4="合外力除以 (m₁+m₂) 而漏配重质量本步 0 分；用动能定理但漏 k 项本步 0 分（口径）",
                 val={"symbol": "a", "number": 5.522388059701493, "exact": "370/67", "unit": "m/s^2",
                      "direction": None, "sig_figs": 3},
                 laws=["L-04"]),
            dict(pid="B-10-S08", title="L = 67/185 m ≈ 0.36 m", kind="discussion", score=1,
                 stmt="L＝v²/(2a)＝4/(2×370/67)＝67/185 m≈0.36 m。",
                 latex="L = \\frac{v^{2}}{2 a}",
                 sympy="L - v**2/(2*a)",
                 l2="(m/s)²/(m/s²)＝m",
                 l4="只写 0.36 不写单位 m 本步 0 分；写成 67/370 m（漏 2 倍）本步 0 分（口径）",
                 val={"symbol": "L", "number": 0.36216216216216217, "exact": "67/185", "unit": "m",
                      "direction": None, "sig_figs": 2},
                 laws=["L-01"]),
        ],
    }
    build(cfg)


def b15():
    """2023 江苏 15：45° 坡道动力学 → P→B 合功为零 → B 点斜抛射程。

    全符号题（d、μ、g 全是符号量）→ nums 为空，L1 逐步 na，只靠 L2 量纲与符号闭合。
    符号迁移：无。sin45°＝cos45°＝√2/2 直接写进 sympy，**不另立角度符号** ——
    题里没给 θ，硬造一个会出现「latex 写 45°、sympy 写 theta」两套表示。
    """
    stem = ("如图所示，滑雪道 AB 由坡道和水平道组成，且平滑连接，坡道倾角均为 45°。平台 BC 与缓冲坡 CD 相连。"
            "若滑雪者从 P 点由静止开始下滑，恰好到达 B 点。滑雪者现从 A 点由静止开始下滑，从 B 点飞出。"
            "已知 A、P 间的距离为 d，滑雪者与滑道间的动摩擦因数均为 μ，重力加速度为 g，不计空气阻力。求：")
    cfg = {
        "meta": {"answer_id": "B-15", "question_id": "B-15", "group": "B",
                 "source": "2023 江苏卷", "question_no": 15, "full_score": 12,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T21:10:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [{"fig_no": 1,
                         "caption": "滑雪道 AB（坡道倾角 45°＋水平道）与平台 BC、缓冲坡 CD；P 在坡道上、B 在坡道与平台交界处；原文无图题",
                         "caption_source": "none", "is_required": True}],
            "subquestions": [
                {"no": "(1)", "text": "滑雪者运动到 P 点的时间 t。", "score": 4},
                {"no": "(2)", "text": "滑雪者从 B 点飞出的速度大小 v。", "score": 4},
                {"no": "(3)", "text": "若滑雪者能着陆在缓冲坡 CD 上，平台 BC 的最大长度 L。", "score": 4},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "滑雪者", "mass_symbol": "m",
                 "note": "可视为质点；坡道、平台、缓冲坡的动摩擦因数同为 μ"},
            ],
            "given": [
                {"symbol": "d", "value": None, "unit": "m", "text": "A、P 间的距离 d（符号量）"},
                {"symbol": "mu", "value": None, "unit": "1", "text": "动摩擦因数 μ（符号量，各段同值）"},
                {"symbol": "g", "value": None, "unit": "m/s^2", "text": "重力加速度 g（符号量）"},
                {"symbol": "theta", "value": 45, "unit": "deg",
                 "text": "坡道倾角 45°；角度不入 T09 符号表，sin45°＝cos45°＝√2/2 直接写进方程"},
            ],
            "process_segments": [
                {"no": 1, "name": "A→P 沿 45° 坡道匀加速",
                 "start": "A 点由静止释放", "end": "到达 P 点（速度 v_P）"},
                {"no": 2, "name": "P→B 合功为零段",
                 "start": "P 点由静止（判据情景）", "end": "恰好到达 B 点，末速为零"},
                {"no": 3, "name": "B 点飞出后的斜抛",
                 "start": "B 点，速度沿坡道方向（与水平成 45°）", "end": "落回与 B 等高的落点"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "t", "text": "滑到 P 点所用时间"},
                {"no": "(2)", "quantity": "v", "text": "从 B 点飞出的速度大小"},
                {"no": "(3)", "quantity": "L", "text": "平台 BC 的最大长度"},
            ],
            "assumptions": [
                "坡道倾角全为 45°，故 sin45°＝cos45°＝√2/2：重力沿坡分量与摩擦力项同系数",
                "P→B 段由静止出发又恰好停在 B 点 ⇒ 该段合功为零；因此从 A 下滑时滑雪者经 P→B 后速度不变，v_B＝v_P",
                "B 点在坡道与平台交界处，速度方向仍沿坡道，飞出后是抛射角 45° 的斜抛，落回与 B 等高处",
                "「平台 BC 的最大长度」取斜抛水平射程（着陆点恰为 C 点时为最大）",
            ],
        },
        "nums": {},
        "allowed_symbols": ["m", "g", "mu", "a", "d", "t", "v", "L"],
        "prior": "high",
        "reason": "金标参考解：45° 坡道牛顿第二定律＋d＝½at² 求时＋合功为零段＋斜抛射程；全符号题 L1 全步 na，L2 逐式手判；12/12 满分",
        "steps": [
            dict(pid="B-15-S01", title="沿 45° 坡道列牛顿第二定律", kind="equation", score=2,
                 stmt="沿坡道方向：重力沿坡分量 mg sin 45° 减去摩擦力 μmg cos 45°，等于 ma。",
                 latex=r"m g \sin 45° - \mu m g \cos 45° = m a",
                 sympy="m*g*(sqrt(2)/2) - mu*m*g*(sqrt(2)/2) - m*a",
                 l2="N：mg 为 N、μ 无量纲，两项均为 N，右侧 ma 亦为 N",
                 l4="漏 μ 项（当作光滑）本步 0 分；sin45° 与 cos45° 按不同值代入本步 0 分",
                 laws=["L-04", "L-05"]),
            dict(pid="B-15-S02", title="由 d = ½at² 求下滑时间", kind="equation", score=2,
                 stmt="由上式得 a＝√2g(1−μ)/2，代入 d＝½at² 得 t＝√(2√2d/((1−μ)g))。",
                 latex=r"d = \frac{1}{2} a t^{2}",
                 sympy="d - Rational(1,2)*a*t**2",
                 l2="m：(m/s²)·s²＝m",
                 l4="漏 ½ 本步 0 分；把 d 当作水平位移本步 0 分（本段位移沿坡道）",
                 val={"symbol": "t", "number": None, "exact": "sqrt(2*sqrt(2)*d/((1-mu)*g))",
                      "unit": "s", "direction": None, "sig_figs": None},
                 laws=["L-01"]),
            dict(pid="B-15-S03", title="P→B 段合功为零、速度不变", kind="judgment", score=1,
                 stmt="P→B 段从静止出发、又恰好到达 B 点（末速为零），说明该段合功为零；"
                      "故从 A 下滑的滑雪者经这一段后速度不再改变，B 点速度大小等于 P 点速度大小。",
                 crit=dict(expr="v_B_vs_v_P", expected=None, comparator="qualitative",
                           text="P→B 段由静止出发又恰好停在 B 点，起末速度都为零 ⇒ 该段合功为零"
                                "（重力做正功与摩擦做负功等量抵消）。由此从 A 下滑的滑雪者经过 P→B 后速度不变，"
                                "v_B 的大小等于 v_P 的大小 —— 不是把 B 点速度取成非零的另一值，也不是取零。"),
                 l2="m/s（同为速度大小，量纲一致）",
                 l4="把 v_B 取成非零值（如沿用 A→P 段末速的某个变形）本步 0 分；未说明该判断本步 0 分",
                 laws=["L-08", "L-10"]),
            dict(pid="B-15-S04", title="由 v² = 2ad 求 B 点速度", kind="equation", score=2,
                 stmt="A→P 为初速为零的匀加速段，v²＝2ad，代入 a 得 v＝√(√2gd(1−μ))。",
                 latex=r"v^{2} = 2 a d",
                 sympy="v**2 - 2*a*d",
                 l2="(m/s)²＝(m/s²)·m",
                 l4="根号内漏 d 本步 0 分；用全程 A→B 列式但摩擦路程写错本步 0 分",
                 laws=["L-01"]),
            dict(pid="B-15-S05", title="结果只用 d、μ、g 表示", kind="discussion", score=1,
                 stmt="第 (2) 问结果写成 v＝√(√2gd(1−μ))：式中只剩题给的 d、μ、g，不含中间量 a、t。",
                 latex=r"v = \sqrt{\sqrt{2} g d (1 - \mu)}",
                 sympy="v**2 - sqrt(2)*g*d*(1 - mu)",
                 l2="m/s",
                 l4="结果含中间量 a 或 t 本步 0 分；把 √2 写成 1.4 未说明本步 0 分",
                 val={"symbol": "v", "number": None, "exact": "sqrt(sqrt(2)*g*d*(1-mu))",
                      "unit": "m/s", "direction": None, "sig_figs": None},
                 laws=["L-01"]),
            dict(pid="B-15-S06", title="B 点速度沿坡道、飞出为斜抛", kind="judgment", score=1,
                 stmt="B 点在坡道与平台的交界处，滑出速度仍沿坡道方向（与水平成 45°），不是水平；"
                      "飞出后只受重力，做抛射角 45° 的斜抛。",
                 crit=dict(expr="launch_dir", expected=None, comparator="qualitative",
                           text="B 点是坡道末端、速度仍沿坡道，故与水平方向夹 45°，抛射角为 45°；"
                                "飞出后只受重力，是斜抛而非平抛 —— 把 B 点速度当作水平的，后面的射程式全错。"),
                 l2="m/s（速度方向判定，量纲一致）",
                 l4="把 B 点速度当作水平本步 0 分；漏写抛射角本步 0 分",
                 laws=["L-01", "L-02"]),
            dict(pid="B-15-S07", title="斜抛射程为 v²/g", kind="equation", score=2,
                 stmt="斜抛落回与 B 等高处：飞行时间 t′＝2v sin45°/g，水平射程 L＝v cos45°·t′＝v²/g。",
                 latex=r"L = v \cos 45° \cdot \frac{2 v \sin 45°}{g}",
                 sympy="L - v*(sqrt(2)/2)*(2*v*(sqrt(2)/2)/g)",
                 l2="m：(m/s)·s＝m",
                 l4="漏 2 倍飞行时间本步 0 分；用 v²sin2θ/g 但 θ 取错本步 0 分",
                 laws=["L-01", "L-02"]),
            dict(pid="B-15-S08", title="L = √2 d (1−μ)", kind="discussion", score=1,
                 stmt="把 v²＝√2gd(1−μ) 代入 L＝v²/g，得平台 BC 的最大长度 L＝√2d(1−μ)。",
                 latex=r"L = \sqrt{2} d (1 - \mu)",
                 sympy="L - sqrt(2)*d*(1 - mu)",
                 l2="m",
                 l4="把 L 当作平台长度而漏抛体段本步 0 分；根号位置错（写成 √(2d)·(1−μ)）本步 0 分",
                 val={"symbol": "L", "number": None, "exact": "sqrt(2)*d*(1-mu)",
                      "unit": "m", "direction": None, "sig_figs": None},
                 laws=["L-01"]),
        ],
    }
    build(cfg)


def b16():
    """2024 江苏 15：含摩擦斜面三段（加速／匀速／减速）＋功率定义＋能量账。

    全符号题（μ、θ、L、m、v、g 全是符号量）→ nums 为空，L1 逐步 na。
    符号迁移：E₁（全过程增加的机械能）→ Efin；E₂（电动机消耗的总电能）→ W。
    白名单没有「总能量」类符号，Eini/Efin 只表示机械能的初末态，把电能记到 W（输入功）上比借 Eini 干净。
    「最终式对、化简错」判例落在 S08：见该步 statement。
    """
    stem = ("如图所示，粗糙斜面的动摩擦因数为 μ，倾角为 θ，斜面长为 L。一个质量为 m 的物块，在电动机作用下，"
            "从 A 点由静止加速至 B 点时达到最大速度 v，之后做匀速运动至 C 点，关闭电动机，从 C 点又恰好到达最高点 D，"
            "重力加速度为 g。求：")
    cfg = {
        "meta": {"answer_id": "B-16", "question_id": "B-16", "group": "B",
                 "source": "2024 江苏卷", "question_no": 15, "full_score": 12,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T21:20:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [{"fig_no": 1,
                         "caption": "粗糙斜面（倾角 θ、长 L）上 A→B→C→D 四点次序，物块经电动机牵引沿斜面上行；原文无图题",
                         "caption_source": "none", "is_required": False}],
            "subquestions": [
                {"no": "(1)", "text": "CD 段长 x。", "score": 4},
                {"no": "(2)", "text": "BC 段电动机的输出功率 P。", "score": 3},
                {"no": "(3)", "text": "全过程物块增加的机械能 E₁ 和电动机消耗的总电能 E₂ 的比值。", "score": 5},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "物块", "mass_symbol": "m", "note": "沿粗糙斜面上行，与斜面动摩擦因数 μ"},
                {"id": "obj2", "name": "电动机", "mass_symbol": "m", "note": "通过牵引力对物块做功；BC 段匀速、输出功率恒定"},
            ],
            "given": [
                {"symbol": "mu", "value": None, "unit": "1", "text": "斜面动摩擦因数 μ（符号量）"},
                {"symbol": "theta", "value": None, "unit": "deg", "text": "斜面倾角 θ（符号量）"},
                {"symbol": "L", "value": None, "unit": "m", "text": "斜面长 L（符号量）"},
                {"symbol": "m", "value": None, "unit": "kg", "text": "物块质量 m（符号量）"},
                {"symbol": "v", "value": None, "unit": "m/s", "text": "B 点达到的最大速度 v（符号量）"},
                {"symbol": "g", "value": None, "unit": "m/s^2", "text": "重力加速度 g（符号量）"},
            ],
            "process_segments": [
                {"no": 1, "name": "AB 段：牵引加速至最大速度",
                 "start": "A 点由静止", "end": "B 点，速度达 v（加速度降为零）"},
                {"no": 2, "name": "BC 段：匀速运动",
                 "start": "B 点（速度 v）", "end": "C 点，速度仍为 v"},
                {"no": 3, "name": "CD 段：关闭电动机后减速",
                 "start": "C 点（速度 v），电动机已关闭", "end": "D 点，速度恰为零（最高点）"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "x", "text": "CD 段长度"},
                {"no": "(2)", "quantity": "P", "text": "BC 段电动机输出功率"},
                {"no": "(3)", "quantity": "Efin", "text": "全过程物块增加的机械能 E₁"},
                {"no": "(3)", "quantity": "W", "text": "电动机消耗的总电能 E₂"},
            ],
            "assumptions": [
                "B 点「达到最大速度」＝牵引力刚降为与阻力相等，此后匀速；故 BC 段牵引力 F＝mg sinθ＋μmg cosθ",
                "CD 段电动机已关闭，只受重力分量与摩擦力，二者同向（沿斜面向下），减速至 D 点恰好为零",
                "全过程物块沿斜面上升 L，机械能增量只有重力势能部分 E₁＝mgL sinθ（动能初末均为零）",
                "电动机消耗的总电能＝物块机械能增量＋摩擦生热，即 E₂＝E₁＋μmg cosθ·L",
            ],
        },
        "nums": {},
        "allowed_symbols": ["m", "g", "mu", "theta", "L", "v", "a", "x", "P", "F", "Efin", "W"],
        "prior": "high",
        "reason": "金标参考解：含摩擦斜面三段＋功率定义式 P＝Fv＋电能—机械能—内能账；全符号题 L1 全步 na，L2 逐式手判；12/12 满分",
        "steps": [
            dict(pid="B-16-S01", title="CD 段上滑列牛顿第二定律", kind="equation", score=2,
                 stmt="CD 段关闭电动机后向上滑行，重力沿斜面分量与摩擦力同向（都沿斜面向下）："
                      "mg sinθ＋μmg cosθ＝ma。",
                 latex=r"m g \sin\theta + \mu m g \cos\theta = m a",
                 sympy="m*g*sin(theta) + mu*m*g*cos(theta) - m*a",
                 l2="N",
                 l4="摩擦项符号取反本步 0 分；漏 cosθ 本步 0 分（摩擦力按正压力 μmg cosθ 计）",
                 laws=["L-04", "L-05"]),
            dict(pid="B-16-S02", title="由 0−v²=−2ax 求 CD 段长", kind="equation", score=2,
                 stmt="CD 段末速为零：0−v²＝−2ax，代入 a 得 x＝v²/[2g(sinθ＋μcosθ)]。",
                 latex=r"0 - v^{2} = -2 a x",
                 sympy="-v**2 + 2*a*x",
                 l2="m²/s²",
                 l4="用 ½mv²＝mgx sinθ（漏摩擦）本步 0 分；漏负号但长度取正不扣分",
                 val={"symbol": "x", "number": None, "exact": "v**2/(2*g*(sin(theta)+mu*cos(theta)))",
                      "unit": "m", "direction": None, "sig_figs": None},
                 laws=["L-01", "L-04"]),
            dict(pid="B-16-S03", title="BC 段匀速、牵引力与阻力平衡", kind="equation", score=1,
                 stmt="BC 段匀速，牵引力与沿斜面的阻力平衡：F＝mg sinθ＋μmg cosθ（不再含 ma）。",
                 latex=r"F = m g \sin\theta + \mu m g \cos\theta",
                 sympy="F - m*g*sin(theta) - mu*m*g*cos(theta)",
                 l2="N",
                 l4="把牵引力写成 ma 本步 0 分；漏摩擦项本步 0 分",
                 laws=["L-03"]),
            dict(pid="B-16-S04", title="功率定义式 P = Fv", kind="equation", score=1,
                 stmt="BC 段牵引力恒定、速度恒为 v，输出功率用定义式 P＝Fv 计（F 取上一步的平衡值）。",
                 latex=r"P = F v",
                 sympy="P - F*v",
                 l2="N·m/s＝W",
                 l4="F 只含重力分量本步 0 分；漏 v 本步 0 分",
                 laws=["L-08"]),
            dict(pid="B-16-S05", title="结果只用 m、g、v、θ、μ 表示", kind="discussion", score=1,
                 stmt="把 F 代入 P＝Fv，得 P＝mgv(sinθ＋μcosθ)：式中只剩 m、g、v、θ、μ，不含中间量 a、x。",
                 latex=r"P = m g v (\sin\theta + \mu \cos\theta)",
                 sympy="P - m*g*v*(sin(theta) + mu*cos(theta))",
                 l2="W：kg·(m/s²)·(m/s)＝kg·m²/s³＝W",
                 l4="结果含中间量本步 0 分；把 P 当作平均功率本步 0 分（BC 段匀速，瞬时值＝平均值）",
                 val={"symbol": "P", "number": None, "exact": "m*g*v*(sin(theta)+mu*cos(theta))",
                      "unit": "W", "direction": None, "sig_figs": None},
                 laws=["L-08"]),
            dict(pid="B-16-S06", title="机械能增量 E₁ = mgL sinθ", kind="equation", score=2,
                 stmt="全过程物块沿斜面上升 L，初末动能均为零，机械能增量只有重力势能部分：E₁＝mgL sinθ。",
                 latex=r"E_{1} = m g L \sin\theta",
                 sympy="Efin - m*g*L*sin(theta)",
                 l2="J：kg·(m/s²)·m＝J",
                 l4="漏 sinθ（写成 mgL）本步 0 分；用 ½mv² 表示 E₁ 本步 0 分",
                 val={"symbol": "Efin", "number": None, "exact": "m*g*L*sin(theta)",
                      "unit": "J", "direction": None, "sig_figs": None},
                 laws=["L-08", "L-04"]),
            dict(pid="B-16-S07", title="总电能＝机械能增量＋摩擦生热", kind="equation", score=2,
                 stmt="电动机消耗的总电能一部分变成物块的机械能、一部分在斜面摩擦中变成内能："
                      "E₂＝E₁＋μmg cosθ·L。",
                 latex=r"E_{2} = E_{1} + \mu m g L \cos\theta",
                 sympy="W - Efin - mu*m*g*L*cos(theta)",
                 l2="J",
                 l4="漏摩擦生热项（写成 E₂＝E₁）本步 0 分；E₂ 按电动机输出功计而不含内耗不扣分",
                 val={"symbol": "W", "number": None, "exact": "m*g*L*(sin(theta)+mu*cos(theta))",
                      "unit": "J", "direction": None, "sig_figs": None},
                 laws=["L-08"]),
            dict(pid="B-16-S08", title="比值 = sinθ/(sinθ+μcosθ)", kind="discussion", score=1,
                 stmt="E₁/E₂＝mgL sinθ/[mgL sinθ＋μmgL cosθ]＝sinθ/(sinθ＋μcosθ)，mgL 整体约去。"
                      "化简只许对分子分母同除同一个量：同除 cosθ 得 tanθ/(μ＋tanθ)，与上式等价。"
                      "判例：把分母的 μcosθ 当成 μ 直接消掉、把该式化简成 1/(1＋μ)，最终式虽对但这一步化简错，"
                      "按 process_flaw 记 —— 分母里的 cosθ 与 sinθ 不是同一个量，不能与分子的 sinθ 对消。",
                 latex=r"\frac{E_{1}}{E_{2}} = \frac{\sin\theta}{\sin\theta + \mu \cos\theta}",
                 sympy="Efin*(sin(theta) + mu*cos(theta)) - W*sin(theta)",
                 l2="无量纲（J/J）",
                 l4="结果未约简（含 L、m、g）本步 0 分；写成倒数 E₂/E₁ 本步 0 分；"
                    "化简成 1/(1＋μ) 或 tanθ/(1＋μtanθ) 本步 0 分（分子分母没有同除同一个量）",
                 laws=["L-08"]),
        ],
    }
    build(cfg)


def b17():
    """2023 湖北 14：半圆挡板摩擦滑行 → 平抛 → 沿切线进圆弧 → 最高点临界 → 动能定理。

    全符号题（R、g 是符号量，只有 μ＝1/(2π) 是数）→ L1 逐步 na。
    符号迁移：v_D → v、v_A → v1、v_B → vb、v_C → vc（白名单只有 v/v1/v2/vb/vc 这几枚速度位）；
    H_BD → H。μ 保留 mu，1/(2π) 只进 nums 不回代（其余符号无值，整步仍 na）。
    cos60° 写 Rational(1,2)（精确），不写 sin(theta)。
    """
    stem = ("如图为某游戏装置原理示意图。水平桌面上固定一半圆形竖直挡板，其半径为 2R、内表面光滑，"
            "挡板的两端 A、B 在桌面边缘，B 与半径为 R 的固定光滑圆弧轨道 CDE 在同一竖直平面内，"
            "过 C 点的轨道半径与竖直方向的夹角为 60°。小物块以某一水平初速度由 A 点切入挡板内侧，"
            "从 B 点飞出桌面后，在 C 点沿圆弧切线方向进入轨道 CDE 内侧，并恰好能到达轨道的最高点 D。"
            "小物块与桌面之间的动摩擦因数为 1/(2π)，重力加速度大小为 g，忽略空气阻力，小物块可视为质点。求：")
    cfg = {
        "meta": {"answer_id": "B-17", "question_id": "B-17", "group": "B",
                 "source": "2023 湖北卷", "question_no": 14, "full_score": 15,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T21:35:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [{"fig_no": 1,
                         "caption": "桌面上半径 2R 的半圆竖直挡板（两端 A、B 在桌面边缘）、B 与半径 R 的圆弧轨道 CDE 的相对方位、过 C 点半径与竖直方向夹 60° 的参照方向；原文无图题",
                         "caption_source": "none", "is_required": True}],
            "subquestions": [
                {"no": "(1)", "text": "小物块到达 D 点的速度大小。", "score": 4},
                {"no": "(2)", "text": "B 和 D 两点间的高度差。", "score": 6},
                {"no": "(3)", "text": "小物块在 A 点的初速度大小。", "score": 5},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "小物块", "mass_symbol": "m",
                 "note": "可视为质点；沿挡板内侧滑行时与桌面摩擦，圆弧轨道光滑"},
            ],
            "given": [
                {"symbol": "R", "value": None, "unit": "m",
                 "text": "圆弧轨道 CDE 半径 R（符号量）；半圆挡板半径为 2R"},
                {"symbol": "mu", "value": 0.15915494309189535, "unit": "1",
                 "text": "动摩擦因数 μ＝1/(2π)（题给数值）"},
                {"symbol": "g", "value": None, "unit": "m/s^2", "text": "重力加速度 g（符号量）"},
                {"symbol": "theta", "value": 60, "unit": "deg",
                 "text": "过 C 点的轨道半径与竖直方向夹 60°；cos60°＝1/2 直接写进方程，不立角度符号"},
            ],
            "process_segments": [
                {"no": 1, "name": "A→B 沿半圆挡板内侧滑行",
                 "start": "A 点以水平初速 v_A 切入", "end": "B 点飞出桌面（速度 v_B）"},
                {"no": 2, "name": "B→C 平抛",
                 "start": "B 点水平飞出", "end": "C 点沿切线进入圆弧（速度 v_C）"},
                {"no": 3, "name": "C→D 沿圆弧上升",
                 "start": "C 点（速度 v_C）", "end": "最高点 D（速度 v_D，恰好通过）"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "v", "text": "D 点速度大小"},
                {"no": "(2)", "quantity": "H", "text": "B 与 D 的高度差"},
                {"no": "(3)", "quantity": "v1", "text": "A 点初速度大小"},
            ],
            "assumptions": [
                "挡板内表面光滑，但小物块在桌面上滑行，摩擦路程取半圆周长 π(2R)＝2πR（不是位移 4R）",
                "「恰好能到达最高点 D」＝D 点轨道弹力为零，只有重力提供向心力（绳模型，非杆模型）",
                "在 C 点沿切线进入：切线方向与水平方向夹 60°，故水平分速度 v_B＝v_C cos 60°（平抛水平分速不变）",
                "B 点与 A 点同在桌面边缘、B 与 C 之间是平抛；H_BD 的零点取 B 点所在高度",
            ],
        },
        "nums": {"mu": 1.0 / (2.0 * 3.141592653589793)},
        "allowed_symbols": ["m", "g", "mu", "R", "v", "vb", "vc", "v1", "H"],
        "prior": "high",
        "reason": "金标参考解：半圆挡板摩擦滑行＋平抛＋沿切线进圆弧＋最高点临界＋三段动能定理；全符号题 L1 全步 na，L2 逐式手判；15/15 满分",
        "steps": [
            dict(pid="B-17-S01", title="最高点恰好通过⇒弹力为零", kind="judgment", score=1,
                 stmt="D 为圆轨道最高点且「恰好通过」，含义是轨道对小物块的弹力恰为零，只有重力提供向心力 —— "
                      "不是速度为零。",
                 crit=dict(expr="contact_force_at_D", expected=None, comparator="qualitative",
                           text="圆轨道内侧最高点「恰好通过」的临界条件是弹力为零（N＝0），向心力全部由重力提供，"
                                "此时速度取最小值 √(gR)，不为零。把「恰好通过」理解成速度为零，"
                                "或认为 D 点弹力向上，都会把临界速度算错。"),
                 l2="N（弹力判据，量纲为力）",
                 l4="把「恰好通过」理解为速度为零本步 0 分；认为 D 点弹力向上本步 0 分",
                 laws=["L-06"]),
            dict(pid="B-17-S02", title="最高点向心力式求 v_D", kind="equation", score=2,
                 stmt="在 D 点由重力提供向心力：mg＝mv_D²/R，解得 v_D＝√(gR)。",
                 latex=r"m g = \frac{m v_{D}^{2}}{R}",
                 sympy="m*g - m*v**2/R",
                 l2="N：右侧 mv²/R 亦为 N",
                 l4="写成 mg＝mv²/(2R) 本步 0 分；漏 m 本步 0 分",
                 laws=["L-06"]),
            dict(pid="B-17-S03", title="v_D 只用 g、R 表示", kind="discussion", score=1,
                 stmt="第 (1) 问结果写成 v_D＝√(gR)：式中不含 m，也不含未消去的中间量。",
                 latex=r"v_{D} = \sqrt{g R}",
                 sympy="v**2 - g*R",
                 l2="m/s",
                 l4="写成 v_D＝√(2gR)（按绳模型最高点）本步 0 分；结果含未消去的量本步 0 分",
                 val={"symbol": "v", "number": None, "exact": "sqrt(g*R)",
                      "unit": "m/s", "direction": None, "sig_figs": None},
                 laws=["L-06"]),
            dict(pid="B-17-S04", title="沿切线进入⇒水平分速度不变", kind="equation", score=1,
                 stmt="C 点沿切线进入：切线方向与水平夹 60°，而平抛的水平分速度始终为 v_B，"
                      "故 v_B＝v_C cos 60°。",
                 latex=r"v_{B} = v_{C} \cos 60°",
                 sympy="vb - vc*Rational(1,2)",
                 l2="m/s",
                 l4="把 60° 当作速度与竖直方向的夹角（用 sin60°）本步 0 分；漏「沿切线」判断本步 0 分",
                 laws=["L-01"]),
            dict(pid="B-17-S05", title="C→D 动能定理求 v_C", kind="equation", score=2,
                 stmt="C→D 上升的高度为 R＋R cos 60°，由动能定理得 v_C＝2√(gR)。",
                 latex=r"-m g (R + R \cos 60°) = \frac{1}{2} m v_{D}^{2} - \frac{1}{2} m v_{C}^{2}",
                 sympy="-m*g*(R + R*Rational(1,2)) - (Rational(1,2)*m*v**2 - Rational(1,2)*m*vc**2)",
                 l2="J",
                 l4="高度差只取 R（漏 R cos 60°）本步 0 分；把 v_D 当作零本步 0 分",
                 val={"symbol": "vc", "number": None, "exact": "2*sqrt(g*R)",
                      "unit": "m/s", "direction": None, "sig_figs": None},
                 laws=["L-08"]),
            dict(pid="B-17-S06", title="B→D 动能定理含 H_BD", kind="equation", score=2,
                 stmt="从 B 到 D 全程用动能定理（平抛段无机械能损失），重力做功 mgH_BD："
                      "mgH_BD＝½mv_D²−½mv_B²。",
                 latex=r"m g H_{BD} = \frac{1}{2} m v_{D}^{2} - \frac{1}{2} m v_{B}^{2}",
                 sympy="m*g*H - (Rational(1,2)*m*v**2 - Rational(1,2)*m*vb**2)",
                 l2="J",
                 l4="把 H_BD 直接当作 R 或 1.5R 本步 0 分；漏写该式仅给结论本步 0 分",
                 laws=["L-08"]),
            dict(pid="B-17-S07", title="H_BD = 0：B 与 D 等高", kind="discussion", score=1,
                 stmt="代入 v_C＝2√(gR)、v_B＝v_C/2＝√(gR)、v_D＝√(gR)，得 H_BD＝0，即 B 点与 D 点等高。",
                 latex=r"H_{BD} = 0",
                 sympy="H - 0",
                 l2="m",
                 l4="答 R、1.5R 或 2R 本步 0 分；只写 0 未说明「等高」本步给分",
                 val={"symbol": "H", "number": 0.0, "exact": "0",
                      "unit": "m", "direction": None, "sig_figs": 1},
                 laws=["L-08"]),
            dict(pid="B-17-S08", title="摩擦路程取半圆周长 2πR", kind="judgment", score=2,
                 stmt="小物块沿半圆挡板内侧滑行一整段弧，摩擦力的作用路程是半圆周长 π(2R)＝2πR，"
                      "不是 A、B 之间的直线距离 4R。",
                 crit=dict(expr="friction_path", expected=None, comparator="qualitative",
                           text="摩擦力沿运动方向逐点作用，做功按路程累积：物块贴着半径 2R 的半圆内侧走完半圈，"
                                "路程为半圆周长 π·2R＝2πR。用位移 4R（A、B 的直线距离）或 2R 计摩擦功都会低估损耗，"
                                "且只有取 2πR 时 μ＝1/(2π) 才能把摩擦功化成 −mgR。"),
                 l2="m（路程，量纲同长度）",
                 l4="用位移 4R 或 2R 计算摩擦功本步 0 分；漏「沿内侧滑行一整圈」本步 0 分",
                 laws=["L-05", "L-08"]),
            dict(pid="B-17-S09", title="A→B 动能定理，μ 代入 1/(2π)", kind="equation", score=2,
                 stmt="A→B 用动能定理：−μmg·2πR＝½mv_B²−½mv_A²；代入 μ＝1/(2π) 后摩擦功化为 −mgR。",
                 latex=r"-\mu m g \cdot 2\pi R = \frac{1}{2} m v_{B}^{2} - \frac{1}{2} m v_{A}^{2}",
                 sympy="-mu*m*g*2*pi*R - (Rational(1,2)*m*vb**2 - Rational(1,2)*m*v1**2)",
                 l2="J",
                 l4="μ 未代入 1/(2π) 本步 0 分；把 v_B 取成 v_C 本步 0 分",
                 laws=["L-08", "L-05"]),
            dict(pid="B-17-S10", title="v_A = √(3gR)", kind="discussion", score=1,
                 stmt="把摩擦功 −mgR 与 v_B²＝gR 代入，得 ½mv_A²＝½mgR＋mgR＝(3/2)mgR，故 v_A＝√(3gR)。",
                 latex=r"v_{A} = \sqrt{3 g R}",
                 sympy="v1**2 - 3*g*R",
                 l2="m/s",
                 l4="写成 √(2gR) 或 √(5gR) 本步 0 分；结果含未消去的量本步 0 分",
                 val={"symbol": "v1", "number": None, "exact": "sqrt(3*g*R)",
                      "unit": "m/s", "direction": None, "sig_figs": None},
                 laws=["L-08"]),
        ],
    }
    build(cfg)


def b18():
    """2025 浙江 1 月 16：下滑＋完全非弹性碰撞＋竖直圆轨道临界＋EF 段摩擦＋斜抛（含反弹一次）。

    数值题，但**同一个量在不同小问取不同值**，nums 只能各留一个数：
      · v_C′：第 (2) 问 h＝2 m → v_C′²＝10（sympy 记 v1）；第 (3) 问 h＝2.5 m → 12.5（记 v1p）
      · h：第 (1) 问给定 0.8 m（进 nums），第 (2)(3) 问是待求的 2 m / 2.5 m（只进 value）
    因此 S04/S08 的方程改用 v_C′ 表达、不含 h，否则同一枚 h 会在两步里要求两个不同的数而互相打架。
    符号迁移：L_FG→s1、L_GH→s2、L_HI→d（三段间距相加即总射程，不另立 d0）；
    v_D→v、v_C′(第2问)→v1、v_C′(第3问)→v1p、v_F→v2、v_F′→v2p。
    sin37°＝0.6、cos37°＝0.8 按题给取定值写 Rational(3,5)/Rational(4,5)：
    若写成 sin(theta) 并把 theta 填 37° 的弧度值，残差约 9e-4，会把正确式子判成 E-12。
    """
    stem = ("一游戏装置的竖直截面如图所示。倾斜直轨道 AB、半径为 R 的竖直螺旋轨道、水平轨道 BC 和 C′E、"
            "倾角为 37° 的倾斜直轨道 EF 平滑连接成一个抛体装置。该装置除 EF 段轨道粗糙外，其余各段均光滑，"
            "F 点与水平高台 GHI 等高。游戏开始，一质量为 m 的滑块 1 从轨道 AB 上的高度 h 处静止滑下，"
            "与静止在 C 点、质量也为 m 的滑块 2 发生完全非弹性碰撞后组合成滑块 3，滑上滑轨。"
            "若滑块 3 落在 GH 段，反弹后水平分速度保持不变，竖直分速度减半；若滑块落在 H 点右侧，立即停止运动。"
            "已知 R＝0.2 m，m＝0.1 kg，EF 段长度 L＝5/16 m，FG 间距 L_FG＝0.4 m，GH 间距 L_GH＝0.22 m，"
            "HI 间距 L_HI＝0.1 m，EF 段 μ＝0.25。滑块 1、2、3 均可视为质点，不计空气阻力，"
            "sin 37°＝0.6，cos 37°＝0.8，g 取 10 m/s²。求：")
    cfg = {
        "meta": {"answer_id": "B-18", "question_id": "B-18", "group": "B",
                 "source": "2025 浙江 1 月卷", "question_no": 16, "full_score": 11,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T21:50:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [{"fig_no": 1,
                         "caption": "倾斜直轨道 AB、半径 R 的竖直螺旋轨道（C、C′ 在同一水平线上、D 为最高点）、水平轨道 BC 与 C′E、倾角 37° 的粗糙 EF 段、与 F 等高的水平高台 GHI；原文无图题",
                         "caption_source": "none", "is_required": True}],
            "subquestions": [
                {"no": "(1)", "text": "若 h＝0.8 m，碰撞后瞬间滑块 3 的速度大小 v_C。", "score": 3},
                {"no": "(2)", "text": "若滑块 3 恰好能通过圆轨道 CDC′，高度 h。", "score": 3},
                {"no": "(3)", "text": "若滑块 3 最终落入 I 点的洞中（游戏成功），讨论游戏成功的高度 h。", "score": 5},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "滑块 1", "mass_symbol": "m", "note": "从 AB 上高度 h 处静止下滑，与滑块 2 碰前速度 v₀"},
                {"id": "obj2", "name": "滑块 2", "mass_symbol": "m", "note": "静止在 C 点，与滑块 1 完全非弹性碰撞"},
                {"id": "obj3", "name": "滑块 3（组合体）", "mass_symbol": "m", "note": "质量 2m，碰后速度 v_C，沿光滑轨道滑行后经粗糙 EF 段抛出"},
            ],
            "given": [
                {"symbol": "R", "value": 0.2, "unit": "m", "text": "竖直螺旋轨道半径 R＝0.2 m"},
                {"symbol": "m", "value": 0.1, "unit": "kg", "text": "滑块 1、2 质量均为 m＝0.1 kg（碰后组合体 2m）"},
                {"symbol": "L", "value": 0.3125, "unit": "m", "text": "EF 段长度 L＝5/16 m"},
                {"symbol": "s1", "value": 0.4, "unit": "m", "text": "FG 间距 L_FG＝0.4 m —— 记作 s1"},
                {"symbol": "s2", "value": 0.22, "unit": "m", "text": "GH 间距 L_GH＝0.22 m —— 记作 s2"},
                {"symbol": "d", "value": 0.1, "unit": "m", "text": "HI 间距 L_HI＝0.1 m —— 记作 d"},
                {"symbol": "mu", "value": 0.25, "unit": "1", "text": "EF 段动摩擦因数 μ＝0.25（其余各段光滑）"},
                {"symbol": "h", "value": 0.8, "unit": "m",
                 "text": "第 (1) 问给定的下滑高度 h＝0.8 m；第 (2)(3) 问的 h 是待求量（2 m、2.5 m 或 2 m）"},
                {"symbol": "theta", "value": 37, "unit": "deg",
                 "text": "EF 倾角 37°，题给 sin37°＝0.6、cos37°＝0.8；方程里直接写 3/5 与 4/5"},
                {"symbol": "g", "value": 10, "unit": "m/s^2", "text": "重力加速度 g 取 10 m/s²"},
            ],
            "process_segments": [
                {"no": 1, "name": "滑块 1 沿 AB 下滑至 C 点并碰撞",
                 "start": "高度 h 处静止释放", "end": "与滑块 2 合成滑块 3，碰后瞬间速度 v_C"},
                {"no": 2, "name": "滑块 3 沿光滑轨道经圆轨道到 C′",
                 "start": "C 点（速度 v_C）", "end": "C′ 点（速度 v_C′），D 为圆轨道最高点"},
                {"no": 3, "name": "C′→E→F 经粗糙段后斜抛落地",
                 "start": "C′ 点", "end": "F 点以 v_F 斜抛；落在 GH 段会反弹一次（竖直分速度减半）"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "vc", "text": "碰撞后瞬间滑块 3 的速度"},
                {"no": "(2)", "quantity": "h", "text": "恰好通过圆轨道 CDC′ 时的高度"},
                {"no": "(3)", "quantity": "h", "text": "落入 I 点洞中（游戏成功）时的高度"},
            ],
            "assumptions": [
                "碰撞时间极短、完全非弹性：mv₀＝2mv_C，碰后速度只有碰前的一半",
                "C 到 C′ 各段光滑、C 与 C′ 等高（同一水平轨道分居圆轨道两侧），故 v_C′＝v_C",
                "竖直圆轨道最高点 D 的临界用 2mg＝2mv_D²/R（质量是碰后的 2m），C′→D 用机械能守恒",
                "C′→F 只有 EF 段有摩擦，摩擦力 μ(2m)g cos37°，路程为 EF 段长 L；F 点与高台 GHI 等高",
                "斜抛落点水平射程由三段间距之和给出：L_FG＋L_GH＋L_HI＝0.4＋0.22＋0.1＝0.72 m",
                "反弹后水平分速度不变、竖直分速度减半，故飞行时间由 2v_y/g 变为 3v_y/g（＝1.5 倍）",
            ],
        },
        "nums": {"m": 0.1, "R": 0.2, "L": 0.3125, "s1": 0.4, "s2": 0.22, "d": 0.1, "mu": 0.25,
                 "g": 10.0, "h": 0.8, "v0": 4.0, "vc": 2.0,
                 "v": 1.4142135623730951, "v1": 3.1622776601683795,
                 "v1p": 3.5355339059327378, "v2": 2.7386127875258306,
                 "v2p": 2.23606797749979},
        "allowed_symbols": ["m", "R", "L", "s1", "s2", "d", "mu", "g", "h",
                            "v0", "vc", "v", "v1", "v1p", "v2", "v2p"],
        "prior": "high",
        "reason": "金标参考解：下滑＋完全非弹性碰撞＋竖直圆轨道最高点临界＋EF 段摩擦＋双分支斜抛（含反弹竖直分速度减半）；L1 逐式数值回代；11/11 满分",
        "steps": [
            dict(pid="B-18-S01", title="滑块 1 由 h 处下滑求 v0", kind="equation", score=2,
                 stmt="滑块 1 沿光滑轨道 AB 下滑，机械能守恒：mgh＝½mv₀²；取 h＝0.8 m 得 v₀＝4 m/s。",
                 latex=r"m g h = \frac{1}{2} m v_{0}^{2}",
                 sympy="m*g*h - Rational(1,2)*m*v0**2",
                 l2="J",
                 l4="漏 ½ 本步 0 分；h 取 0.8 m 之外的轨道高度本步 0 分",
                 val={"symbol": "v0", "number": 4.0, "exact": "4",
                      "unit": "m/s", "direction": None, "sig_figs": 1},
                 laws=["L-09"]),
            dict(pid="B-18-S02", title="完全非弹性碰撞求 v_C", kind="equation", score=1,
                 stmt="滑块 1 与静止的滑块 2 完全非弹性碰撞，动量守恒：mv₀＝2mv_C，得 v_C＝2 m/s。",
                 latex=r"m v_{0} = 2 m v_{C}",
                 sympy="m*v0 - 2*m*vc",
                 l2="kg·m/s",
                 l4="把碰后速度写成 v₀ 本步 0 分；质量比取反本步 0 分",
                 val={"symbol": "vc", "number": 2.0, "exact": "2",
                      "unit": "m/s", "direction": None, "sig_figs": 1},
                 laws=["L-12"]),
            dict(pid="B-18-S03", title="恰好通过圆轨道最高点 D", kind="judgment", score=1,
                 stmt="「恰好通过圆轨道 CDC′」的临界点在最高点 D，且此时做圆周运动的是碰后质量 2m 的滑块 3："
                      "2mg＝2m·v_D²/R。",
                 crit=dict(expr="2*m*g - 2*m*v**2/R", expected=0, comparator="eq",
                           text="圆轨道内侧最高点恰好通过的临界条件是弹力为零、只有重力提供向心力；"
                                "此时在轨道上运动的是碰后质量 2m 的滑块 3，故写 2mg＝2m v_D²/R（质量的 2 倍两侧都要带），"
                                "临界点判在最高点 D 而不是 C 或 C′。"),
                 l2="N（两侧同为力）",
                 l4="临界用 mg＝mv²/R 且未说明 2m 已约去（即漏碰后质量 2m）本步 0 分；把临界点判在 C 或 C′ 本步 0 分",
                 laws=["L-06"]),
            dict(pid="B-18-S04", title="C′→D 机械能守恒逆推 h", kind="equation", score=2,
                 stmt="C′→D 机械能守恒（光滑），高度差为 2R：½(2m)v_C′²＝½(2m)v_D²＋(2m)g·2R，"
                      "得 v_C′＝√10 m/s；再由 v_C′＝v₀′/2、mgh＝½mv₀′² 逆推得 h＝2 m。",
                 latex=r"m v_{C'}^{2} = m v_{D}^{2} + 4 m g R",
                 sympy="m*v1**2 - m*v**2 - 4*m*g*R",
                 l2="J",
                 l4="漏「碰后质量加倍」本步 0 分；高度差取 R（应为 2R）本步 0 分；"
                    "本步的 h 是第 (2) 问的高度＝2 m，与第 (1) 问给定的 h＝0.8 m 不是同一个值",
                 val={"symbol": "h", "number": 2.0, "exact": "2",
                      "unit": "m", "direction": None, "sig_figs": 1},
                 laws=["L-09", "L-12"]),
            dict(pid="B-18-S05", title="分直落与反弹两种情形", kind="judgment", score=1,
                 stmt="落入 I 洞有两条路径：由 F 点直接落入（射程恰为 0.72 m）；或先落在 GH 段、反弹一次后再落入 I。"
                      "两情形都要列，只讨论一种会漏解。",
                 crit=dict(expr="branch_enumeration", expected=None, comparator="qualitative",
                           text="滑块 3 从 F 点斜抛后可能一次落地就进洞，也可能先落在 GH 段（反弹后水平分速度不变、"
                                "竖直分速度减半）再落进 I；题给「落在 GH 段才反弹」是分情形的前提，"
                                "因此必须按「直接落入」与「反弹一次后落入」两条分支分别列射程条件——只写一种情形即漏解。"),
                 l2="m（两种情形的射程都按长度计）",
                 l4="只讨论一种情形本步 0 分；把反弹后竖直分速度也当作不变本步 0 分",
                 laws=["L-01", "L-02"]),
            dict(pid="B-18-S06", title="直接落入 I 洞的射程条件", kind="equation", score=1,
                 stmt="直接落入：水平射程等于 FG＋GH＋HI＝0.4＋0.22＋0.1＝0.72 m，"
                      "飞行时间 2v_F sin37°/g，故 0.72＝v_F cos37°·(2v_F sin37°/g)，得 v_F²＝7.5。",
                 latex=r"s_{1} + s_{2} + d = v_{F} \cos 37° \cdot \frac{2 v_{F} \sin 37°}{g}",
                 sympy="s1 + s2 + d - v2*Rational(4,5)*2*v2*Rational(3,5)/g",
                 l2="m：(m/s)·(m/s)/(m/s²)＝m",
                 l4="射程漏 L_FG 或 L_HI 本步 0 分；飞行时间漏 2 倍本步 0 分",
                 val={"symbol": "v2", "number": 2.7386127875258306, "exact": "sqrt(15/2)",
                      "unit": "m/s", "direction": None, "sig_figs": 2},
                 laws=["L-01"]),
            dict(pid="B-18-S07", title="反弹一次后的射程条件", kind="equation", score=1,
                 stmt="反弹一次：竖直分速度减半后仍占半程，总飞行时间由 2v_F′sin37°/g 变为 3v_F′sin37°/g（1.5 倍），"
                      "射程仍为 0.72 m，得 v_F′²＝5。",
                 latex=r"s_{1} + s_{2} + d = v_{F'} \cos 37° \cdot \frac{3 v_{F'} \sin 37°}{g}",
                 sympy="s1 + s2 + d - v2p*Rational(4,5)*3*v2p*Rational(3,5)/g",
                 l2="m",
                 l4="时间仍用 2 倍（未含反弹增加的半程）本步 0 分；反弹后水平分速度也减半本步 0 分",
                 val={"symbol": "v2p", "number": 2.23606797749979, "exact": "sqrt(5)",
                      "unit": "m/s", "direction": None, "sig_figs": 2},
                 laws=["L-01"]),
            dict(pid="B-18-S08", title="C′→F 动能定理反推 h", kind="discussion", score=2,
                 stmt="由 C′→F 的动能定理（EF 段摩擦 μ(2m)g cos37°·L）把 v_F 反推成 v_C′，再由 v_C′＝v₀/2、"
                      "mgh＝½mv₀² 得 h：直接落入分支 v_F²＝7.5 → v_C″²＝12.5 → h＝2.5 m；"
                      "反弹分支 v_F′²＝5 → v_C″²＝10 → h＝2 m。答案 h＝2.5 m 或 2 m。",
                 latex=r"\frac{1}{2}(2 m) v_{F}^{2} = \frac{1}{2}(2 m) v_{C'}^{2} - (2 m g \sin 37° + \mu \cdot 2 m g \cos 37°) L",
                 sympy="Rational(1,2)*2*m*v2**2 - Rational(1,2)*2*m*v1p**2 + (2*m*g*Rational(3,5) + mu*2*m*g*Rational(4,5))*L",
                 l2="J",
                 l4="漏 EF 段摩擦项本步 0 分；只给一个 h 值本步 0 分",
                 val={"symbol": "h", "number": 2.5, "exact": "5/2",
                      "unit": "m", "direction": None, "sig_figs": 2},
                 laws=["L-08"]),
        ],
    }
    build(cfg)


def b19():
    """2021 全国乙 24：碰撞前后动能比不变 → 落回同高度的落地动能 → 恒力拍球的功与力。

    全数值题，L1 可逐步回代（8 步里 6 步 pass、2 步定性判据 na）。
    符号迁移：h₁（自由落下高度）→ h0、h₂（反弹高度）→ h、h₃（拍球下落高度）→ H。
    白名单只有 h/h0/H 三枚高度位，按「第 1 次／第 2 次／拍球」的顺序固定映射，见各步 statement。
    """
    stem = ("一篮球质量为 m＝0.60 kg，一运动员使其从距地面高度为 h₁＝1.8 m 处由静止自由落下，反弹高度为 h₂＝1.2 m。"
            "若使篮球从距地面 h₃＝1.5 m 的高度由静止下落，并在开始下落的同时向下拍球，球落地后反弹的高度也为 1.5 m。"
            "假设运动员拍球时对球的作用力为恒力，作用时间为 t＝0.20 s；该篮球每次与地面碰撞前后的动能的比值不变。"
            "重力加速度大小取 g＝10 m/s²，不计空气阻力。求：")
    cfg = {
        "meta": {"answer_id": "B-19", "question_id": "B-19", "group": "B",
                 "source": "2021 全国乙卷", "question_no": 24, "full_score": 12,
                 "mode": "gold", "model": "human-gold", "prompt_version": "p1",
                 "temperature": 0, "generated_at": "2026-11-25T22:00:00+08:00",
                 "latency_ms": 0, "tokens": {"in": 0, "out": 0}, "stem_source": "original"},
        "question": {
            "stem_text": stem,
            "figures": [],
            "subquestions": [
                {"no": "(1)", "text": "运动员拍球过程中对篮球所做的功。", "score": 6},
                {"no": "(2)", "text": "运动员拍球时对篮球的作用力的大小。", "score": 6},
            ],
        },
        "situation": {
            "objects": [
                {"id": "obj1", "name": "篮球", "mass_symbol": "m",
                 "note": "质量 0.60 kg；每次与地面碰撞前后的动能比值不变"},
                {"id": "obj2", "name": "运动员的手", "mass_symbol": "m",
                 "note": "拍球时对球施加竖直向下的恒力 F，作用时间 t＝0.20 s"},
            ],
            "given": [
                {"symbol": "m", "value": 0.6, "unit": "kg", "text": "篮球质量 m＝0.60 kg"},
                {"symbol": "h0", "value": 1.8, "unit": "m", "text": "第一次自由落下的高度 h₁＝1.8 m —— 记作 h0"},
                {"symbol": "h", "value": 1.2, "unit": "m", "text": "第一次的反弹高度 h₂＝1.2 m —— 记作 h"},
                {"symbol": "H", "value": 1.5, "unit": "m", "text": "拍球的下落高度与反弹高度 h₃＝1.5 m —— 记作 H"},
                {"symbol": "t", "value": 0.2, "unit": "s", "text": "拍球作用时间 t＝0.20 s"},
                {"symbol": "g", "value": 10, "unit": "m/s^2", "text": "重力加速度 g＝10 m/s²"},
            ],
            "process_segments": [
                {"no": 1, "name": "第一次自由下落与反弹（定动能比）",
                 "start": "从 h₁＝1.8 m 由静止下落", "end": "反弹到 h₂＝1.2 m 的最高点（速度为零）"},
                {"no": 2, "name": "拍球下落段（恒力 F 与重力共同作用）",
                 "start": "从 h₃＝1.5 m 由静止下落，同时开始拍球", "end": "拍球结束（作用 t＝0.20 s），此后只受重力"},
                {"no": 3, "name": "落地与反弹回 1.5 m",
                 "start": "落地瞬间（动能 E_k3）", "end": "反弹回到 h₃＝1.5 m 的最高点（速度为零）"},
            ],
            "targets": [
                {"no": "(1)", "quantity": "W", "text": "拍球过程中运动员对篮球做的功"},
                {"no": "(2)", "quantity": "F", "text": "拍球时运动员对篮球的作用力"},
            ],
            "assumptions": [
                "「每次与地面碰撞前后的动能比值不变」按同一篮球、同一地面的固有性质处理，比值 k 由第一次的 h₁、h₂ 定出",
                "自由下落与反弹阶段只受重力：落地动能＝mgh_落，反弹初动能＝mgh_反弹，故 k＝E_碰前/E_碰后＝h₁/h₂",
                "拍球段球受恒力 F（向下）与重力 mg（向下），做匀加速直线运动，位移 s＝½at²",
                "拍球结束时球已下降 s，此后到落地只受重力；全过程对球用功能关系 W＋mgh₃＝E_k3",
                "反弹回 1.5 m 说明落地动能等于 1.5mgh₃；与第一次比较即 E_k3＝k·mgh₃",
            ],
        },
        "nums": {"m": 0.6, "h0": 1.8, "h": 1.2, "H": 1.5, "t": 0.2, "g": 10.0,
                 "k": 1.5, "Ek": 13.5, "W": 4.5, "a": 25.0, "F": 9.0},
        "allowed_symbols": ["m", "g", "t", "h0", "h", "H", "k", "Ek", "W", "F", "a"],
        "prior": "high",
        "reason": "金标参考解：动能比不变＋功能关系求功＋恒力拍球的牛顿第二定律与运动学联立；L1 六步数值回代、两步定性判据；12/12 满分",
        "steps": [
            dict(pid="B-19-S01", title="每次碰地前后动能比值不变", kind="judgment", score=1,
                 stmt="题设「该篮球每次与地面碰撞前后的动能的比值不变」是一条对同一篮球成立的固有性质："
                      "可用第一次的 h₁、h₂ 把该比值定出来，再用于拍球那一次。",
                 crit=dict(expr="ratio_invariance", expected=None, comparator="qualitative",
                           text="「每次碰撞前后动能比值不变」是同一篮球对同一地面的固有性质，与下落高度无关："
                                "第一次的 h₁＝1.8 m、h₂＝1.2 m 只用来**标定**这个比值，"
                                "拍球那一次的落地动能再由同一个比值算出 —— 不能把每次的比值各定一个，"
                                "也不能把它当成速度之比。"),
                 l2="无量纲（动能之比）",
                 l4="把比值当作速度比本步 0 分；未说明「同一篮球每次比值不变」本步 0 分",
                 laws=["L-08"]),
            dict(pid="B-19-S02", title="由两次高度求动能比 k", kind="equation", score=2,
                 stmt="落地动能 mgh₁、反弹初动能 mgh₂，故 k＝E_碰前/E_碰后＝mgh₁/(mgh₂)＝h₁/h₂＝1.8/1.2＝1.5。",
                 latex=r"k = \frac{h_{1}}{h_{2}}",
                 sympy="k - h0/h",
                 l2="无量纲：J/J",
                 l4="取成 h₂/h₁＝2/3（比值颠倒）本步 0 分；用速度比 √1.5 本步 0 分",
                 val={"symbol": "k", "number": 1.5, "exact": "3/2",
                      "unit": "1", "direction": None, "sig_figs": 2},
                 laws=["L-08"]),
            dict(pid="B-19-S03", title="落地瞬间动能＝k·mgh₃", kind="equation", score=2,
                 stmt="拍球那次落地动能由同一比值给出：E_k3＝k·mgh₃＝1.5×0.60×10×1.5＝13.5 J。",
                 latex=r"E_{k3} = k m g h_{3}",
                 sympy="Ek - k*m*g*H",
                 l2="J",
                 l4="漏 k 本步 0 分；把 E_k3 当作反弹后动能本步 0 分",
                 val={"symbol": "Ek", "number": 13.5, "exact": "27/2",
                      "unit": "J", "direction": None, "sig_figs": 2},
                 laws=["L-08"]),
            dict(pid="B-19-S04", title="功能关系求拍球做功 W", kind="discussion", score=1,
                 stmt="从静止下落到落地：拍球的功 W 与重力功 mgh₃ 之和等于落地动能，"
                      "W＋mgh₃＝E_k3，故 W＝13.5−9.0＝4.5 J。",
                 latex=r"W + m g h_{3} = E_{k3}",
                 sympy="W + m*g*H - Ek",
                 l2="J",
                 l4="漏 mgh₃ 项本步 0 分；只写 4.5 不写单位 J 本步 0 分",
                 val={"symbol": "W", "number": 4.5, "exact": "9/2",
                      "unit": "J", "direction": None, "sig_figs": 2},
                 laws=["L-08"]),
            dict(pid="B-19-S05", title="恒力拍球做匀加速直线运动", kind="judgment", score=1,
                 stmt="拍球过程中球受恒力 F 与重力 mg（同向下），加速度恒定，做初速为零的匀加速直线运动 —— "
                      "不是匀速，也不是只在拍球瞬间获得速度。",
                 crit=dict(expr="motion_type_under_constant_force", expected=None, comparator="qualitative",
                           text="拍球时 F 与 mg 都是恒力且同向下，合力恒定，故球做初速为零的匀加速直线运动，"
                                "位移按 s＝½at² 计、做功按 W＝Fs 计；漏掉重力或把过程当成匀速，"
                                "都会把 F 算成 ma 或 W/(vt) 之类的错式。"),
                 l2="m/s²（加速度恒定）",
                 l4="把拍球当作匀速本步 0 分；漏重力本步 0 分",
                 laws=["L-04"]),
            dict(pid="B-19-S06", title="F + mg = ma", kind="equation", score=2,
                 stmt="取向下为正：F＋mg＝ma（F 与重力同向，都向下）。",
                 latex=r"F + m g = m a",
                 sympy="F + m*g - m*a",
                 l2="N",
                 l4="写成 F−mg＝ma（重力方向反）本步 0 分；漏 mg 本步 0 分",
                 laws=["L-04"]),
            dict(pid="B-19-S07", title="s＝½at² 与 W＝Fs 联立", kind="equation", score=2,
                 stmt="拍球段位移 s＝½at²，做功 W＝Fs，两式消去 s 与 a 得 W＝F·½at²；"
                      "代入 W＝4.5 J、t＝0.20 s 与 F＋mg＝ma 联立即可解 F。",
                 latex=r"W = F \cdot \frac{1}{2} a t^{2}",
                 sympy="W - F*Rational(1,2)*a*t**2",
                 l2="J：N·(m/s²)·s²＝N·m＝J",
                 l4="只列 s 或只列 W 本步给 1 分；把 s 当作 h₃ 本步 0 分",
                 laws=["L-01", "L-08"]),
            dict(pid="B-19-S08", title="F＝9 N，−15 N 舍去", kind="discussion", score=1,
                 stmt="把 F＝m(a−g) 代入 W＝F·½at² 得 0.6a²−6a−225＝0，两根 a＝25 或 a＝−15 m/s²，"
                      "负根不合「向下加速」的物理意义舍去，取 a＝25 m/s²，故 F＝0.6×15＝9 N。",
                 latex=r"F = 9",
                 sympy="F - 9",
                 l2="N",
                 l4="只写 9 不写单位 N 本步 0 分；保留 −15 N 未说明舍去本步 0 分",
                 val={"symbol": "F", "number": 9.0, "exact": "9",
                      "unit": "N", "direction": None, "sig_figs": 1},
                 laws=["L-04", "L-01"]),
        ],
    }
    build(cfg)


if __name__ == "__main__":
    # 27 题全量（T08f 补齐余下 20 题后，默认列表＝全部样例；分批时用 `python schema/_build_examples.py b15` 单题跑）
    ALL = ["a01", "a02", "a03", "a04", "a05", "a06", "a08", "a09", "a10",
           "b01", "b02", "b03", "b04", "b05", "b06", "b07", "b08", "b09", "b10",
           "b12", "b13", "b15", "b16", "b17", "b18", "b19", "b20"]
    only = sys.argv[1:] or ALL
    for name in only:
        globals()[name]()
    print("完成。下一步：python schema/validate_schema.py schema/examples/<题号>.json")
