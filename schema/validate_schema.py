#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_schema.py — 解析 Schema（answer 1.2.1）校验器

用法：
    python schema/validate_schema.py schema/example_A-06.json
    python schema/validate_schema.py <answer.json> --quiet

选项：
    --point-table PATH   采分点总表 xlsx（含 采分点总表 / 选题清单_30题 两张表）
                         默认 原始资料/五卷力学大题_采分点总表_v2.xlsx
    --point-csv-dir DIR  额外并入的样张 csv 目录，默认 采分点/
    --law-table PATH     定律表 csv（默认 知识表/定律适用条件_v1.csv；不存在则用内置 L-01…L-12）
    --symbol-table PATH  符号白名单 csv（默认 知识表/符号白名单_v1.csv；不存在则只查 ASCII 规则）
    --quiet              只打结论行

退出码：0 = 无 E（允许有 W）；1 = 有 E。

实现范围（对应任务卡 §5）：
    1. JSON Schema 校验（draft-07，先 check_schema 自检）
    2. R1 step_id 唯一 + 命名空间不与 point_id 混用
    3. R2 step_no ⊆ outline、严格递增、gold 全覆盖
    4. R3 方程双表示（sympy 形式、符号闭合、latex 受限子集）；equation 为 null 时跳过
    5. R4 degraded 是状态不是判错
    6. R6 引用完整性（point_id / step_id / law_id / symbol_id）
    7. R8 分值闭合
    8. R10 归零点必红
    9. R11 given[source=figure] 必须与 figures[].provides 同符号且数值一致（1.2 缺陷 ①）
   10. R12 input_sha256 重算比对（1.2 缺陷 ①）
   11. R13 整题层 layers 必须等于步级 checks 的反推结果（1.2 缺陷 ②）
   12. R14 steps[].segment_id 不许悬空（1.2 缺陷 ③）
   13. R15 judgment/critical ⇔ equation 为 null 且带 criterion；equation/value ⇔ 反之（1.2 缺陷 ④）
   14. R16 figures[].file 与 file_sha256 必须同时为 null 或同时非 null（1.2.1 缺陷 ①）
   15. R17 file 非 null 时文件必须存在（按工作区根解析）且 sha256 逐字相等（1.2.1 缺陷 ①）
   16. R18 discussion 步 criterion 与 equation 至少一个非 null（1.2.1 缺陷 ②）
   17. W-fig is_required=true 但 file=null → WARN（不是错：确实没有图）
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import os
import re
import sys

try:
    import jsonschema
    from jsonschema import Draft7Validator
except ImportError:  # pragma: no cover
    print("[E] 缺依赖：pip install jsonschema")
    sys.exit(1)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 内置定律白名单：与 T10 任务卡 §1 的 law_id 一一对应（表未就绪时的兜底）
BUILTIN_LAWS = {
    "L-01": "匀变速直线运动公式组",
    "L-02": "自由落体与竖直上抛",
    "L-03": "共点力平衡",
    "L-04": "牛顿第二定律",
    "L-05": "滑动摩擦力 f=μN",
    "L-06": "圆周运动与向心力",
    "L-07": "万有引力与天体运动",
    "L-08": "动能定理",
    "L-09": "机械能守恒",
    "L-10": "功能关系与摩擦生热",
    "L-11": "动量定理",
    "L-12": "动量守恒",
}

# T09 R8 的受限 LaTeX 子集（命令白名单）
LATEX_CMDS = {
    "frac", "sqrt", "cdot", "times", "sin", "cos", "tan",
    "le", "ge", "approx", "mu", "theta", "alpha", "omega", "Delta", "pi",
}

# sympy 里的函数/常量名，不算「符号」
SYMPY_FUNCS = {
    "Rational", "S", "sin", "cos", "tan", "sqrt", "pi", "E", "I",
    "Abs", "exp", "log", "Symbol", "Integer", "Float",
}

ZERO_CODES = {"E-01", "E-20"}

# criterion.text 里不许出现的占位词：判据必须能独立读懂（T08d §1 缺陷 ④）
CRITERION_PLACEHOLDERS = ("同上", "见式", "见上式", "如前", "略")


# ---------------------------------------------------------------- 输入指纹（1.2）

def _canon_num(v) -> str:
    """数值规范化：整数与浮点同形，避免 1 与 1.0 算出两个哈希。"""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return "%.17g" % float(v)
    return str(v)


def canonical_provides(question: dict) -> str:
    """figures[].provides 的规范化串。生成器与校验器必须逐字相同。

    排序键 = (fig_no, symbol, value, unit, read_from, text)；每项以竖线相连、行间换行。
    没有 provides 时返回空串 —— 此时 input_sha256 只由 stem_text 决定。
    """
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


def input_payload(question: dict) -> str:
    """input_sha256 的被哈希串：题干 + 固定分隔 + 规范化读数。"""
    return question.get("stem_text", "") + "\n\n#provides\n" + canonical_provides(question)


def input_sha256_of(question: dict) -> str:
    return hashlib.sha256(input_payload(question).encode("utf-8")).hexdigest()


def same_value(a, b) -> bool:
    """provides ↔ given 的数值一致：数值容差 1e-9；字符串精确相等；null 只与 null 相容。"""
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= 1e-9
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    return False



def rel(path: str) -> str:
    """相对路径仅用于显示；跨盘符时退回绝对路径。"""
    try:
        return os.path.relpath(path, ROOT)
    except ValueError:
        return os.path.abspath(path)


class Report:
    """收集 E/W，边跑边打。"""

    def __init__(self, quiet: bool = False):
        self.errors: list[str] = []
        self.warns: list[str] = []
        self.quiet = quiet
        self.oks: list[str] = []

    def ok(self, tag: str, msg: str):
        self.oks.append(f"[OK] {tag} {msg}")
        if not self.quiet:
            print(f"[OK] {tag:<10} {msg}")

    def err(self, tag: str, msg: str):
        self.errors.append(f"[E] {tag} {msg}")
        print(f"[E] {tag:<10} {msg}")

    def warn(self, tag: str, msg: str):
        self.warns.append(f"[W] {tag} {msg}")
        if not self.quiet:
            print(f"[W] {tag:<10} {msg}")


# ---------------------------------------------------------------- 采分点表

def load_points(xlsx_path: str, csv_dir: str, rep: Report) -> dict:
    """返回 {point_id: {"score": float, "from": str}}。

    两个来源：
      a) xlsx 的「采分点总表」——已有 point_id 列（A-01…A-05）
      b) 采分点/样张_*.csv——没有 point_id，按「<编号>-S<步:02d>」生成；
         编号由「选题清单_30题」按 (来源/卷别, 题号) 反查。
    """
    points: dict[str, dict] = {}

    if not os.path.exists(xlsx_path):
        rep.warn("R6", f"采分点总表不存在，point_id 存在性检查跳过：{xlsx_path}")
        return points

    try:
        import openpyxl
    except ImportError:
        rep.warn("R6", "缺 openpyxl，point_id 存在性检查跳过（pip install openpyxl）")
        return points

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)

    ws = wb["采分点总表"]
    header = [str(c).strip() if c is not None else "" for c in next(ws.iter_rows(values_only=True))]
    ip, isc = header.index("point_id"), header.index("分值")
    for row in ws.iter_rows(min_row=2, values_only=True):
        pid = row[ip]
        if not pid:
            continue
        points[str(pid).strip()] = {"score": float(row[isc]), "from": "采分点总表"}

    # (卷别, 题号) -> 编号
    qmap: dict[tuple[str, str], str] = {}
    if "选题清单_30题" in wb.sheetnames:
        ws2 = wb["选题清单_30题"]
        h2 = [str(c).strip() if c is not None else "" for c in next(ws2.iter_rows(values_only=True))]
        ino, isrc, iq = h2.index("编号"), h2.index("来源 / 卷别"), h2.index("题号")
        for row in ws2.iter_rows(min_row=2, values_only=True):
            if not row[ino]:
                continue
            qmap[(str(row[isrc]).strip(), str(row[iq]).strip())] = str(row[ino]).strip()

    for path in sorted(glob.glob(os.path.join(csv_dir, "样张_*.csv"))):
        with open(path, encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                key = (str(row.get("卷别", "")).strip(), str(row.get("题号", "")).strip())
                qid = qmap.get(key)
                if not qid:
                    rep.warn("R6", f"{os.path.basename(path)} 的「{key[0]} {key[1]} 题」在选题清单里查不到编号，该行未并入")
                    continue
                pid = f"{qid}-S{int(row['步']):02d}"
                new = {"score": float(row["分值"]), "from": os.path.basename(path)}
                old = points.get(pid)
                if old:
                    # 同一 point_id 出现两次：不许静默覆盖（T00 卡 C11）
                    if abs(old["score"] - new["score"]) > 1e-9:
                        rep.err("R6-dup", f"{pid} 双源分值冲突："
                                f"{old['from']}={old['score']:g} vs {new['from']}={new['score']:g}")
                    else:
                        rep.warn("R6-dup", f"{pid} 同 id 双源（{old['from']} 与 {new['from']}，"
                                 f"分值一致），入册后应把样张 CSV 移入 采分点/归档/")
                    continue
                points[pid] = new

    return points


def load_laws(path: str, rep: Report) -> dict:
    if path and os.path.exists(path):
        laws = {}
        with open(path, encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                lid = (row.get("law_id") or "").strip()
                if lid:
                    laws[lid] = (row.get("名称") or "").strip()
        if laws:
            rep.ok("R6-law", f"定律表：{len(laws)} 条（{rel(path)}）")
            return laws
    rep.warn("R6-law", f"定律表未就绪，改用内置 12 条（{rel(path) if path else '未指定'}）")
    return dict(BUILTIN_LAWS)


def load_symbols(path: str, rep: Report) -> set | None:
    if path and os.path.exists(path):
        with open(path, encoding="utf-8-sig") as fh:
            ids = {(row.get("symbol_id") or "").strip() for row in csv.DictReader(fh)}
        ids.discard("")
        if ids:
            rep.ok("R6-sym", f"符号白名单：{len(ids)} 个（{rel(path)}）")
            return ids
    rep.warn("R6-sym", "符号白名单未就绪（T09），本次只查 ASCII 与「符号-表达式」一致性")
    return None


# ---------------------------------------------------------------- 业务规则

def sympy_symbols(expr: str) -> set:
    names = set(re.findall(r"[A-Za-z][A-Za-z0-9]*", expr))
    return {n for n in names if n not in SYMPY_FUNCS}


def check_schema(doc: dict, schema: dict, rep: Report):
    try:
        Draft7Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        rep.err("S0", f"Schema 自身不合法：{exc.message}")
        return

    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    if not errors:
        rep.ok("S0", f"JSON Schema 通过（draft-07，{len(errors)} 处违规）")
        return
    for err in errors:
        path = "/".join(str(p) for p in err.absolute_path) or "(root)"
        rep.err("S0", f"{path}: {err.message}")
    print(f"     共 {len(errors)} 处 Schema 违规，业务规则不再执行（先修结构）")
    raise SystemExit(finish(rep))


def check_steps(doc: dict, points: dict, laws: dict, symbols: set | None, rep: Report,
                symbol_strict: bool = False):
    steps = doc["steps"]
    outline = doc["outline"]
    mode = doc["meta"]["mode"]
    o_nos = [o["step_no"] for o in outline]
    s_nos = [s["step_no"] for s in steps]

    # ---- R1 step_id 唯一 + 命名空间
    ids = [s["step_id"] for s in steps]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        rep.err("R1", f"step_id 重复：{sorted(dup)}")
    else:
        rep.ok("R1", f"step_id 唯一：{len(ids)} 个")

    if mode == "free":
        collided = [s["step_id"] for s in steps if s["point_id"] and s["step_id"] == s["point_id"]]
        if collided:
            rep.err("R1", f"free 模式下 step_id 与 point_id 同形，S5 对齐无从判断：{collided[:3]}")
        else:
            rep.ok("R1-ns", "free 模式：step_id 与 point_id 已分区")
    else:
        rep.ok("R1-ns", f"{mode} 模式：step_id 可与 point_id 同值（1:1 对齐）")

    # ---- R2 大纲对齐
    if o_nos != list(range(1, len(o_nos) + 1)):
        rep.err("R2", f"outline 的 step_no 必须从 1 连续：{o_nos}")
    if mode != "rewrite" and s_nos != list(range(1, len(s_nos) + 1)):
        rep.err("R2", f"{mode} 模式的 step_no 必须从 1 连续（部分完成时为 1..k）：{s_nos}")
    if s_nos != sorted(set(s_nos)):
        rep.err("R2", f"step_no 未严格递增：{s_nos}")
    not_in_outline = [n for n in s_nos if n not in o_nos]
    if not_in_outline:
        rep.err("R2", f"步骤号不在大纲里：{not_in_outline}")
    if len(s_nos) != len(set(s_nos)):
        rep.err("R2", "同一 step_no 出现多次")

    expanded = [o["step_no"] for o in outline if o.get("expanded")]
    missing_step = [n for n in expanded if n not in s_nos]
    if missing_step:
        rep.err("R2", f"outline 标 expanded=true 但没有对应步骤：{missing_step}")
    stale = [o["step_no"] for o in outline if not o.get("expanded") and o["step_no"] in s_nos]
    if stale:
        rep.err("R2", f"有步骤但 outline.expanded=false：{stale}")

    if mode == "gold" and set(s_nos) != set(o_nos):
        rep.err("R2", f"gold 模式必须覆盖全部大纲：有步骤 {s_nos}，大纲 {o_nos}")
    if len(steps) < len(outline):
        rep.warn("R2", f"部分完成：大纲 {len(outline)} 步，已展开 {len(steps)} 步 —— 不得进入 S5 采分点对齐")
    if not (not_in_outline or missing_step or stale or dup):
        rep.ok("R2", f"步骤-大纲对齐：{len(steps)}/{len(outline)}")

    # ---- 引用完整性 R6
    for s in steps:
        sid = s["step_id"]
        pid = s["point_id"]
        if mode == "gold" and not pid:
            rep.err("R6", f"{sid} 在 gold 模式下 point_id 必填")
        if pid and points and pid not in points:
            rep.err("R6", f"{sid} 的 point_id「{pid}」不在采分点表")
        for lid in s["law_ids"]:
            if lid not in laws:
                rep.err("R6", f"{sid} 的 law_id「{lid}」不在 12 条定律表")
        if s["kind"] in ("equation", "critical") and not s["law_ids"] and mode not in ("free", "zero"):
            # 2026-11-25 T20 裁定（C 案）：law_ids 属「拆解规范」不属「模型作答」。
            # free ＝ 模型自由作答、尚未与采分点/定律对齐，此时空 law_ids 不是缺陷。
            # zero ＝ 题库外新题（2026-11-26 T40），定律表只覆盖 20 题，同样不强制。
            # gold/rewrite 仍强制 —— 那两类的产物必须已完成拆解。
            rep.err("R6", f"{sid} 是 {s['kind']} 步，law_ids 不得为空")
        if s["status"] == "checked" and not s["checks"]:
            rep.err("R6", f"{sid} 标 checked 但 checks 为空")
        if s["confidence"] > 5 or s["confidence"] < 1:
            rep.err("R6", f"{sid} confidence 越界")
        eq = s.get("equation")
        if eq is not None:
            if mes := re.findall(r"[^\x00-\x7f]", "".join(eq["symbols"])):
                rep.err("R6", f"{sid} 符号不是 ASCII：{mes}")
            if symbols:
                bad = [x for x in eq["symbols"] if x not in symbols]
                if bad:
                    msg = f"{sid} 用了白名单外的符号 {bad}（需 T09 登记后归一化）"
                    if symbol_strict:
                        rep.err("R6-sym", msg)
                    else:
                        rep.warn("R6-sym", msg)

    hit_pids = [h["point_id"] for h in doc["grading"]["point_hits"]]
    if len(hit_pids) != len(set(hit_pids)):
        rep.err("R6", f"point_hits 里 point_id 重复：{hit_pids}")
    for h in doc["grading"]["point_hits"]:
        if h["step_id"] not in ids:
            rep.err("R6", f"point_hits 引用了不存在的 step_id：{h['step_id']}")
        if points and h["point_id"] not in points:
            rep.err("R6", f"point_hits 的 point_id「{h['point_id']}」不在采分点表")
        elif points:
            want = points[h["point_id"]]["score"]
            if abs(want - h["score_possible"]) > 1e-9:
                rep.err("R6", f"{h['point_id']} 的 score_possible={h['score_possible']}，采分点表是 {want}")
        if h["score_awarded"] > h["score_possible"] + 1e-9:
            rep.err("R6", f"{h['point_id']} 得分 {h['score_awarded']} 超过该点分值 {h['score_possible']}")
        if h["hit"] and abs(h["score_awarded"] - h["score_possible"]) > 1e-9:
            rep.warn("R6", f"{h['point_id']} hit=true 但未给满分")
    for f in doc["validation"]["failures"]:
        if f["step_id"] not in ids:
            rep.err("R6", f"failures 引用了不存在的 step_id：{f['step_id']}")
    for sid in doc["review"]["rejected_steps"]:
        if sid not in ids:
            rep.err("R6", f"rejected_steps 引用了不存在的 step_id：{sid}")
    for d in doc["grading"]["missing_points"]:
        if points and d["point_id"] not in points:
            rep.err("R6", f"missing_points 的 point_id「{d['point_id']}」不在采分点表")
    if not any(e.startswith("[E] R6") for e in rep.errors):
        rep.ok("R6", f"引用完整性：{len(steps)} 步 / {len(hit_pids)} 个命中点 / 0 处悬空")

    # ---- R3 方程双表示（1.2：equation 可为 null，判断步只查判据表达形式）
    n_eq = 0
    for s in steps:
        sid, eq = s["step_id"], s.get("equation")
        if eq is not None:
            n_eq += 1
            latex, sp = eq["latex"], eq["sympy"]
            if "=" in sp:
                rep.err("R3", f"{sid} 的 sympy 含等号，须写「左边减右边」：{sp}")
            if re.search(r"(?<![\w.])\d+\.\d+", sp):
                rep.err("R3", f"{sid} 的 sympy 含小数，L1 回代不可信：{sp}")
            if re.search(r"(?<![\w.*^])\d+\s*/\s*\d+", sp):
                rep.err("R3", f"{sid} 的 sympy 出现裸数字除法，须写 Rational(a,b) 或 S(a)/b：{sp}")
            cmds = set(re.findall(r"\\([A-Za-z]+)", latex))
            bad_cmd = sorted(cmds - LATEX_CMDS)
            if bad_cmd:
                rep.err("R3", f"{sid} 的 latex 用了子集外命令 {bad_cmd}：{latex}")
            if re.search(r"[\u4e00-\u9fff]", latex):
                rep.err("R3", f"{sid} 的 latex 含中文（\\text{{}} 包中文会让 sympy 全崩）：{latex}")
            if latex.count("=") > 1:
                rep.warn("R3", f"{sid} 的 latex 有两个以上等号，T09 R9 要求拆成两条：{latex}")
            declared = set(eq["symbols"])
            used = sympy_symbols(sp)
            if declared != used:
                rep.err("R3", f"{sid} 符号声明与 sympy 不一致：声明多 {sorted(declared - used)}，漏 {sorted(used - declared)}")

        cr = s.get("criterion")
        if cr is not None:
            if "=" in cr["expr"]:
                rep.err("R3", f"{sid} 的 criterion.expr 含等号，须写成「待比较量」本身：{cr['expr']}")
            if cr["comparator"] == "qualitative" and cr["expected"] is not None:
                rep.err("R3", f"{sid} 的 criterion 标 qualitative 却给了 expected={cr['expected']}")

        # value 自洽
        v = s["value"]
        if v is not None and v.get("number") is None and v.get("exact") is None:
            rep.err("R3", f"{sid} 的 value 既无数值也无精确值")
    if not any(e.startswith("[E] R3") for e in rep.errors):
        rep.ok("R3", f"方程双表示：{n_eq}/{len(steps)} 步有方程且全部可解析、符号闭合、latex 在子集内"
                     f"；其余 {len(steps) - n_eq} 步为判据步")

    # ---- R4 degraded 是状态不是判错（1.2：无方程步不参与解析状态统计）
    eq_steps = [s for s in steps if s.get("equation") is not None]
    degraded = [s["step_id"] for s in eq_steps if s["equation"]["parse_status"] == "degraded"]
    failed = [s["step_id"] for s in eq_steps if s["equation"]["parse_status"] == "failed"]
    bad_l2 = []
    for s in eq_steps:
        if s["equation"]["parse_status"] != "ok":
            for c in s["checks"]:
                if c["layer"] == "L2" and c["status"] == "pass":
                    bad_l2.append(s["step_id"])
    if bad_l2:
        rep.err("R4", f"解析未成功却标 L2 通过：{sorted(set(bad_l2))}")
    if eq_steps:
        ratio = len(degraded) / len(eq_steps)
        if ratio > 0.2:
            rep.warn("R4", f"degraded 占 {ratio:.0%} > 20%，按规则停用 L2，只保留 L1")
        if ratio == 0 and not failed:
            rep.ok("R4", f"解析状态：{len(eq_steps)}/{len(eq_steps)} ok，degraded 0%"
                         f"（另有 {len(steps) - len(eq_steps)} 步无方程，不参与统计）")
        else:
            rep.ok("R4", f"解析状态：ok {len(eq_steps) - len(degraded) - len(failed)} / degraded {len(degraded)} / failed {len(failed)}（degraded 不计入 fail）")

    # ---- R8 分值闭合
    g = doc["grading"]
    if doc["meta"].get("mode") == "zero":
        # 题库外新题（2026-11-26 T40）：无采分点，grading 三个分数字段为 null。
        # 只校验「小问分值之和 = 卷面分」，判分闭合对本题无意义。
        sub_sum = sum(q["score"] or 0 for q in doc["question"]["subquestions"])
        full = doc["meta"].get("full_score")
        if full is not None and abs(sub_sum - full) > 1e-9:
            rep.err("R8", f"各小问分值之和 {sub_sum:g} ≠ 卷面分 {full}")
        else:
            rep.ok("R8", f"新题模式不判分（grading 为 null）；小问分值合计 {sub_sum:g}"
                         + ("、卷面分 %g" % full if full is not None else "，卷面分缺"))
    else:
        if abs(sum(h["score_awarded"] for h in g["point_hits"]) - g["score_awarded"]) > 1e-9:
            rep.err("R8", f"Σpoint_hits={sum(h['score_awarded'] for h in g['point_hits'])} 与 grading.score_awarded={g['score_awarded']} 不闭合")
        if abs(g["score_total"] - doc["meta"]["full_score"]) > 1e-9:
            rep.err("R8", f"grading.score_total={g['score_total']} ≠ meta.full_score={doc['meta']['full_score']}")
        sub_sum = sum(q["score"] for q in doc["question"]["subquestions"])
        if abs(sub_sum - doc["meta"]["full_score"]) > 1e-9:
            rep.err("R8", f"各小问分值之和 {sub_sum} ≠ 卷面分 {doc['meta']['full_score']}")
        want_rate = g["score_awarded"] / g["score_total"]
        if abs(want_rate - g["weighted_rate"]) > 1e-4:
            rep.err("R8", f"weighted_rate={g['weighted_rate']}，重算应为 {want_rate:.4f}")
        if not any(e.startswith("[E] R8") for e in rep.errors):
            rep.ok("R8", f"分值闭合：{g['score_awarded']}/{g['score_total']}，weighted_rate={g['weighted_rate']}，小问合计 {sub_sum:g}")

    # ---- R10 归零点必红
    level = doc["triage"]["level"]
    zph = doc["validation"]["zero_point_hit"]
    zcodes = sorted({f["error_code"] for f in doc["validation"]["failures"] if f["error_code"] in ZERO_CODES})
    if zph and level != "red":
        rep.err("R10", f"zero_point_hit=true 但 triage.level={level}，归零点必须 red")
    if zcodes and not zph:
        rep.err("R10", f"失败里出现归零码 {zcodes}，但 zero_point_hit=false")
    if zcodes and level != "red":
        rep.err("R10", f"失败里出现归零码 {zcodes}，triage.level={level} 必须 red")
    if not (zcodes or (zph and level != "red")):
        rep.ok("R10", f"归零点：zero_point_hit={str(zph).lower()}，level={level}")

    # ---- 模式与审核一致性
    if mode == "rewrite" and doc["validation"]["rewrite_rounds"] < 1:
        rep.err("R-mode", "rewrite 模式必须 rewrite_rounds>=1（否则三档路由拿不到重写信号）")
    rv = doc["review"]
    if rv["verdict"] == "rejected" and not rv["rejected_steps"]:
        rep.err("R-mode", "verdict=rejected 但 rejected_steps 为空")
    if rv["verdict"] in ("rejected", "edited") and not rv["reason_codes"]:
        rep.err("R-mode", f"verdict={rv['verdict']} 必须给原因码（21 条错误码里选）")
    if rv["verdict"] == "edited" and not rv["diffs"] and not rv["added_steps"]:
        rep.err("R-mode", "verdict=edited 但既无 diffs 也无 added_steps")
    rep.ok("R-mode", f"模式={mode}，rewrite_rounds={doc['validation']['rewrite_rounds']}，verdict={rv['verdict']}")


def check_v12(doc: dict, rep: Report):
    """Schema 1.2 / 1.2.1 的专项规则（R11/R12/R13/R14/R15）。

    版本闸门：R11/R12/R15 只在 schema_version 为 "1.2" 或 "1.2.1" 时执行。
    理由：1.1 文档没有 criterion 概念，若对其执行「judgment 必须带 criterion」，
    「旧样例把 version 改回 1.1」这条向后兼容验收就必然报 E，与任务卡 §2 冲突。
    结构类规则（R13 整题层、R14 segment_id）不依赖版本，一律执行。
    """
    q, steps = doc["question"], doc["steps"]
    ver = str(doc.get("schema_version"))
    # 1.2.1 只加图指纹（R16/R17）与 R18，**不改 1.2 的任何语义**，故两者共用同一套规则。
    # 若这里只认 "1.2"，7 份升到 1.2.1 的样例会把 R11/R12/R15 整组静默跳过 —— 那才是真漏洞。
    is12 = ver in ("1.2", "1.2.1")

    # ---- R11 given[source=figure] ↔ figures[].provides
    prov: dict[str, list] = {}
    for fig in q.get("figures") or []:
        for p in fig.get("provides") or []:
            prov.setdefault(p["symbol"], []).append(p)

    bad = []
    for g in doc["situation"]["given"]:
        if g.get("source", "stem") != "figure":
            continue
        cands = prov.get(g["symbol"])
        if not cands:
            bad.append(f"{g['symbol']} 标 source=figure，但没有任何 figures[].provides 提供该符号")
            continue
        if g.get("value") is None:
            continue          # 符号读数（如 1.2v₀）：只查符号存在，数值不可比
        if not any(same_value(g["value"], p.get("value")) for p in cands):
            bad.append(f"{g['symbol']}：given 记 {g['value']}，provides 记 "
                       f"{[p.get('value') for p in cands]}")
    if bad:
        rep.err("R11", "图读数来源对不上：" + "；".join(bad))
    elif prov:
        n_fig_given = sum(1 for g in doc["situation"]["given"] if g.get("source") == "figure")
        n_prov = sum(len(v) for v in prov.values())
        rep.ok("R11", f"图读数来源：provides {n_prov} 条 / {len(prov)} 个符号，"
                      f"given 标 figure {n_fig_given} 项，全部对得上")
    else:
        rep.ok("R11", "本题无图读数（figures 无 provides），无需校验来源")

    # ---- R12 input_sha256
    if is12 or q.get("input_sha256") is not None:
        want = input_sha256_of(q)
        got = q.get("input_sha256")
        n_prov = sum(len(v) for v in prov.values())
        if got is None:
            rep.warn("R12", "question.input_sha256 缺失：图读数不受指纹保护（1.2 写盘应带）")
        elif got != want:
            rep.err("R12", f"input_sha256 失配：文件记 {got[:16]}…，按当前 stem_text+provides "
                           f"重算应为 {want[:16]}… —— 图读数被改过，或改完没有重算指纹")
        else:
            rep.ok("R12", f"input_sha256 与题干+{n_prov} 条读数一致：{want[:16]}…")

    # ---- R13 整题层 = 步级反推
    layers = doc["validation"]["layers"]
    diff = []
    for lay in ("L1", "L2", "L3", "L4"):
        sts = [c["status"] for s in steps for c in (s.get("checks") or []) if c["layer"] == lay]
        if "fail" in sts:
            exp = "fail"
        elif "na" in sts:
            exp = "na"
        elif "skipped" in sts:
            exp = "skipped"
        elif "pass" in sts:
            exp = "pass"
        else:
            exp = "na"
        got = layers.get(lay)
        # skipped 是「本层停用」，允许独立于步级存在（degraded > 20% 的情形）
        if got != exp and got != "skipped":
            diff.append(f"{lay} 整题={got} / 步级反推={exp}")
    if diff:
        rep.err("R13", "整题层与步级矛盾：" + "；".join(diff)
                + "（整题层必须按「有 fail 记 fail、有 na 记 na、全 pass 才 pass」反推）")
    else:
        rep.ok("R13", "整题层 = 步级反推：L1/L2/L3/L4 逐层一致")

    # ---- R14 segment_id 不悬空
    segs = [p.get("segment_id") for p in doc["situation"]["process_segments"]]
    named = [x for x in segs if x]
    dup = sorted({x for x in named if named.count(x) > 1})
    dangling = [f"{s['step_id']}→{s['segment_id']}" for s in steps
                if s.get("segment_id") and s["segment_id"] not in named]
    if dup:
        rep.err("R14", f"process_segments 的 segment_id 重复：{dup}")
    if dangling:
        rep.err("R14", f"steps[].segment_id 悬空（无对应过程分段）：{dangling}")
    if not (dup or dangling):
        n_step_seg = sum(1 for s in steps if s.get("segment_id"))
        rep.ok("R14", f"过程分段：{len(named)}/{len(segs)} 段有 segment_id，"
                      f"{n_step_seg}/{len(steps)} 步已归属，0 悬空")

    # ---- R15 kind ⇔ equation/criterion（恰好一个）
    probs = []
    n_crit = 0
    for s in steps:
        k, eq, cr = s["kind"], s.get("equation"), s.get("criterion")
        sid = s["step_id"]
        if k in ("judgment", "critical"):
            bads = []
            if eq is not None:
                bads.append("equation 必须为 null")
            if cr is None:
                bads.append("criterion 必填")
            if bads:
                probs.append(f"{sid}（{k}）" + "、".join(bads))
            if cr is not None:
                n_crit += 1
                for w in CRITERION_PLACEHOLDERS:
                    if w in cr["text"]:
                        probs.append(f"{sid} 的 criterion.text 含占位词「{w}」，判据必须能独立读懂")
        elif k in ("equation", "value"):
            bads = []
            if eq is None:
                bads.append("equation 不得为空")
            if cr is not None:
                bads.append("criterion 不该出现（只属判断/临界步）")
            if bads:
                probs.append(f"{sid}（{k}）" + "、".join(bads))
    if is12 and probs:
        rep.err("R15", "kind 与 equation/criterion 不互斥：" + "；".join(probs))
    elif is12:
        n_null = sum(1 for s in steps if s.get("equation") is None)
        rep.ok("R15", f"判断/临界步 {n_crit} 步：equation 全 null、criterion 全在；"
                      f"其余方程/求值步 equation 全非空（无方程步合计 {n_null}）")
    else:
        # 1.0/1.1 里 judgment 带 equation 是当时的合法形态，不按 1.2 标准追责
        rep.ok("R15", f"{ver} 文档：跳过 kind↔criterion 校验（1.2 专项）")


def check_v121(doc: dict, rep: Report):
    """Schema 1.2.1 的三条专项规则（R16/R17/R18）+ W-fig。

    版本闸门：
      - R16/R17/W-fig 只在 schema_version=="1.2.1" 时执行。1.0/1.1/1.2 的 figure
        没有 file 字段，对它们执行只会造出假 E（成对违约）或假 W（必需图缺失）。
      - R18 不设闸门：1.0/1.1 的 equation 在那两版里本身必填，合法旧档案恒真；
        1.2 起 equation 可空，「discussion 步两头空」才成为可能，也才需要这条底线。

    这里只查「数据自己是否可信」，不查图好不好看、caption 准不准 —— 那是 T12b/L5 的事。
    """
    q, steps = doc["question"], doc["steps"]
    ver = str(doc.get("schema_version"))
    is121 = ver == "1.2.1"
    # 1.2.1 的 file/file_sha256 是 Schema 级必填（见 answer.schema.json 的 allOf），
    # 缺键会在 S0 就中止，走不到这里；因此下面一律按「键在、值可为 null」处理。
    figs = sorted(q.get("figures") or [], key=lambda f: f.get("fig_no", 0))

    if is121:
        # ---- R16 file 与 file_sha256 成对（同时 null 或同时非 null）
        bad = []
        for fig in figs:
            f, h = fig.get("file"), fig.get("file_sha256")
            if (f is None) != (h is None):
                bad.append(f"图 {fig.get('fig_no')}：file={f!r} / file_sha256={h!r}")
        if bad:
            rep.err("R16", "file 与 file_sha256 必须同时为 null 或同时非 null：" + "；".join(bad))
        else:
            n_file = sum(1 for fig in figs if fig.get("file") is not None)
            if not figs:
                rep.ok("R16", "本题 figures 为空（无图），无图指纹可查")
            else:
                rep.ok("R16", f"图指纹字段成对：{n_file}/{len(figs)} 张有文件，其余双 null")

        # ---- R17 文件存在 + 哈希逐字相等
        missing, mismatch = [], []
        for fig in figs:
            f, h = fig.get("file"), fig.get("file_sha256")
            if f is None or h is None:
                continue
            path = os.path.join(ROOT, f)
            if not os.path.isfile(path):
                missing.append(f"图 {fig.get('fig_no')}：{f}")
                continue
            with open(path, "rb") as fh:
                got = hashlib.sha256(fh.read()).hexdigest()
            if got != h:
                mismatch.append(f"图 {fig.get('fig_no')}（{f}）：文件记 {h[:12]}…，磁盘现算 {got[:12]}…")
        if missing:
            rep.err("R17", "file 指向的文件不存在（按工作区根解析）：" + "；".join(missing))
        if mismatch:
            rep.err("R17", "file_sha256 与磁盘文件字节不符：" + "；".join(mismatch))
        if not (missing or mismatch):
            n_file = sum(1 for fig in figs if fig.get("file"))
            if n_file:
                rep.ok("R17", f"图文件指纹：{n_file} 个文件全部存在，sha256 与磁盘逐字相同")
            else:
                rep.ok("R17", "没有带 file 的图，无磁盘文件可比对")

        # ---- W-fig 必需图却没有文件（是 W 不是 E：确实没有图，但缺口要报出来）
        for fig in figs:
            if fig.get("is_required") and fig.get("file") is None:
                rep.warn("W-fig", f"图 {fig.get('fig_no')} 标 is_required=true 但 file=null"
                                  f" —— 必需图缺失，这张图不在指纹保护内")
    else:
        rep.ok("R16/R17", f"{ver} 文档：跳过 1.2.1 图指纹校验（该版无 file 字段）")

    # ---- R18 discussion 步不许两头空
    empty = [s["step_id"] for s in steps
             if s["kind"] == "discussion"
             and s.get("equation") is None and s.get("criterion") is None]
    if empty:
        rep.err("R18", "discussion 步 equation 与 criterion 同时为 null，没有任何可判定锚点，"
                       "判分器无从上手：" + "、".join(empty))
    else:
        n_d = sum(1 for s in steps if s["kind"] == "discussion")
        if n_d:
            rep.ok("R18", f"discussion 步 {n_d} 个，全部至少有一个可判定锚点（equation 或 criterion）")
        else:
            rep.ok("R18", "本题无 discussion 步，无需检查锚点")


def finish(rep: Report) -> int:
    print("-" * 68)
    if rep.errors:
        print(f"失败：{len(rep.errors)} 项 E，{len(rep.warns)} 项 W → 退出 1")
        return 1
    print(f"通过：E 0 项，W {len(rep.warns)} 项 → 退出 0")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="解析 Schema 校验器")
    ap.add_argument("answer", help="待校验的 answer json")
    ap.add_argument("--point-table", default=os.path.join(ROOT, "原始资料", "五卷力学大题_采分点总表_v2.xlsx"))
    ap.add_argument("--point-csv-dir", default=os.path.join(ROOT, "采分点"))
    ap.add_argument("--law-table", default=os.path.join(ROOT, "知识表", "定律适用条件_v1.csv"))
    ap.add_argument("--symbol-table", default=os.path.join(ROOT, "知识表", "符号白名单_v1.csv"))
    ap.add_argument("--symbol-strict", action="store_true",
                    help="白名单外的符号直接判 E（默认只给 W，因 T09 白名单在迭代）")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.answer):
        print(f"[E] 文件不存在：{args.answer}")
        return 1

    schema_path = os.path.join(HERE, "answer.schema.json")
    with open(schema_path, encoding="utf-8") as fh:
        schema = json.load(fh)
    with open(args.answer, encoding="utf-8") as fh:
        doc = json.load(fh)

    rep = Report(args.quiet)
    print(f"校验对象：{rel(args.answer)}")

    check_schema(doc, schema, rep)
    points = load_points(args.point_table, args.point_csv_dir, rep)
    if points:
        srcs = {}
        for p in points.values():
            srcs[p["from"]] = srcs.get(p["from"], 0) + 1
        rep.ok("R6-tab", "采分点表：" + "，".join(f"{k} {v} 点" for k, v in sorted(srcs.items())))
    laws = load_laws(args.law_table, rep)
    symbols = load_symbols(args.symbol_table, rep)

    check_steps(doc, points, laws, symbols, rep, args.symbol_strict)
    check_v12(doc, rep)
    check_v121(doc, rep)
    return finish(rep)


if __name__ == "__main__":
    sys.exit(main())
