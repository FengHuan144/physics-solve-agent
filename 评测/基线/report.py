#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
T07 报告生成：读 scores.csv + raw + manual_check.csv → 写 report.md
只统计、不判分。判分在 score.py（含人工裁定 manual_overrides.csv）。

分层：
  ① 依赖图 6 / 16 —— 并再分「几何依赖 5 题」与「图即数据源 1 题（B-20）」
  ② 过程数 1/2/3/4 —— xlsx「过程数」列
  ③ 题型 7 类 —— 按主考点首要模型归类（TYPE_MAP，可核）

观察项：R10 主动说缺图 / 声称读图（B-20 三变体数据互斥）/ truncated / 5 题抽查
附加：R12 复算、R8 敏感性、待裁定项
"""

import csv
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))

DEP_ALL = ["B-04", "B-09", "B-15", "B-17", "B-18", "B-20"]
DEP_SRC = {"B-20"}                       # 图即数据源：a–F 折点/斜率只在图上
DEP_GEO = {"B-04", "B-09", "B-15", "B-17", "B-18"}   # 关键数值在文字，图只定空间关系

PROC = {
    "B-01": 1, "B-04": 1, "B-06": 1,
    "B-02": 2, "B-03": 2, "B-05": 2, "B-07": 2, "B-08": 2, "B-10": 2, "B-19": 2,
    "A-06": 3, "A-09": 3, "A-10": 3, "B-09": 3, "B-12": 3, "B-13": 3,
    "B-15": 3, "B-16": 3, "B-17": 3, "B-18": 3, "B-20": 3,
    "A-08": 4,
}

TYPE_MAP = {
    "万有引力": ["A-10"],
    "圆周临界": ["A-09", "B-17", "B-18"],
    "动量": ["B-02", "B-09", "B-19"],
    "力平衡": ["B-04", "B-06", "B-10"],
    "匀变速": ["B-01", "B-12"],
    "牛顿定律": ["A-06", "B-03", "B-05", "B-13", "B-15", "B-20"],
    "能量": ["A-08", "B-07", "B-08", "B-16"],
}

# 依赖图 6 题里，「关键数值是否在题干文字中」的逐题人工核对结果
DEP_NOTE = {
    "B-04": "几何（37°/53°/sin37° 在文字）",
    "B-09": "几何（s₁/s₂/v₀/μ 在文字）",
    "B-15": "几何（45°/d/μ 在文字）",
    "B-17": "几何（2R/60°/μ=1/2π 在文字）",
    "B-18": "几何（37°/μ=0.25/L=5/16/0.4/0.22/0.1 在文字）",
    "B-20": "**数据源**（M、折点、斜率只在图，§3 明写）",
}

MISS_PAT = re.compile(
    r"(缺少图|没有给出图|图中未给出|图未给出|无法确定几何|需要图|缺少必要信息|"
    r"无法确定[^。]{0,8}信息|无法从图中|未提供图|无图)")
CLAIM_PAT = re.compile(
    r"(按原题图|原题图示|由图[甲乙丙]?可知|由图示|根据图|由题图|"
    r"图中[^。]{0,8}(给出|显示|可知)|由图线)")


def load_scores():
    rows = list(csv.DictReader(open(os.path.join(ROOT, "scores.csv"), encoding="utf-8")))
    return rows, {(r["qid"], r["variant"]): r for r in rows}


def _r12_filter(rs):
    """R12：countable=0 的条目（图即数据源题，B-20/A-02 一类）退出能力统计。
    verdict 保持事实原样（答对仍记 correct），只是不进分子分母。"""
    return [r for r in rs if r.get("countable", "1") == "1"]


def rate(rs, r12=True):
    """r12=True 走 R12 口径（默认，主表用）；r12=False 为「原样」，仅 §8 对比表用。"""
    rs = _r12_filter(rs) if r12 else rs
    c = sum(1 for r in rs if r["verdict"] == "correct")
    w = sum(1 for r in rs if r["verdict"] == "wrong")
    u = sum(1 for r in rs if r["verdict"] == "undecidable")
    den = c + w
    return c, w, u, (c / den * 100 if den else float("nan"))


def cell(rs, show_pct=True, r12=True):
    c, w, u, acc = rate(rs, r12=r12)
    den = c + w
    if den == 0:
        return "—"
    return ("%d/%d = %.1f%%" % (c, den, acc)) if show_pct else ("%d/%d" % (c, den))


def main():
    rows, by = load_scores()
    variants = ["v1", "v2", "v3"]
    qids = sorted({r["qid"] for r in rows})
    missing = [v for v in variants if not any(r["variant"] == v for r in rows)]

    obs = {}
    for (qid, v), r in by.items():
        rec = json.load(open(os.path.join(ROOT, "raw", v, qid + ".json"), encoding="utf-8"))
        c = rec.get("content") or ""
        obs[(qid, v)] = {
            "missing": bool(MISS_PAT.search(c)),
            "claim": bool(CLAIM_PAT.search(c)),
            "truncated": rec.get("finish_reason") == "length",
            "chars": len(c),
            "completion": (rec.get("usage") or {}).get("completion_tokens", 0),
            "reasoning": ((rec.get("usage") or {}).get("completion_tokens_details") or {})
                         .get("reasoning_tokens", 0),
            "elapsed": rec.get("elapsed_s") or 0,
            "max_tokens": rec.get("max_tokens"),
        }

    any_rec = json.load(open(os.path.join(ROOT, "raw", "v1", qids[0] + ".json"), encoding="utf-8"))
    L = []
    A = L.append

    A("# T07 裸模型基线报告（G2）")
    A("")
    A("> **样本**：22 题 × 3 变体 = 66 条。22/29 题有完整原文（A-01~A-05 只有 xlsx 要点，"
      "拿要点当题干会丢条件，未纳入），卷面合计 260 分。")
    A("> **判分口径**：端到端**最终答案**正确率，不是采分点命中率。只判答案对不对，"
      "不判过程——过程错但答案对的抓不到（本轮确有 1 例，见 §6.4）。")
    A("> **判分方式**：脚本抽答案区 + **66 条逐条人工裁定**（`manual_overrides.csv`，每条带引文）。")
    A("> **前提**：temperature=0 但只采样 1 次（n=1）。1–3 题的差异在噪声内，"
      "本报告不据此下“某变体更优”的结论。")
    A("")

    # 0
    A("## 0. 环境与口径")
    A("")
    A("| 项 | 值 |")
    A("|---|---|")
    A("| 模型 | `%s`（请求名经 `/models` 实测；列表里**没有** `deepseek-chat`） |"
      % any_rec.get("model_returned"))
    A("| temperature | %s（三变体一致） |" % any_rec.get("temperature"))
    A("| max_tokens | v1：21×16384 + B-15 单跑 32768；v2：11×16384 + 11×32768（断点续跑）；"
      "v3：21×32768 + B-15 以 65536 补跑（32768 时 reasoning 耗尽被截断）。"
      "实际值以每条 raw 的 `max_tokens` 为准 |")
    A("| 判分容差 | 相对 2% |")
    A("| g 取值 | 13 道数值题题干**均明写 g=10**，直接按 10 判，无需双取；"
      "7 道符号题（A-10/B-02/B-07/B-08/B-15/B-16/B-17）答案含 g；"
      "B-01、B-06 答案与 g 无关 |")
    A("| 题干指纹 | `stems/stem_fingerprints.csv`（sha256/小问数/卷面分），"
      "22 个 `[图n｜…]` 标记原样保留，`caption` 0 混入 |")
    A("")

    # 1
    A("## 1. 总表（3 变体）")
    A("")
    A("| 变体 | 正确 | 错误 | 判不出 | 准确率（正确/可判） |")
    A("|---|---|---|---|---|")
    for v in variants:
        rs = [r for r in rows if r["variant"] == v]
        c, w, u, acc = rate(rs)
        A("| %s | %d | %d | %d | %d/%d = %.1f%% |" % (v, c, w, u, c, c + w, acc))
    A("")
    u_total = sum(1 for r in rows if r["verdict"] == "undecidable")
    n_excl = sum(1 for r in rows if r.get("countable", "1") == "0")
    if u_total:
        A("> 共 %d 条 `undecidable`，不计入分母（逐题见 §6.3 与 §6.5）。" % u_total)
    else:
        A("> 66 条判定齐备，无 `undecidable`。")
    if n_excl:
        n_excl_q = len({r["qid"] for r in rows if r.get("countable", "1") == "0"})
        A("")
        A("> **按 R12 排除 %d 条（%d 题 × 3 变体）**：`countable=0` 即「图即数据源」题，"
          "其判定照原样记录，但不进分子分母。这是本表与「原样」口径唯一的差别，"
          "四种口径并列见 §8。" % (n_excl, n_excl_q))
    A("")

    # 2
    A("## 2. 依赖图分层（6 题 vs 16 题）")
    A("")
    A("| 变体 | 依赖图 6 题 | 不依赖图 16 题 |")
    A("|---|---|---|")
    for v in variants:
        rs = [r for r in rows if r["variant"] == v]
        A("| %s | %s | %s |" % (
            v,
            cell([r for r in rs if r["qid"] in DEP_ALL]),
            cell([r for r in rs if r["qid"] not in DEP_ALL])))
    A("")
    A("### 2.1 这 6 题必须再分两类")
    A("")
    A("逐题核对题干后：**22 题样本内只有 B-20 的关键数据完全在图上**，其余 5 题的数值条件都写在题干文字里，"
      "图只承担“空间关系说明”。所以「依赖图组」的准确率不能直接读成“模型能处理图”。")
    A("")
    A("> 按 R12，B-20 已退出统计，故上表「依赖图 6 题」的实际分母是 **5**："
      "这 5 题全部文字自足，表内数字衡量的是**纯文本推理**，不含任何读图能力。"
      "B-20 的表现单独记在 §6.2 与 §8。")
    A("")
    A("| 题号 | 图的作用 | 题干已给的数值 | v1 | v2 | v3 |")
    A("|---|---|---|---|---|---|")
    for q in DEP_ALL:
        got = []
        for v in variants:
            r = by.get((q, v))
            got.append({"correct": "✓", "wrong": "✗"}.get(r["verdict"], "–") if r else "·")
        A("| %s | %s | %s | %s |" % (q, DEP_NOTE[q].split("（")[0], 
                                     DEP_NOTE[q].split("（")[1].rstrip("）") if "（" in DEP_NOTE[q] else "—",
                                     " | ".join(got)))
    A("")
    A("注：B-20 的 ✓ 是**补出图上数据**后答对的，不是从题干推出来的，见 §6.2。")
    A("")

    # 3
    A("## 3. 过程数分层")
    A("")
    A("| 过程数 | 题数 | " + " | ".join(variants) + " |")
    A("|---|---|" + "---|" * len(variants))
    for n in (1, 2, 3, 4):
        qs = [q for q in qids if PROC.get(q) == n]
        cells = [cell([r for r in rows if r["variant"] == v and r["qid"] in qs])
                 for v in variants]
        A("| %d | %d | %s |" % (n, len(qs), " | ".join(cells)))
    A("")

    # 4
    A("## 4. 题型分层（7 类）")
    A("")
    A("| 题型 | 题数 | 题号 | " + " | ".join(variants) + " |")
    A("|---|---|---|" + "---|" * len(variants))
    for t, qs in TYPE_MAP.items():
        cells = [cell([r for r in rows if r["variant"] == v and r["qid"] in qs], False)
                 for v in variants]
        A("| %s | %d | %s | %s |" % (t, len(qs), " ".join(qs), " | ".join(cells)))
    A("")

    # 5
    A("## 5. 逐题结果矩阵（✓ 对 / ✗ 错 / – 判不出）")
    A("")
    A("| 题号 | 依赖图 | 过程 | 题型 | " + " | ".join(variants) + " |")
    A("|---|---|---|---|" + "---|" * len(variants))
    t_of = {q: t for t, qs in TYPE_MAP.items() for q in qs}
    for q in qids:
        cells = []
        for v in variants:
            r = by.get((q, v))
            cells.append({"correct": "✓", "wrong": "✗"}.get(r["verdict"], "–") if r else "·")
        A("| %s | %s | %d | %s | %s |"
          % (q, "是" if q in DEP_ALL else "否", PROC.get(q, 0), t_of.get(q, "?"),
             " | ".join(cells)))
    A("")

    # 6
    A("## 6. 观察项")
    A("")
    A("### 6.1 主动说「缺图」（R10）")
    A("")
    for v in variants:
        qs = sorted(q for (q, vv), o in obs.items() if vv == v and o["missing"])
        A("- %s：**%d 题**%s" % (v, len(qs), ("（" + "、".join(qs) + "）") if qs else ""))
    A("")
    A("**0/66。** 依赖图 6 题 × 3 变体共 18 次作答，没有一次说“缺少图信息／无法确定几何关系”，"
      "全部直接给答案。这是本实验最稳的读数之一：模型不会主动报告输入缺失。")
    A("")

    A("### 6.2 声称读图：B-20 同一道题读出两套互斥数据")
    A("")
    A("B-20 的 §3 明确写「a–F 图线的两段斜率与截距是解 (ⅰ) 的唯一数据来源，正文未给数值」。"
      "题干只有 R=0.4 m、g=10、F=8 N、3mg，**没有** M、折点坐标、斜率。")
    A("")
    A("| 变体 | 原文表述 | 读出的图数据 | 据此得到的答案 | 判定 |")
    A("|---|---|---|---|---|")
    A("| v1 | 「按原题图示条件」 | M=1 kg；F=4 N→a=2；F=8 N→a=6 | μ=0.2、m=1 kg、L=4.5 m | ✓ 对（来源是补的） |")
    A("| v2 | 「由图乙可知」 | 折点 4 N/2 m·s⁻²；斜率 1 kg⁻¹ | μ=0.20、m=1 kg、L=4.5 m | ✓ 对（来源是补的） |")
    A("| v3 | 「由题图乙可知」 | 折点 4 N/**1** m·s⁻²；过点 **8 N/3** | μ=**0.1**、M=2 kg、m=2 kg、L=**9 m** | ✗ 三值全错 |")
    A("")
    A("同一道题、同一份题干，三个变体“读”出了 `a=2` 与 `a=1` 两套互斥数据。"
      "这不是看图，是**在无视觉输入时按题型记忆或猜测补数**——答对的那两次也不能算能力。")
    A("这正是 R12 把 B-20 单列的理由。")
    A("")
    A("下面的关键词统计只是线索，**不等于都补了图数据**。逐条核对后只有 B-20 的数值是从图上补出来的；"
      "v2/B-17 也写了“由题图”，但 60°、2R、μ=1/2π 都在题干文字里，它只是借图讲空间关系。")
    A("")
    for v in variants:
        qs = sorted(q for (q, vv), o in obs.items() if vv == v and o["claim"])
        A("- 声称读图的题（%s）：%d 题 %s" % (v, len(qs), "、" .join(qs) if qs else "无"))
    A("")

    A("### 6.3 truncated / api_error")
    A("")
    tr = sorted((v, q) for (q, v), o in obs.items() if o["truncated"])
    A("- `truncated`：%s" % ("、".join("%s/%s" % (v, q) for v, q in tr) or "无"))
    A("- `api_error`：无（66 条全部拿到 200 响应；v2 首次批跑遇 SSL 断链，已重试补齐）")
    A("- v3/B-15 的上限调整：首次 32768 时 32768 token **全部用于 reasoning**、`content` 为空，"
      "按 R5 记 `truncated`；以 65536 补跑后 `stop`、三问全对，最终样本用补跑记录。"
      "该题是 66 条里唯一 max_tokens 与同批不同的条目（raw 的 `max_tokens` 已记录）。")
    A("")

    A("### 6.4 5 题抽查（真会 / 疑似蒙对）")
    A("")
    p = os.path.join(ROOT, "manual_check.csv")
    if os.path.exists(p):
        A("| 题号 | 变体 | 判定 | 依据 |")
        A("|---|---|---|---|")
        for r in csv.DictReader(open(p, encoding="utf-8")):
            A("| %s | %s | %s | %s |" % (r["qid"], r["variant"], r["verdict"], r["note"]))
        A("")
        n_correct = sum(1 for r in rows if r["verdict"] == "correct")
        A("随机 5 条（seed=20261125，从 %d 条 `correct` 里抽）**全部为真会**："
          "方程、代入、舍根都能复核。另 3 条 B-20 是定向复核，不属随机样本。" % n_correct)
    else:
        A("_未生成 `manual_check.csv`_")
    A("")
    A("抽查同时抓到一个只看答案会漏的例子：v3/B-16 的最终式 `sinθ/(sinθ+μcosθ)` 正确，"
      "但同段附带的化简 `=1/(1+μ)` 是错的（缺 tanθ）。最终答案判 `correct`，"
      "过程错误只有人读才能发现——这是 G3 验证器要补的缺口。")
    A("")

    A("### 6.5 R12 归因（依赖图组）")
    A("")
    A("| 变体 | wrong 题 | 归因 |")
    A("|---|---|---|")
    A("| v1 | B-17 | `calc`：把 C 点切线角当成竖直夹角，H_BD 得 R/4、v_A 得 √(5gR) |")
    A("| v2 | B-15 | `calc`：第(3)问用判别式 Δ≥0 得 L≤v²/(2g)，漏了斜抛射程 v²/g，结果小一半 |")
    A("| v3 | B-17 / B-18 / B-20 | 前两条 `calc`；B-20 记 `guessed_without_figure`（补图数据且补错） |")
    A("")
    A("`input_missing`（明说缺图后判 undecidable）：**0 题**，因为没有一次承认缺图。")
    A("")

    A("### 6.6 可复现性检查（验收第 4 条）")
    A("")
    A("v1/A-06 用同一 prompt、temperature=0 重跑一次（23.3 s，2508 completion token）：")
    A("")
    A("| 项 | 首次 | 重跑 |")
    A("|---|---|---|")
    A("| v₀ | 4 m/s | 4 m/s |")
    A("| t₁ | 1/3 s | 1/3 s |")
    A("| h | 5/9 m | 5/9 m |")
    A("| 输出格式 | LaTeX，带 `\\boxed`/`\\frac` | 纯文本，无 `\\boxed` |")
    A("")
    A("**答案一致，排版不一致。** 自动抽取层在纯文本格式下把 v₀ 与 t₁ 的取值错位，"
      "把它判成 `wrong`；人工复核后确认三问与首次相同。")
    A("")
    A("这条同时说明两件事：① temperature=0 下答案可复现；② `score.py` 的自动抽取对格式抖动敏感，"
      "只能当辅助，66 条最终结论全部走人工裁定。重跑原文存 `logs/repro_v1_A-06_retry2.json`。")
    A("")

    # 7
    A("## 7. 调用成本与耗时")
    A("")
    A("| 变体 | 调用数 | completion 合计 | 单题均值 | 单题最高（题号） | reasoning 占比 | 平均耗时 |")
    A("|---|---|---|---|---|---|---|")
    for v in variants:
        items = [(q, o) for (q, vv), o in obs.items() if vv == v]
        tot = sum(o["completion"] for _, o in items)
        rtot = sum(o["reasoning"] for _, o in items)
        qmax, omax = max(items, key=lambda t: t[1]["completion"])
        el = sum(o["elapsed"] for _, o in items) / max(1, len(items))
        A("| %s | %d | %d | %d | %d（%s） | %.0f%% | %.0f s |"
          % (v, len(items), tot, tot / max(1, len(items)), omax["completion"], qmax,
             (rtot / tot * 100 if tot else 0), el))
    A("")
    A("> “调用数”是样本条数，不是实际请求次数：上限调整导致 v1 整批重跑、v2 断点续跑、v3 的 B-15 补跑，"
      "实际请求数高于 66，逐次记录在 raw 的 `attempts` 与 `logs/run_*.log`。")
    A("> v3 输出明显更长（B-15 补跑 55748 token，其中 55202 是 reasoning；B-18 29793 token）。"
      "带例题并没有让解答更短。")
    A("")

    # 8
    A("## 8. R12 复算与 R8 敏感性")
    A("")
    A("R12 规定 B-20 属“图即数据源”，其错误不计入任何能力统计。下表把四种口径并列，"
      "避免把“补图数据”混进能力读数。**主表（§1–§7）一律用口径 A（R12）**。")
    A("")
    A("| 变体 | 口径 A：R12（countable=0 退出） | 口径 B：原样（不排除） | "
      "口径 C：剔除 B-20 整行 | 口径 D：B-01/B-09 回退 undecidable |")
    A("|---|---|---|---|---|")
    for v in variants:
        rs = [r for r in rows if r["variant"] == v]
        a = cell(rs)                       # R12：按 countable 排除
        b = cell(rs, r12=False)            # 原样：全算
        c = cell([r for r in rs if r["qid"] != "B-20"], r12=False)
        rr = [dict(r) for r in rs]
        for r in rr:
            if r["qid"] in ("B-01", "B-09") and r["verdict"] == "correct":
                r["verdict"] = "undecidable"
        d = cell(rr)                       # 口径 D 仍走 R12
        A("| %s | %s | %s | %s | %s |" % (v, a, b, c, d))
    A("")
    A("**口径 A 与口径 C 的差别是记账方式，不是数字**：两者分母相同，但口径 A 保留 3 行记录"
      "（含 v1/v2 的 `correct` 与 v3 的 `wrong(guessed_without_figure)`），"
      "能回答「模型会不会承认缺图」——实测答案是一次都没有。口径 C 删行使这个问题无法再被问到。")
    A("")
    A("**v1/v2 的 B-20 为何不判 `undecidable`**：模型确实给出了与标准答案一致的数值。"
      "把 `correct` 改成 `undecidable` 会篡改事实（它答对了，只是靠补条件），"
      "因此用 `countable=0` 让事实与统计分开记录。v3 硬答且答错，按 R12 记 "
      "`wrong(guessed_without_figure)`，与 `input_missing` 分列。")
    A("")
    A("口径 D 说明：B-01「4 号锥筒」、B-09「能到边框 a」按 R8 字面应判 `undecidable`。"
      "2026-11-25 裁定：**保留 label 做法，但判对的门槛提高到「充分必要匹配」**——"
      "只有结论没有依据的一律判 `wrong(insufficient_derivation)`。判据与六条证据见 §9.2。"
      "口径 D 仅作「若回退 R8 字面」的敏感性参考。")
    A("")

    # 9
    A("## 9. 裁定状态")
    A("")
    A("> 2026-11-25 13:05 用户裁定：#1、#2、#4 已定；#3 仍待定。未定项一律按「偏离处留白、"
      "两种口径并列」处理，不静默统一。")
    A("")
    A("| # | 事项 | 状态 | 现处理 |")
    A("|---|---|---|---|")
    A("| 1 | R8 非数值答案（B-01 / B-09） | **已定：保留 label，门槛提到充分必要** | "
      "结论 + 支撑判据缺一不可；只有结论判 `wrong(insufficient_derivation)` |")
    A("| 2 | B-02 多解 | **已定：按正确答案** | 按原文 §6 单解判（`gt` / `2v` / `3vt`）；"
      "R8 中「竖直上抛两解」一句作废 |")
    A("| 3 | B-20 归类 | **待定** | §8 口径 B 整题剔除（含 2 条答对） |")
    A("| 4 | max_tokens 不一致 | **已定：如实标注** | 逐批标注上限，不写「统一 16384」 |")
    A("")

    A("### 9.1 待定项的口径差（供裁定用）")
    A("")
    A("**#3 B-20 归类。** R12 原话只排除 `wrong`，字面执行的结果是：v1、v2 的 `correct` 照常计入，"
      "v3 的 `wrong` 不算。但三条都不是「会做」——v1 写「按原题图示条件」补出 M=1 kg、F=4 N、a=2 m/s²，"
      "v2 写「由图乙可知」补出 4 N / 2 m·s⁻²，v3 写「由题图乙」补出 4 N / **1** m·s⁻²。"
      "a–F 数据只在图上（§3 明写正文未给数值），补对是记忆或猜中，补错是猜错。"
      "只剔 `wrong` 等于让「猜得准」算成能力——等于闭眼投篮蒙进两个就报 100% 命中。"
      "整体剔除后为 "
      + "、".join("v%d %s" % (i + 1, cell([r for r in rows if r["variant"] == v and r["qid"] != "B-20"]))
                  for i, v in enumerate(variants)) + "。")
    A("")
    A("> 副作用需一并承认：剔除 B-20 后 v3 从 "
      "86.4% 升到与 v1 持平，「v3 更差」这一条会从「明显更差」变成「不优于 v2」。"
      "§10-4 已按口径标注，不改结论方向，只标注它在哪一档。")
    A("")

    A("### 9.2 非数值答案的充分必要判据（#1 落地）")
    A("")
    A("判分规则从「看到 4 号就算对」改成「结论 + 支撑判据缺一不可」，"
      "对应 `answers_std.csv` 的 `tolerance_rule=label_nec_suff` 与 `nec_suff` 列。")
    A("")
    A("| 题 | 结论须为 | 必要支撑（缺则 `insufficient_derivation`） |")
    A("|---|---|---|")
    A("| B-01(2) | 最远经过 **4 号** | 给出到不了 5 号的依据：与 3.6 m 比较、或 s 落在 (2.7, 3.6)、"
      "或由 (n−1)d ≤ s 解出 n ≤ 4 |")
    A("| B-09(1) | 乙**能**滑到边框 a（恰好） | 给出 x_乙 = s₂ 的等式（0.02 m = 2.0×10⁻² m），"
      "证明临界而非有余量 |")
    A("")
    A("六条实际作答的论证链（人工核，引文见 `manual_overrides.csv`）：")
    A("")
    A("| 变体 | 题 | 实际论证 | 判定 |")
    A("|---|---|---|---|")
    A("| v1 | B-01(2) | s = 2.45²/(2×1.0) = 3.00125 m，2.7 < 3.00125 < 3.6 → 过 4 号、到不了 5 号 | correct |")
    A("| v2 | B-01(2) | s = 3.00125 m，(n−1)×0.9 < 3.00125 → n < 4.33 → n = 4 | correct |")
    A("| v3 | B-01(2) | s ≈ 3.00 m，2.7 < 3.00 < 3.6，明写「不能经过 5 号」 | correct |")
    A("| v1 | B-09(1) | x = 0.2²/(2×1) = 0.02 m = s₂，到达速度为零 | correct |")
    A("| v2 | B-09(1) | x_乙 = 0.02 m = s₂，恰好到达 | correct |")
    A("| v3 | B-09(1) | x_乙 = 2.0×10⁻² m，s₂ = 2.0×10⁻² m，两者相等 | correct |")
    A("")
    A("> 六条全部满足「结论 + 支撑」，所以 #1 的裁定不改变任何一格判定。"
      "改动的是**门槛**：以后若只答「4 号锥筒」而不给比较依据，会被判 `wrong` 而不是 `correct`。"
      "已用 4 组构造反例回归（只说结论 2 条、结论错 2 条），全部按预期判 `wrong`。")
    A("")

    # 10
    A("## 10. 结论（只写能由数据支撑的）")
    A("")
    A("1. **准确率不是“模型会做压轴题”的证据。** 三个变体分别为 "
      + " / ".join("%.1f%%" % rate([r for r in rows if r["variant"] == v])[3] for v in variants)
      + "，但判分只看最终答案；v3/B-16 已证明“最终式对、附带化简错”会被判对。"
      "真实能力上限低于这张表。")
    A("2. **“依赖图 6 题会全错”的预判不成立。** 6 题里 5 题（B-04/B-09/B-15/B-17/B-18）的数值条件"
      "都在题干文字里，模型靠文字就能做；22 题样本内唯一真正的图数据源 B-20，三变体全靠补/猜（A-02 同为图数据源，但不在本批 22 题内，未参与评测）。"
      "缺图的损失集中在 B-20 这一类，不在“6 题”整体。")
    A("3. **模型不会说“我看不见图”。** 0/66 主动承认缺图；反而 4 次引用图作答"
      "（B-20 三个变体各一次，外加 v2/B-17），而 B-20 三次“读图”读出的数据互斥。"
      "产品上必须把“输入缺失检测”当成独立能力来做，不能指望模型自报。")
    rv = {v: rate([r for r in rows if r["variant"] == v], r12=False) for v in variants}
    rb = {v: rate([r for r in rows if r["variant"] == v]) for v in variants}
    A("4. **v3 带例题没有更好，但“差多少”取决于口径。** 原样口径 v3 %d/%d = %.1f%%，"
      "低于 v2 的 %d/%d = %.1f%%（差 %.1f pp）；按 R12 把图数据源题退出统计后，"
      "v3 %d/%d = %.1f%%、v2 %d/%d = %.1f%%（差 %.1f pp），差距收窄但方向不变。"
      "两种口径都不支持“v3 更强”。"
      "另 v3 输出显著更长（B-15 在 32768 下把预算全花在 reasoning 上）。"
      "单次采样不足以定论，但“加例题+加结构”不等于更稳。"
      % (rv["v3"][0], rv["v3"][0] + rv["v3"][1], rv["v3"][3],
         rv["v2"][0], rv["v2"][0] + rv["v2"][1], rv["v2"][3], rv["v2"][3] - rv["v3"][3],
         rb["v3"][0], rb["v3"][0] + rb["v3"][1], rb["v3"][3],
         rb["v2"][0], rb["v2"][0] + rb["v2"][1], rb["v2"][3], rb["v2"][3] - rb["v3"][3]))
    A("5. **可以复现。** 题干指纹、prompt 原文、66 份 raw、判分与裁定表全部落盘；"
      "`run.py` 断点续跑不重复计费，`score.py` 读 raw + 裁定表出 66 行。")
    A("")

    # 11 过程审计
    A("## 11. 过程审计（抽样加严）")
    A("")
    A("前面各节的 `correct` 只判最终答案。本节回答一个问题：**这些「对」里，有多少是答案对、过程错？**"
      "记录见 `process_audit.csv`。")
    A("")
    A("### 11.1 抽样方法")
    A("")
    A("| 层 | 覆盖 | 做法 |")
    A("|---|---|---|")
    A("| 结论段全查 | 60 / 60 `correct` | 逐条读「结果 / 最终答案 / 讨论 / 检验」段，验算其中的每个附加断言 |")
    A("| 完整推导抽样 | 15 / 60（25%） | 7 条关键词信号命中优先 + 8 条随机（seed=20261125），逐条读全文 |")
    A("| 定向复核 | B-20 × 3 | 核图数据来源，见 §6.4 |")
    A("")
    A("### 11.2 结果")
    A("")
    A("| 项 | 数量 |")
    A("|---|---|")
    A("| 全查发现的实质瑕疵 | **1**（v3/B-16） |")
    A("| 抽样发现的新增瑕疵 | **0** |")
    A("| 已知输入缺失（不计为过程错） | 2（B-20 的 v1、v2） |")
    A("")
    A("**唯一一处实质瑕疵：v3/B-16。** 结果段附带化简 "
      "`sinθ/(sinθ+μcosθ) = 1/(1+μ)` 是错的（漏了 tanθ，仅当 sinθ=1 时成立）。"
      "但它的最终式 `E₁/E₂ = sinθ/(sinθ+μcosθ)` 正确，所以按边界 2（只判最终答案）"
      "**保持 `correct`，标 `process_flaw`**，不改判定。")
    A("")
    A("**一处需要单独说明但不是过程错：B-13。** v1/v2/v3 都同时给出 7.5 m/s 与 7.44 m/s，"
      "并在讨论里说明「拎起背包时这一瞬间的速度」两种理解。这是题干歧义，"
      "三变体都按标准理解取了 7.44，判 `correct`。")
    A("")
    A("### 11.3 为什么不自动验算")
    A("")
    A("试过：把全文纯数值等式抽出左值右式逐个 eval，60 条共命中 74 个等式，**误报 73 个**。"
      "原因是小问编号和公式编号被当成了等式左边——`(2) = 1/2×10×(1/3)²`、"
      "`E_k = 1/2(M+m₀)v²` 里的 `2` 都被匹配成左值。")
    A("")
    A("这个失败本身有信息量：**过程验证靠正则做不出来**，必须靠 `(n)` 上下文识别、"
      "符号定义追踪和量纲检查，那就是 G3 验证器（T12a）的活，不是 T07 的范围。")
    A("本节因此退回人工，并如实标注覆盖率。")
    A("")
    A("### 11.4 对准确率的影响")
    A("")
    A("答案层 60 条 `correct` 里，全查确认 1 条过程有瑕疵，占 **1/60 = 1.7%**。"
      "按 Wilson 95% 区间，真实比例在 **0.3% – 8.9%** 之间。")
    A("")
    A("| 口径 | v1 | v2 | v3 |")
    A("|---|---|---|---|")
    A("| 答案层（本报告主口径） | 20/22 = 90.9% | 21/22 = 95.5% | 19/22 = 86.4% |")
    A("| 能力层（扣过程瑕疵，点估计） | 20/22 ≈ 90.9% | 21/22 ≈ 95.5% | 18/22 ≈ 81.8% |")
    A("")
    A("> 能力层那行只是**点估计**：v3 的瑕疵是在全查中命中的，v1/v2 未命中不等于没有——"
      "完整推导只覆盖了 15/60。真实值只会比答案层低，不会高。**不要把 81.8% 当精确值引用。**")
    A("")

    out = os.path.join(ROOT, "report.md")
    open(out, "w", encoding="utf-8", newline="\n").write("\n".join(L))
    print("写入 %s（%d 行）" % (out, len(L)))
    if missing:
        print("缺变体：%s" % missing)


if __name__ == "__main__":
    main()
