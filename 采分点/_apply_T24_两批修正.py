# -*- coding: utf-8 -*-
"""T24 两批修正一次落表：把批2（B-05~B-13）与批3（B-15~B-20）的修正写进
原始资料/五卷力学大题_采分点总表_v2.xlsx 的「采分点总表」sheet。

设计原则
--------
1. 每处改动都断言「旧串在该单元格里出现且仅出现 1 次」，对不上就整脚本中止，
   不会出现「改了一半」。
2. 默认干跑（不写盘）；`--write` 才写，且先备份。
3. `--verify` 只读校验，可对已写入的表反复跑。

用法
----
    python 采分点/_apply_T24_两批修正.py            # 干跑，打印变更清单与指标
    python 采分点/_apply_T24_两批修正.py --write    # 备份 + 写盘
    python 采分点/_apply_T24_两批修正.py --verify   # 写后校验
"""
import argparse
import datetime
import pathlib
import re
import shutil
import sys

import openpyxl
from collections import OrderedDict

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
XLSX = ROOT / "原始资料" / "五卷力学大题_采分点总表_v2.xlsx"
SHEET = "采分点总表"

COLS = {
    "分": "分值",
    "类": "采分类别",
    "临界": "含临界",
    "码": "错误码",
    "径": "判分口径",
    "备": "备注",
    "采": "采分点（必须出现的式子或判断）",
}
Q2 = ["B-05", "B-06", "B-07", "B-08", "B-09", "B-10", "B-12", "B-13"]
Q3 = ["B-15", "B-16", "B-17", "B-18", "B-19", "B-20"]

LOG = []          # 变更清单
FAILED = []       # 断言失败


class Sheet:
    def __init__(self, path):
        self.wb = openpyxl.load_workbook(path)
        self.ws = self.wb[SHEET]
        hdr = [c.value for c in self.ws[1]]
        self.I = {h: i for i, h in enumerate(hdr)}
        self.rows = {}      # point_id -> row index (1-based)
        for r in range(2, self.ws.max_row + 1):
            pid = self.ws.cell(r, self.I["point_id"] + 1).value
            if pid:
                self.rows[str(pid)] = r

    def get(self, pid, col):
        return self.ws.cell(self.rows[pid], self.I[COLS[col]] + 1).value

    def put(self, pid, col, val):
        self.ws.cell(self.rows[pid], self.I[COLS[col]] + 1).value = val

    # --- 三种改动 ---
    def set(self, pid, col, new, why):
        old = self.get(pid, col)
        if old == new:
            return
        self.put(pid, col, new)
        LOG.append((pid, COLS[col], f"{old!r}", f"{new!r}", why))

    def sub(self, pid, col, old, new, why):
        cur = str(self.get(pid, col) or "")
        n = cur.count(old)
        if n != 1:
            FAILED.append(f"{pid} {COLS[col]}：期望「{old[:30]}」出现 1 次，实际 {n} 次")
            return
        self.put(pid, col, cur.replace(old, new))
        LOG.append((pid, COLS[col], f"删/改「{old}」", f"为「{new}」" if new else "（删去）", why))

    def app(self, pid, col, txt, why):
        cur = str(self.get(pid, col) or "")
        if txt in cur:
            return
        self.put(pid, col, (cur + "；" if cur else "") + txt)
        LOG.append((pid, COLS[col], "（原样保留）", f"追加「{txt}」", why))

    def each(self, q, fn):
        for pid in [p for p in self.rows if p.startswith(q + "-S")]:
            fn(pid)


# =====================================================================
# 修正正文
# =====================================================================
def apply_all(s):
    # ---------- 批2 · 三处「两步分值互换」回调（差额为 0 的题不该有互换）----------
    s.set("B-05-S02", "分", 2, "批2 §4.5：B-05 初值合计＝卷面 10，互换无必要")
    s.set("B-05-S03", "分", 2, "同上，与 S02 互换的另一半")
    s.set("B-09-S02", "分", 2, "批2 §1#6：初值合计 10 < 卷面 11，缺的 1 分本可正常补给 ②")
    s.set("B-09-S07", "分", 1, "同上，④ 回初值")
    s.set("B-13-S06", "分", 2, "批2 §1#5：初值合计 11＝卷面 11，纯记账错位")
    s.set("B-13-S07", "分", 1, "同上，④ 回初值")

    # ---------- 批2 · 类别误归 ----------
    s.set("B-05-S05", "类", "② 原始方程", "批2 §4.2：主体是方程 v₁cosα=v₀cos37°")
    s.set("B-09-S04", "类", "⑤ 边界判断", "批2 §1#7：「能否到达」+「s 恰等于 s₂」是边界判断")
    s.set("B-10-S05", "类", "③ 过程量", "批2 §4.2：联立两式解 sinθ 与 k")

    # ---------- 批2 · 错误码 ----------
    s.set("B-07-S04", "码", "E-06", "批2 §1#16：E-15 是临界误判，本步是全非弹性碰撞且含临界=否")
    s.set("B-10-S08", "码", "E-10", "批2 §1#15：漏 2 倍属代入代数错，不是基数/分母误取（E-01 归零级）")

    # ---------- 批2/批3 · 含临界：一律照题干原文 §8 取值 ----------
    for q in ["B-09", "B-10", "B-13", "B-15", "B-16", "B-20"]:
        s.each(q, lambda pid: s.set(pid, "临界", "是", f"{q} 题干 §8 明写「是否含临界：是」"))

    # ---------- 批2 · 口径：两处判反（把对的判错 / 把错的判对）----------
    s.sub("B-08-S06", "径",
          "；写成 (5/4)√(2hE_p/(mg)) 未化简不扣分",
          "；（(5/4)√(2hE_p/(mg)) 与正解差 √2 倍，同样 0 分）",
          "批2 §1#1：该式 =1.768，正解系数 5/2=2.5，等于给差 41% 的答满分")
    s.sub("B-06-S06", "径",
          "用 P = Fv cosθ 却把 v 取成瞬时速度又未说明本步 0 分",
          "把 t 取成 20 s（或把位移取成 15 m）本步 0 分",
          "批2 §1#2：本题匀速，瞬时速≡平均速，P=600 W 正确，原句是误杀")

    # ---------- 批2 · 口径：三处改松 ----------
    s.sub("B-06-S01", "径", "只写“平衡”未指明水平方向本步给分",
          "只写“平衡”未指明水平方向本步 0 分", "批2 §1#11：同句模板第 4 次出现，统一改严")
    s.sub("B-12-S01", "径", "漏“整体”说明但结果正确本步给分",
          "漏“整体”说明（只列滑块或只列杆）本步 0 分", "批2 §1#11")
    s.sub("B-13-S04", "径", "漏“同向”说明本步给分",
          "漏“同向”说明本步 0 分", "批2 §1#11")

    # ---------- 批2 · 口径：一处改严（整体法是替代解法，不是错法）----------
    s.sub("B-12-S03", "径", "；用整体法求 N₂ 本步 0 分",
          "；未写隔离杆这一步、只给结果本步 0 分",
          "批2 §1#3：整体法 ΣF=Σma 同样得 5 N，判 0 属误杀")

    # ---------- 批2 · ② 合步必填句（规范 §1 2026-11-25 补充）----------
    for pid in ["B-05-S01", "B-05-S02", "B-08-S04", "B-09-S02",
                "B-09-S03", "B-12-S07", "B-13-S01"]:
        s.app(pid, "径", "方程对即给分，结果错扣 0.5（1 分步记 0）",
              "批2 §5.5：7 步 ② 合步全部缺规范 §1 必填句")

    # ---------- 批2 · 重复计分外观 ----------
    s.app("B-06-S06", "径",
          "本步只判是否辨识为平均功率，不重复计 P = W/t 的列式分（列式分在 S07）",
          "批2 §5.6：S06 判「选它」、S07 写它，构成 E-22 外观")

    # ---------- 批2 · 备注：分问数与表内实际不符（3 题）----------
    def b06(pid):
        s.sub(pid, "备", "按骨架推定 4／4／6",
              "按骨架推定 4／5／5（(2)＝S04+S05、(3)＝S06+S07+S08）",
              "批2 §1#13：表内实际 4/5/5，备注写 4/4/6")
    for pid in [p for p in s.rows if p.startswith("B-06-S")]:
        b06(pid)

    def b09(pid):
        s.sub(pid, "备", "按骨架推定（1）5／（2）6",
              "按骨架推定（1）7／（2）4（(1) 含三个②、初值下限 6，5 分不可达；"
              "单量 7/4 递减为结构性，规范 §3 待补条款）",
              "批2 §1#14：表内实际 6/5，备注写 5/6")
    for pid in [p for p in s.rows if p.startswith("B-09-S")]:
        b09(pid)

    def b16(pid):
        s.sub(pid, "备", "按骨架推定 4／4／4",
              "按骨架推定 4／3／5（与源页 §7 逐问赋分 4＋3＋5 一致）",
              "T00 复核：表内实际 4/3/5，备注写 4/4/4")
    for pid in [p for p in s.rows if p.startswith("B-16-S")]:
        b16(pid)

    def b19(pid):
        s.sub(pid, "备", "按骨架推定（1）5／（2）7",
              "按骨架推定（1）6／（2）6",
              "批3 §1-14：表内实际 6/6，备注写 5/7")
    for pid in [p for p in s.rows if p.startswith("B-19-S")]:
        b19(pid)

    def b17(pid):
        s.sub(pid, "备", "（4／5／6）",
              "（4／6／5：S06 归 ② 回 2 分、S10 归 ④ 回 1 分后，(3) 由 6 降 5；"
              "单量 4/6/5 递减登记为结构性）",
              "T00 复核：按初值归位后小问分为 4/6/5")
    for pid in [p for p in s.rows if p.startswith("B-17-S")]:
        b17(pid)

    # ---------- 批2 · 备注：抬分 / 压分理由（规范 §3 第二步要求写明）----------
    s.app("B-05-S05", "备",
          "类别 ①→②：主体是方程 v₁cosα = v₀cos37°，「水平分速不变」是它的前提判断"
          "（T00 2026-11-25 裁定 3）；2 分即 ② 初值",
          "批2 §1#9：判断＋方程合步，归 ① 会逼出「①取2」违规")
    s.app("B-06-S04", "备",
          "② 取 3 分：初值 2，抬 1 分（跨全程：两绳拉力在 20 m 全长做功）",
          "T00 补记：批2 §4.1 提到「② 抬到 3 分 1 步」但未列行")
    s.app("B-06-S05", "备", "④ 抬到 2 分：初值 1，抬 1 分", "批2 §4.1：配平抬分，备注未写")
    s.app("B-06-S08", "备",
          "④ 抬到 2 分：初值 1，抬 1 分；本题初值合计 12 < 卷面 14，差 2 分由 S05、S08 各抬 1 分补足",
          "批2 §4.1：配平抬分，备注未写")
    s.app("B-08-S02", "备", "④ 抬到 2 分：初值 1，抬 1 分（差 3 分的说明见 S06 备注）",
          "批2 §4.1：配平抬分，备注未写")
    s.app("B-08-S06", "备",
          "④ 抬到 3 分：初值 1，抬 2 分。本题初值合计 9 < 卷面 12，差 3 分；"
          "T00 2026-11-25 裁定不补步（卷面 12 系骨架推定，不在推定分值上做结构加步），"
          "改由 S02 抬 1、本步抬 2 闭合；若卷面实为 10 分，本步应回 2 分",
          "批2 §1#10 + T00 裁定：差 3 分不补步，抬分理由必须写明")
    for pid in ["B-10-S01", "B-10-S03", "B-10-S04"]:
        s.app(pid, "备", "② 压到 1 分：初值 2，压 1 分。本题初值合计 12 > 卷面 9，超预算 3 分",
              "批2 §8.1 + T00 裁定 2：② 超预算压缩须写明")
    s.app("B-12-S08", "备", "② 压到 1 分：初值 2，压 1 分。本题初值合计 12 > 卷面 11，超预算 1 分",
          "同上")
    s.app("B-09-S06", "备", "③取2：两段累加（t₁、t₂ 各 1 分）", "批2 §4.1：③ 取 2 须写理由")
    s.app("B-13-S05", "备", "③取2：两量各 1 分（背包 v₁、滑雪者 v₂）", "同上")
    s.app("B-10-S05", "备",
          "类别 ④→③：联立两式解出 sinθ 与 k（T00 2026-11-25 裁定 3）；按 1 分计，"
          "因 ③ 联立初值 2 而本题初值已超卷面 3 分",
          "批2 §1#8：类别误归，只改类别不改分")

    # ---------- 批3 · 分值归位 ----------
    s.set("B-17-S06", "分", 2, "批3 §1#6：② 初值 2，原表压到 1 分（与 S10 成对互换）")
    s.set("B-17-S10", "分", 1, "同上，④ 回初值")
    s.set("B-19-S02", "分", 2, "批3 §1#4：② 初值 2；本题初值合计＝卷面 12，零代价")
    s.set("B-19-S04", "分", 1, "同上，④ 回初值")
    s.set("B-19-S06", "分", 2, "同上，第二对互换")
    s.set("B-19-S08", "分", 1, "同上，④ 回初值")

    # ---------- 批3 · 类别 ----------
    s.set("B-15-S02", "类", "② 原始方程",
          "批3 §1#7：主体是运动学式 d = ½at²（2026-11-25 裁定运动学三式计入 ②），2 分即 ② 初值")
    s.set("B-16-S02", "类", "② 原始方程",
          "批3 §1#5：本步为 0−v²=−2ax（运动学三式），2 分即 ② 初值")
    s.set("B-16-S03", "类", "② 原始方程",
          "T00 裁定 3：含等式 F = mg sinθ + μmg cosθ，主体是方程")
    s.set("B-17-S04", "类", "② 原始方程", "T00 裁定 3：含等式 v_B = v_C cos60°")
    s.set("B-18-S03", "类", "② 原始方程", "T00 裁定 3：含等式 2mg = 2m·v_D²/R")

    # ---------- 批3 · 口径 ----------
    s.sub("B-15-S03", "径",
          "把“恰好到达 B”理解为速度为零而写 v = 0 本步 0 分",
          "把 v_B 取成非零值（如沿用 A→P 段末速）本步 0 分",
          "批3 A 级 #2：题干「由静止下滑、恰好到达 B」→ v_B=0 正是正确判据，原句误杀")
    s.sub("B-18-S03", "径",
          "临界用 mg = mv²/R（漏滑块 3 的质量 2m）本步 0 分",
          "临界用 mg = mv²/R 且未说明 2m 已约去（即漏碰后质量 2m）本步 0 分",
          "批3 A 级 #1：2mg=2mv²/R 两边约 2m 即 mg=mv²/R，同解，原句把等价解判 0")

    # ---------- 批3 · 采分点算式（漏 2m）----------
    s.sub("B-18-S08", "采", "μmg cos37°·L", "μ(2m)g cos37°·L",
          "批3 A 级 #3：EF 段在完全非弹性碰撞之后，质量 2m；"
          "题干 §6 数值自检亦写 ½·2m·v²，摩擦功 0.125 J 而非 0.0625 J")

    # ---------- 批3 · 备注 ----------
    s.app("B-16-S02", "备",
          "类别 ④→②：运动学三式，2 分即 ② 初值（不再算抬分）", "批3 §1#5")
    s.app("B-16-S03", "备",
          "类别 ①→②（T00 裁定 3：主体是等式）；② 初值 2 而本步计 1 分——本题 ② 初值已超卷面，"
          "与 S04 各压 1 分保持合计 12（T00 裁定 1：类别不绑分值）",
          "批3 §7 第 16 条请裁：类别归 ② 会让 ② 超预算")
    s.app("B-16-S04", "备", "② 压到 1 分：初值 2，压 1 分（与 S03 各压 1 分）",
          "批3 §1#5：原表 ② 压分，备注未写")
    s.app("B-17-S04", "备",
          "类别 ①→②（T00 裁定 3）；分值保留 1 分，② 初值 2——压 1 分与 S08 的「①取2」互抵，"
          "合计仍 15（T00 裁定 1：类别不绑分值）",
          "批3 §7 第 16 条")
    s.app("B-17-S08", "备", "①取2：建模类——摩擦路程取半圆周长 2πR 而非位移 4R（T00 2026-11-25 裁定归 ①）",
          "批3 §1#6：① 取 2 分未写理由，按 §3 视为配平违规")
    s.app("B-18-S02", "备", "② 压到 1 分：初值 2，压 1 分。本题初值合计 13 > 卷面 11，超预算 2 分",
          "批3 §4.2：B-18 三处 ② 真压")
    s.app("B-18-S06", "备", "② 压到 1 分：初值 2，压 1 分（同上）", "批3 §4.2")
    s.app("B-18-S07", "备", "② 压到 1 分：初值 2，压 1 分（同上）", "批3 §4.2")
    s.app("B-18-S03", "备",
          "类别 ①→②（T00 裁定 3）；分值保留 1 分，② 初值 2（T00 裁定 1）", "批3 §7 第 16 条")
    s.app("B-18-S08", "备",
          "④ 抬到 2 分：初值 1，抬 1 分。本题初值超卷面 2 分，由 S02/S06/S07 各压 1 分、"
          "本步抬 1 分后净压 2 分", "批3 §4.2：抬分理由须写明")
    s.app("B-15-S02", "备",
          "类别 ④→②（T00 裁定 3：主体是运动学式 d = ½at²）；2 分即 ② 初值，"
          "原表 ④ 取 2 分无条款依据（④ 初值 1）", "批3 §1#7")
    s.app("B-17-S06", "备", "② 回初值 2 分（原 1 分与 S10 成对互换）", "批3 §1#6")
    s.app("B-17-S10", "备", "④ 回初值 1 分（同上）", "批3 §1#6")
    s.app("B-19-S02", "备", "② 回初值 2 分（原 1 分与 S04 成对互换，零代价）", "批3 §1#4")
    s.app("B-19-S04", "备", "④ 回初值 1 分（同上）", "批3 §1#4")
    s.app("B-19-S06", "备", "② 回初值 2 分（原 1 分与 S08 成对互换）", "批3 §1#4")
    s.app("B-19-S08", "备", "④ 回初值 1 分（同上）", "批3 §1#4")
    s.app("B-20-S09", "备",
          "同型合步（一步承载两个独立采分事实，同 A-05-S10）：待整题重拆，本轮不拆"
          "（拆后初期合计超卷面 14 分）", "批3 §1#8")
    s.app("B-20-S10", "备",
          "舍根理由（另一根下 Q 点相对速度向右，与「先到 P 后沿右侧上滑」矛盾）由 T00 复算得出，"
          "源解析未写", "批3 §5：理由须标明来源")


# =====================================================================
# 指标
# =====================================================================
def metrics(s, qs, title):
    print("\n### " + title)
    print(f"{'题':<6}{'卷面':>4}{'步':>4}{'合计':>6}  小问分" + " " * 16 + "②分值占比")
    for q in qs:
        pids = sorted(p for p in s.rows if p.startswith(q + "-S"))
        tot = sum(float(s.get(p, "分")) for p in pids)
        sub = OrderedDict()
        for p in pids:
            k = str(s.ws.cell(s.rows[p], s.I["小问"] + 1).value)
            sub[k] = sub.get(k, 0) + float(s.get(p, "分"))
        two = sum(float(s.get(p, "分")) for p in pids if str(s.get(p, "类")).startswith("②"))
        oral = float(s.ws.cell(s.rows[pids[0]], s.I["卷面分"] + 1).value)
        ssum = " / ".join(f"{k}{v:g}" for k, v in sub.items())
        flag = "" if abs(tot - oral) < 1e-9 else "  **不闭合**"
        if two / tot < 0.30:
            flag += "  **②<30%**"
        print(f"{q:<6}{oral:>4g}{len(pids):>4}{tot:>6g}  {ssum:<24}{two/tot:>8.0%}{flag}")


def verify(s):
    print("\n### 写后校验")
    ok = True
    for q in Q2 + Q3:
        pids = sorted(p for p in s.rows if p.startswith(q + "-S"))
        tot = sum(float(s.get(p, "分")) for p in pids)
        oral = float(s.ws.cell(s.rows[pids[0]], s.I["卷面分"] + 1).value)
        if abs(tot - oral) > 1e-9:
            print(f"  [X] {q} 合计 {tot:g} ≠ 卷面 {oral:g}")
            ok = False
    # 不变式：E-15 只能落在含临界=是 的行，白名单例外见规范 §3 补充五条·五-附
    # 2026-11-25 修正两处（T00）：
    #   ① 原判据写 str(码) == "E-15" —— 整格等值，多码格（"E-15 / E-21"）被静默跳过，
    #      A-06-S01 因此漏检。改为按 / 、 , ， 拆 token 判。
    #   ② 白名单从「待裁 WARN」转为正式豁免（用户 2026-11-25 裁定：留码 + 开豁免）。
    #      物理理由：「板块是否发生相对滑动」本身是临界判断，留码不为了让记账好看而改物理。
    #      代价明写：不变式从「全表适用」降为「全表 + 1 条白名单」。
    E15_EXEMPT = {
        "A-06-S01": "判定「板块间是否发生相对滑动」本身是临界判断；题干 §8 记 含临界=否，"
                    "按规范 §3 补充五条·五-附 豁免（全表唯一）",
    }
    if len(E15_EXEMPT) != 1:
        print(f"  [X] E-15 豁免表应为 1 条，实为 {len(E15_EXEMPT)} 条 —— 白名单不许扩大")
        ok = False
    for p in s.rows:
        codes = [c.strip() for c in re.split(r"[/、,，]", str(s.get(p, "码") or "")) if c.strip()]
        if "E-15" in codes and str(s.get(p, "临界")) != "是":
            if p in E15_EXEMPT:
                print(f"  [OK 豁免] {p} 挂 E-15 且含临界={s.get(p, '临界')}：{E15_EXEMPT[p]}")
            else:
                print(f"  [X] {p} 挂 E-15 但含临界={s.get(p, '临界')}")
                ok = False
    # 反向：豁免行若已改成含临界=是，则该豁免失效，应删除——防止白名单留着给下次开口子
    for p in E15_EXEMPT:
        if p in s.rows and str(s.get(p, "临界")) == "是":
            print(f"  [X] {p} 已在豁免表但含临界已为「是」——豁免失效，请删除该条目")
            ok = False
    # 备注不得为空
    for q in Q2 + Q3:
        for p in [x for x in s.rows if x.startswith(q + "-S")]:
            if not str(s.get(p, "备") or "").strip():
                print(f"  [X] {p} 备注为空")
                ok = False
    print("  校验结果：" + ("全部通过" if ok else "**有失败项，见上**"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    s = Sheet(XLSX)

    if a.verify:
        sys.exit(0 if verify(s) else 1)

    before = {q: sum(float(s.get(p, "分")) for p in s.rows if p.startswith(q + "-S"))
              for q in Q2 + Q3}
    metrics(s, Q2, "改动前 · 批2")
    metrics(s, Q3, "改动前 · 批3")

    apply_all(s)

    if FAILED:
        print("\n### 断言失败（未写盘）")
        for f in FAILED:
            print("  [X] " + f)
        # 硬检测：这批修正会把 B-17-S06 从 1 分改到 2 分。若已是 2 分，说明本表已落过表，
        # 干跑必然全体失败（旧串已被替换）。此时正确动作是 --verify，不是手改断言。
        if str(s.get("B-17-S06", "分")).strip() in ("2", "2.0"):
            print("\n[关键判读] 实测 B-17-S06 已是 2 分 → 本表**已落过表**，"
                  "上述失败是「旧串已被替换」的必然结果，不是数据损坏。")
            print("           请改用：python 采分点/_apply_T24_两批修正.py --verify")
            print("           如确认要重放，先回滚备份再跑干跑。**不要改断言绕过去。**")
        sys.exit(2)

    print(f"\n### 变更清单（共 {len(LOG)} 处）")
    print("| # | point_id | 列 | 动作 | 理由 |")
    print("|---|---|---|---|---|")
    for i, (pid, col, old, new, why) in enumerate(LOG, 1):
        act = f"{old} → {new}"
        act = act.replace("|", "/")
        print(f"| {i} | {pid} | {col} | {act} | {why} |")

    metrics(s, Q2, "改动后 · 批2")
    metrics(s, Q3, "改动后 · 批3")
    after = {q: sum(float(s.get(p, "分")) for p in s.rows if p.startswith(q + "-S"))
             for q in Q2 + Q3}
    moved = [q for q in after if abs(after[q] - before[q]) > 1e-9]
    print("\n### 合计变化：" + ("无（每题闭合不变）" if not moved else str({q: after[q] for q in moved})))

    if a.write:
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        bak = XLSX.with_name(XLSX.stem + f"_备份_{stamp}_两批修正前.xlsx")
        shutil.copy2(XLSX, bak)
        s.wb.save(XLSX)
        print(f"\n[已备份] {bak.name}")
        print(f"[已写入] {XLSX.name}")
        verify(Sheet(XLSX))
    else:
        print("\n（干跑，未写盘。加 --write 落盘）")


if __name__ == "__main__":
    main()
