# -*- coding: utf-8 -*-
"""
T22 · T20 步↔点对齐（粒度审查）

只读输入（§2）：
  1. schema/examples/{q}.json                     金标（66 步 / 96 分）
  2. 评测/T20/out/{q}_validated.json              模型产物（101 步，7 个文件）
  3. 原始资料/五卷力学大题_采分点总表_v2.xlsx      采分点原文与分值
  4. 评测/对齐/对齐说明_20261125.md                T14a 口径经验（只读，不解析）

输出（§4）：
  评测/对齐/T20步点对齐_v2.json   ← 裁定后版本（v1 保留不覆盖）
  评测/对齐/T20对齐_裁定_20261125.md  ← 裁定依据（人读）

幂等：人工判定表内联在本文件 ANNOT 里，重跑不改变输出（含 built_at）。

跑法：
  cd "D:/峤的个人档案/做点东西/物理解题agent"
  python 评测/对齐/_build_t20align.py
"""
import json
import os
import sys
from collections import Counter, OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "评测", "对齐", "T20步点对齐_v2.json")
# v2 = 裁定后版本（见 评测/对齐/T20对齐_裁定_20261125.md）。v1 原样保留，不覆盖。
BUILT_AT = "2026-11-25T18:14:07+08:00"  # v2 首次实跑的真实时刻（mtime 为准），重跑不改，保证幂等

# §9 的执行顺序（同时是 items 的输出顺序）
ORDER = ["B-20", "A-08", "A-02", "B-02", "B-09", "A-10", "B-12"]
EXPECT_STEPS = {"B-20": 17, "A-08": 19, "A-02": 19, "B-02": 12,
                "B-09": 12, "A-10": 12, "B-12": 10}

# ---------------------------------------------------------------- 人工判定表
# 字段：gist 不看金标时写的一句；cls=class；pt=point_id；pts=point_ids(merged)；
#       dup=dup_of；alias；inline；ev=evidence（必须是该步 statement 的逐字子串）；note
ANNOT = OrderedDict()

ANNOT["B-20"] = {
    "steps": OrderedDict([
        ("B-20-S01", dict(gist="判 Q 点弹力只能向下", cls="primary", pt="B-20-S01",
                          ev="轨道对物块的弹力 N 只能向下",
                          note="金标补了「若弹力向上则早已脱离轨道」的反证，模型只给结论")),
        ("B-20-S02", dict(gist="列 Q 点向心方程 N+mg=mv²/R", cls="primary", pt="B-20-S02",
                          ev="N+mg=mv^2/R", note="")),
        ("B-20-S03", dict(gist="代 N=3mg，得 v²=4gR", cls="split", pt="B-20-S02",
                          ev="3mg+mg=mv^2/R", note="金标 S02 把代入并进同一步，模型拆出 S03")),
        ("B-20-S04", dict(gist="求 v=4 m/s", cls="primary", pt="B-20-S03",
                          ev="v=sqrt(4gR)=4 m/s", note="")),
        ("B-20-S05", dict(gist="判低段共速、折点临界、此后相对滑动", cls="primary", pt="B-20-S04",
                          ev="折点 F=4 N、a=2 m/s^2 为刚要相对滑动的临界点",
                          note="同句还读出折点 a=2 m/s²，金标 S04 只登记 F=4 N（额外读数，见说明 §4）")),
        ("B-20-S06", dict(gist="由折点求 M+m=2 kg", cls="split", pt="B-20-S06",
                          ev="M+m=2 kg",
                          note="金标由 k₁=1/(M+m)=0.5 求，模型改走折点 (4 N, 2 m/s²)，同值不同路")),
        ("B-20-S07", dict(gist="高段对轨道列式，由斜率 1/M=1 得 M=1 kg", cls="primary", pt="B-20-S06",
                          ev="斜率 Δa/ΔF=1/M=(6-2)/(8-4)=1，故 M=1 kg",
                          note="斜率读数与金标 k₂=1 同义；该步同时含金标 S05 三条读数里的一条")),
        ("B-20-S08", dict(gist="m=1 kg", cls="split", pt="B-20-S06",
                          ev="得 m=1 kg", note="")),
        ("B-20-S09", dict(gist="折点代入求 μ=0.2", cls="split", pt="B-20-S06",
                          ev="得 μ=0.2",
                          note="金标由截距 b₂=−2 求，模型由折点代入，同值不同路")),
        ("B-20-S10", dict(gist="判 F=8 N 已滑动，并给轨道 6、物块 2", cls="primary", pt="B-20-S07",
                          ev="a_1=(F-μmg)/M=6 m/s^2", inline=True,
                          alias=[dict(gold="a2", model="a_1", why="轨道加速度"),
                                 dict(gold="a1", model="a_2", why="物块加速度")],
                          note="符号互换：金标 a2=轨道、a1=物块，模型 a_1=轨道、a_2=物块；6 与 2 都只在叙述里，无 value 对象（§8 已实测）")),
        ("B-20-S11", dict(gist="相对加速度定 L=2t²", cls="primary", pt="B-20-S08",
                          ev="L=1/2(a_1-a_2)t^2=2t^2",
                          alias=[dict(gold="a2", model="a_1", why="轨道加速度"),
                                 dict(gold="a1", model="a_2", why="物块加速度")],
                          note="走相对加速度，没踩口径里「整体直接用 v²=2aL」的否决项")),
        ("B-20-S12", dict(gist="P 点速度 6t 与 2t", cls="split", pt="B-20-S08",
                          ev="轨道速度 V_P=6t，物块速度 v_P=2t", note="")),
        ("B-20-S13", dict(gist="判水平动量守恒与机械能守恒适用", cls="split", pt="B-20-S09",
                          ev="系统水平动量守恒", note="金标把守恒判断并进 S09 的式子，模型单列一句")),
        ("B-20-S14", dict(gist="列动量守恒 V_Q+7=8t", cls="split", pt="B-20-S09",
                          ev="V_Q+7=6t+2t=8t", note="")),
        ("B-20-S15", dict(gist="列机械能守恒式", cls="split", pt="B-20-S09",
                          ev="1/2(V_P^2+v_P^2)=1/2(V_Q^2+7^2)+mg·2R", note="")),
        ("B-20-S16", dict(gist="解二次方程，按相对速度方向舍 19/6 s", cls="split", pt="B-20-S10",
                          ev="u_rel 应沿切线向左，即 u_rel>0，故舍去 t=19/6 s",
                          note="金标舍根用 v轨′≈18.3>7（物块比轨道慢、相对后退），模型用相对速度方向；判据不同、结论同")),
        ("B-20-S17", dict(gist="L=4.5 m", cls="primary", pt="B-20-S10",
                          ev="L=2×(3/2)^2=9/2 m=4.5 m", note="")),
    ]),
    "points": OrderedDict([
        ("B-20-S01", dict(home="1:1", by=["B-20-S01"], note="")),
        ("B-20-S02", dict(home="1:n", by=["B-20-S02", "B-20-S03"], note="按点聚合可判：方程段 + 代入段")),
        ("B-20-S03", dict(home="1:1", by=["B-20-S04"], note="")),
        ("B-20-S04", dict(home="1:1", by=["B-20-S05"], note="")),
        ("B-20-S05", dict(home="none", by=[],
                          closest="B-20-S07：图乙高段斜率 Δa/ΔF=1/M=(6-2)/(8-4)=1",
                          gap="三条读数只命中 k₂=1 一条；k₁=1/(M+m)=0.5 与 b₂=−2 m/s² 在 17 步里都没出现，模型改由折点 (4 N, 2 m/s²) 求 M+m、由折点代入求 μ。按 §7.3 不硬挂")),
        ("B-20-S06", dict(home="1:n", by=["B-20-S07", "B-20-S06", "B-20-S08", "B-20-S09"],
                          note="四个量拆成四步。表口径「只解出部分量本步 0 分」——任何单步都判 0，必须按点聚合到 M、m、μ 三个量齐全；M=1 落 S07（与金标 value 同量同值）")),
        ("B-20-S07", dict(home="1:1", by=["B-20-S10"], note="6 与 2 均 inline，无 value 对象")),
        ("B-20-S08", dict(home="1:n", by=["B-20-S11", "B-20-S12"], note="L=2t² 与 P 点两速度拆开")),
        ("B-20-S09", dict(home="1:n", by=["B-20-S13", "B-20-S14", "B-20-S15"],
                          note="守恒判断 + 动量式 + 能量式，三步全是 split。口径要求说明 7 m/s 是水平分速度：S14 用「Q 点相对速度沿切线向左 ⇒ 对地速度也向左」交代了方向，等价于说清 Q 点速度水平")),
        ("B-20-S10", dict(home="1:n", by=["B-20-S17", "B-20-S16"], note="舍根论证与 L 值分开")),
    ]),
    "judgment": dict(new_points=[], none_points=["B-20-S05"]),
}

ANNOT["A-08"] = {
    "steps": OrderedDict([
        ("A-08-S01", dict(gist="圆轨道下滑列机械能守恒", cls="split", pt="A-08-S01",
                          ev="只有重力做功，机械能守恒", note="")),
        ("A-08-S02", dict(gist="v_P=6 m/s", cls="primary", pt="A-08-S01",
                          ev="v_P=sqrt(2gR)=6 m/s",
                          alias=[dict(gold="v1", model="vP", why="碰前速度")], note="")),
        ("A-08-S03", dict(gist="P 点径向方程 N−m g=mv²/R", cls="primary", pt="A-08-S02",
                          ev="轨道支持力 N 与重力 m_a g 的合力提供向心力", note="")),
        ("A-08-S04", dict(gist="N=30 N", cls="primary", pt="A-08-S03",
                          ev="N=m_a g+2m_a g=3m_a g=30 N",
                          alias=[dict(gold="Nf", model="N", why="支持力")],
                          note="金标另用牛顿第三定律给出对轨道压力同为 30 N；模型未提第三定律")),
        ("A-08-S05", dict(gist="碰前 v_Ma=3 m/s", cls="primary", pt="A-08-S04",
                          ev="v_Ma=3 m/s，方向向左",
                          alias=[dict(gold="v2", model="vMa", why="a 碰前速度")], note="")),
        ("A-08-S06", dict(gist="弹性正碰求 v_b=2 m/s", cls="primary", pt="A-08-S05",
                          ev="v_b=2m_a u_a/(m_a+m_b)=2 m/s",
                          alias=[dict(gold="v2p", model="vb", why="b 碰后速度")],
                          note="金标同句还算了 a 反弹 1 m/s，模型未算（不单列采分点）；口径的『按完全非弹性取共速』一票否决项未踩")),
        ("A-08-S07", dict(gist="判带向左、b 相对带向左、摩擦力向右", cls="primary", pt="A-08-S06",
                          ev="相对带向左运动，故所受滑动摩擦力向右",
                          note="[R4 裁定] 本点是混合点（金标 kind=value，但口径的两条 0 分条件考的是「判相对方向」与「先减速后共速」）。primary 取判定核心这一步：S07 是唯一不带符号错误的命中；a_b=5 的数值只以 −5 出现（S08），按 §6 反例「符号相反不算同一」，故值侧证据以 split 计。按 R1 修订口径（混合点取「口径 0 分条件考核的那块」），这里无需当例外")),
        ("A-08-S08", dict(gist="a=−5 m/s²、t1=0.2 s", cls="split", pt="A-08-S07",
                          ev="b 在传送带上的加速度为 -μg=-5 m/s²", inline=True,
                          note="金标 S06 的 a_b=5 在此步 inline 出现且符号为负（取左为正）；同一步又给金标 S07 的 t1=0.2 s——一步两用，见说明 §3")),
        ("A-08-S09", dict(gist="s1=0.3 m", cls="split", pt="A-08-S07",
                          ev="s1=(v_b+v0)t1/2=0.3 m", note="")),
        ("A-08-S10", dict(gist="t=3.2 s", cls="primary", pt="A-08-S07",
                          ev="t=t1+(L-s1)/v0=0.2+3.0/1=3.2 s",
                          alias=[dict(gold="t", model="ttotal", why="M→N 总时间")], note="")),
        ("A-08-S11", dict(gist="冲量后 v1=2 m/s 向右", cls="primary", pt="A-08-S08",
                          ev="得 v1=2 m/s，方向向右",
                          alias=[dict(gold="v2b", model="v1", why="冲量后 b 的速度")],
                          note="模型用 v1 记冲量后速度（2），与金标 v1（碰前 6）同名不同物——符号冲突，已列说明 §3")),
        ("A-08-S12", dict(gist="判 Δt=0.6 s 与冲量间隔同步", cls="primary", pt="A-08-S09",
                          ev="经过一个间隔 Δt 时 v=2-5×0.6=-1 m/s，刚好等于带速", inline=True,
                          note="金标 dt=0.6 s 是 value 字段；模型只在式子里写 0.6，无 value 对象（§8 已实测）")),
        ("A-08-S13", dict(gist="每段相对滑程 0.9 m", cls="split", pt="A-08-S11",
                          ev="s_rel=(v1+v0)Δt-Rational(1,2)μgΔt²=(2+1)×0.6-0.5×5×0.6²=0.9 m",
                          note="")),
        ("A-08-S14", dict(gist="每段位移 0.3 m", cls="split", pt="A-08-S10",
                          ev="d1=v1Δt-Rational(1,2)μgΔt²=2×0.6-0.5×5×0.6²=0.3 m", note="")),
        ("A-08-S15", dict(gist="判 10 个整间隔、余 0.3 m", cls="split", pt="A-08-S10",
                          ev="10 个完整间隔后位置 x=10×0.3=3.0 m，仍在传送带上", note="")),
        ("A-08-S16", dict(gist="列末段剩余距离方程", cls="split", pt="A-08-S10",
                          ev="由 v1t_e-Rational(1,2)μg t_e² 等于剩余距离 0.3 m 列方程", note="")),
        ("A-08-S17", dict(gist="解两根取 t_e=0.2 s", cls="split", pt="A-08-S10",
                          ev="两根为 0.2 s 和 0.6 s；b 先向右越过 M 离开传送带，故取较小根 t_e=0.2 s", note="")),
        ("A-08-S18", dict(gist="末段相对滑程 0.5 m", cls="split", pt="A-08-S10",
                          ev="s_e=(v1+v0)t_e-Rational(1,2)μg t_e²=3×0.2-0.5×5×0.2²=0.5 m",
                          note="此值同时被金标 S11 引用（9.5 m 的末段），S11 的 by 里也列本步")),
        ("A-08-S19", dict(gist="Q=95 J", cls="primary", pt="A-08-S11",
                          ev="总热量 Q=Q1+Q2=95 J",
                          alias=[dict(gold="Qheat", model="Q", why="摩擦生热")], note="")),
    ]),
    "points": OrderedDict([
        ("A-08-S01", dict(home="1:n", by=["A-08-S02", "A-08-S01"], note="值 + 守恒式两步")),
        ("A-08-S02", dict(home="1:1", by=["A-08-S03"], note="")),
        ("A-08-S03", dict(home="1:1", by=["A-08-S04"], note="")),
        ("A-08-S04", dict(home="1:1", by=["A-08-S05"], note="")),
        ("A-08-S05", dict(home="1:1", by=["A-08-S06"], note="")),
        ("A-08-S06", dict(home="1:n", by=["A-08-S07", "A-08-S08", "A-08-S09", "A-08-S10"],
                          note="按表口径本点要「判方向 + a_b=5 + 先减速后共速（t₁、x₁、匀速段）」，四件分散在四步；a_b=5 只在 S08 里 inline 且带负号，S07 只判方向")),
        ("A-08-S07", dict(home="1:n", by=["A-08-S10", "A-08-S09", "A-08-S08"],
                          note="t、s1、t1 三步，按点聚合")),
        ("A-08-S08", dict(home="1:1", by=["A-08-S11"], note="")),
        ("A-08-S09", dict(home="1:n", by=["A-08-S12", "A-08-S13", "A-08-S14"],
                          note="按表口径本点要「Δt=0.6 + 对地位移 0.3 向右 + 相对路程 0.9」，三步分别给；拆开看任何单步都不足，合起来齐")),
        ("A-08-S10", dict(home="1:n", by=["A-08-S14", "A-08-S15", "A-08-S16", "A-08-S17", "A-08-S18"],
                          note="周期净位移、整周期数、剩余距离、舍根、末段滑程五步")),
        ("A-08-S11", dict(home="1:n", by=["A-08-S19", "A-08-S13", "A-08-S18"],
                          note="9.5 m 由 S13（10×0.9）与 S18（0.5）拼出，Q 在 S19")),
    ]),
    "judgment": dict(new_points=[], none_points=[]),
}

ANNOT["A-02"] = {
    "steps": OrderedDict([
        ("A-02-S01", dict(gist="读 v–t 图三个时刻的读数", cls="primary", pt="A-02-S01",
                          ev="由图乙读出：t=0时B速度为6/5 v0，A静止",
                          note="一句读了 t=0、t0、2t0 三个时刻；金标 S01 只登记前两条，2t0 的两条分别支撑 S09、S10（见说明 §3）")),
        ("A-02-S02", dict(gist="第一次碰撞前后水平动量守恒", cls="primary", pt="A-02-S02", equiv=True,
                          ev="水平方向系统不受外力，动量守恒",
                          note="[等价形式] 金标写压缩最短共速的 M·1.2v₀=(M+m)v₀；模型写碰后分离的 M·1.2v₀=m·2v₀+M·0.8v₀。两式同解 M=5m，但不是同一物理时刻、字面不等价——照字面匹配会判 0（见说明 §5）")),
        ("A-02-S03", dict(gist="M=5m", cls="primary", pt="A-02-S03",
                          ev="由动量守恒式解得M=5m", note="")),
        ("A-02-S04", dict(gist="判压缩最大时二者共速", cls="split", pt="A-02-S04",
                          ev="弹簧压缩量最大时A、B速度相等",
                          note="金标 S04 的标题是「动能损失＝最大弹性势能」，判定句在 S04 里，模型把它单列成一步")),
        ("A-02-S05", dict(gist="列初动能＝共速动能＋Ep", cls="primary", pt="A-02-S04",
                          ev="初动能等于共速时总动能与弹簧最大弹性势能之和", note="")),
        ("A-02-S06", dict(gist="Ep=3/5 m v0²", cls="primary", pt="A-02-S05",
                          ev="得Ep,max=3/5 m v0^2", note="")),
        ("A-02-S07", dict(gist="判最大压缩量＝s_B−s_A", cls="split", pt="A-02-S08",
                          ev="即x_max=s_B-s_A", note="")),
        ("A-02-S08", dict(gist="质心匀速式＋s_A=9/25 v0t0", cls="merged",
                          pts=["A-02-S06", "A-02-S07"],
                          ev="故t=t0时质心位移为v0t0",
                          note="[R2 裁定标 merged] 金标 S06（判断：质心匀速/面积，2 分）与 S07（方程 m·s_A+5m·s_B=6m·v₀t₀ 解 s_B）登记的是同一条方程；本步一句「质心位移＝v₀t₀＝位移加权平均」同时充当两点的证据，删掉这条方程两点同时塌 → 真合并。风险落在 S06：模型只给「质心匀速」没给「相对简谐」，2 分里可能只拿 1，机械分摊判不出该扣 1 还是 0。S07 另有 S09 独立给值，故 S07 仍为 1:n")),
        ("A-02-S09", dict(gist="s_B=141/125 v0t0", cls="primary", pt="A-02-S07",
                          ev="解得s_B=141/125 v0t0", note="")),
        ("A-02-S10", dict(gist="x_max=96/125 v0t0", cls="primary", pt="A-02-S08",
                          ev="x_max=s_B-s_A=(141/125-9/25)v0t0=96/125 v0t0", note="")),
        ("A-02-S11", dict(gist="由最高点相同判第二次碰后 A 仍 2v0", cls="primary", pt="A-02-S09",
                          ev="说明第二次碰后A沿斜面向上的初速度大小仍为2v0", note="")),
        ("A-02-S12", dict(gist="判碰前 B=4/5v0、A 向左", cls="split", pt="A-02-S10",
                          ev="第二次碰撞前B速度仍为4/5 v0", note="")),
        ("A-02-S13", dict(gist="第二次碰撞动量守恒（A 反向取负）", cls="primary", pt="A-02-S10",
                          ev="设第二次碰前A速度大小为w，方向向左；碰后B速度为u_B",
                          alias=[dict(gold="M", model="5m", why="已代入 M=5m"),
                                 dict(gold="v1", model="w", why="A 第二次碰前速度"),
                                 dict(gold="v2p", model="u_B", why="B 第二次碰后速度")],
                          note="")),
        ("A-02-S14", dict(gist="用相对速度等大反向替代动能守恒", cls="primary", pt="A-02-S11", equiv=True,
                          ev="碰后A、B相对速度与碰前等大反向",
                          note="[等价形式] 金标写动能守恒式（含 ½Mv² 四项）；模型写一维弹性碰撞的等价比（相对速度反向），没有出现任何 ½mv² 项。物理等价，字面命中不了——照字面匹配会判 0")),
        ("A-02-S15", dict(gist="解出 w=v0", cls="primary", pt="A-02-S12",
                          ev="得w=v0",
                          note="金标 S12 要求「并说明另一解不合题意」；按表口径「只给一个解且未说明，给 1 分」，本步仍拿满，不扣")),
        ("A-02-S16", dict(gist="复述滑回速度 v0、声明重力总功为零", cls="meta", pt=None,
                          ev="从滑上到滑回底端，重力总功为零，摩擦力做负功",
                          note="不含独立可判事实：前半复述 S15 结论，后半是 S17/S18 的做功依据")),
        ("A-02-S17", dict(gist="上滑动能定理式", cls="primary", pt="A-02-S13",
                          ev="对第一次上滑过程应用动能定理", note="式含 L 与 μ 两个未知量，靠 S17/S18 联立消 gL")),
        ("A-02-S18", dict(gist="全程能量式（上滑＋下滑合并）", cls="primary", pt="A-02-S14", equiv=True,
                          ev="摩擦力做负功共2μmgLcosθ",
                          note="[等价形式] 金标的下滑式是 mgLsinθ−μmgLcosθ=½mv₀²；模型只写全程式，没有出现「mgLsinθ 正项」。口径说「与上滑式符号相反是采分关键」，本步恰好看不到这个符号结构")),
        ("A-02-S19", dict(gist="μ=9/20=0.45", cls="primary", pt="A-02-S15",
                          ev="解得μ=9/20", note="")),
    ]),
    "points": OrderedDict([
        ("A-02-S01", dict(home="1:1", by=["A-02-S01"], note="")),
        ("A-02-S02", dict(home="1:1", by=["A-02-S02"], note="路径不同（碰后 vs 共速），同解 M=5m")),
        ("A-02-S03", dict(home="1:1", by=["A-02-S03"], note="")),
        ("A-02-S04", dict(home="1:n", by=["A-02-S04", "A-02-S05"], note="判定句 + 能量式")),
        ("A-02-S05", dict(home="1:1", by=["A-02-S06"], note="")),
        ("A-02-S06", dict(home="merged", by=["A-02-S08"],
                          note="[R2 裁定] 唯一承载步 S08 同时承载 S07 的方程 → 部分对无处分摊。模型给了「质心匀速」但没给「相对简谐」，按口径「只说面积不解释给 1 分」，2 分里可能只拿 1；因为与 S07 共用一步，机械分摊判不出该扣 1 还是 0，只能按点整体判")),
        ("A-02-S07", dict(home="1:n", by=["A-02-S09", "A-02-S08"],
                          note="方程在 S08（该步已按 R2 标 merged，同时承载 S06），值在 S09 独立给出 → 本点仍可判，不随 S06 落 merged")),
        ("A-02-S08", dict(home="1:n", by=["A-02-S10", "A-02-S07"], note="")),
        ("A-02-S09", dict(home="1:1", by=["A-02-S11"], note="")),
        ("A-02-S10", dict(home="1:n", by=["A-02-S12", "A-02-S13"], note="")),
        ("A-02-S11", dict(home="1:1", by=["A-02-S14"], note="等价比替代动能式，见 step note")),
        ("A-02-S12", dict(home="1:1", by=["A-02-S15"], note="舍根论证缺失，1 分里可能只拿一半")),
        ("A-02-S13", dict(home="1:1", by=["A-02-S17"], note="")),
        ("A-02-S14", dict(home="1:1", by=["A-02-S18"], note="全程式等价，非同一式")),
        ("A-02-S15", dict(home="1:1", by=["A-02-S19"], note="")),
    ]),
    "judgment": dict(new_points=[], none_points=[]),
}

ANNOT["B-02"] = {
    "steps": OrderedDict([
        ("B-02-S01", dict(gist="判最高点速度为零、取正方向", cls="split", pt="B-02-S01",
                          ev="在最高点瞬时速度为零", note="")),
        ("B-02-S02", dict(gist="列 v0−gt=0", cls="split", pt="B-02-S01",
                          ev="从抛出到最高点有 v0 - g t = 0", note="")),
        ("B-02-S03", dict(gist="v0=gt", cls="primary", pt="B-02-S01",
                          ev="解得 v0 = g t",
                          note="与 S02 同一式子换形，但补出了金标 value 字段要的 v0=gt，判 split 不判 dup")),
        ("B-02-S04", dict(gist="判炸裂瞬间动量守恒、初动量为零", cls="split", pt="B-02-S02",
                          ev="炸裂过程动量守恒；最高点爆炸前总动量为零",
                          note="金标限定「只对水平方向」；模型先说「炸裂过程动量守恒」（未限定方向），S05 才限定水平")),
        ("B-02-S05", dict(gist="水平动量守恒式 2mv+m vBx=0", cls="split", pt="B-02-S03",
                          ev="水平方向动量守恒：2m v + m vBx = 0", note="")),
        ("B-02-S06", dict(gist="vB=2v", cls="primary", pt="B-02-S03",
                          ev="故B的速度大小为 vB = 2v",
                          alias=[dict(gold="v2", model="vB", why="B 的速度")], note="")),
        ("B-02-S07", dict(gist="判二者下落时间相同", cls="split", pt="B-02-S04",
                          ev="二者在竖直方向的运动相同，落地时间相同", note="")),
        ("B-02-S08", dict(gist="H=½g t²", cls="split", pt="B-02-S04",
                          ev="最高点相对地面的高度 H = 1/2 g t^2", note="")),
        ("B-02-S09", dict(gist="T=t", cls="primary", pt="B-02-S04",
                          ev="代入H=1/2gt^2得T=t",
                          alias=[dict(gold="t2", model="T", why="下落时间")], note="")),
        ("B-02-S10", dict(gist="x_A=v t", cls="split", pt="B-02-S05",
                          ev="下落的水平位移 xA = vT = v t", note="")),
        ("B-02-S11", dict(gist="x_B=2v t", cls="split", pt="B-02-S05",
                          ev="下落的水平位移 xB = 2vT = 2v t", note="")),
        ("B-02-S12", dict(gist="d=3vt", cls="primary", pt="B-02-S06",
                          ev="距离 d = xA + xB = 3v t", note="「两侧相加」在「位于最高点正下方的两侧」里")),
    ]),
    "points": OrderedDict([
        ("B-02-S01", dict(home="1:n", by=["B-02-S03", "B-02-S02", "B-02-S01"], note="三步：判定、方程、解")),
        ("B-02-S02", dict(home="1:n", by=["B-02-S04", "B-02-S05"],
                          note="S04 未限定方向，只有 S05 限定水平；金标「竖直方向成对抵消」的论证缺失")),
        ("B-02-S03", dict(home="1:n", by=["B-02-S06", "B-02-S05"], note="")),
        ("B-02-S04", dict(home="1:n", by=["B-02-S09", "B-02-S07", "B-02-S08"], note="")),
        ("B-02-S05", dict(home="1:n", by=["B-02-S10", "B-02-S11"],
                          note="模型没写合并式 s₁+s₂=(v+v₂)t，只分别给 x_A、x_B")),
        ("B-02-S06", dict(home="1:1", by=["B-02-S12"], note="")),
    ]),
    "judgment": dict(new_points=[], none_points=[]),
}

ANNOT["B-09"] = {
    "steps": OrderedDict([
        ("B-09-S01", dict(gist="由速度位移关系求 v1=0.3", cls="primary", pt="B-09-S02",
                          ev="由速度—位移关系 v1^2-v0^2=-2μg s1 求 v1",
                          note="模型把 a=μg 直接写进式里，没有独立的 a=μg 步（金标 S01 单独 2 分）")),
        ("B-09-S02", dict(gist="等质量正碰求乙 v2=0.2", cls="primary", pt="B-09-S03",
                          ev="有 m v1=m v_after+m v2，解得乙碰后速度 v2",
                          alias=[dict(gold="v1p", model="v_after", why="甲碰后速度")], note="")),
        ("B-09-S03", dict(gist="求乙滑行距离 0.02 m", cls="split", pt="B-09-S04",
                          ev="从碰后到速度减为零的最大滑行距离 L 满足 0-v2^2=-2μgL", note="")),
        ("B-09-S04", dict(gist="判 L=s2，刚好到达边框 a", cls="primary", pt="B-09-S04",
                          ev="故乙速度恰减到零时刚好到达边框a，能够滑动到边框a", note="")),
        ("B-09-S05", dict(gist="列 a=μg", cls="primary", pt="B-09-S01",
                          ev="由牛顿第二定律得 a=μg",
                          note="金标强调甲、乙相同；模型只对甲写，乙在 S03 里另写「加速度大小为 μg」")),
        ("B-09-S06", dict(gist="a=1 m/s²", cls="split", pt="B-09-S01",
                          ev="得 a=1 m/s^2", note="")),
        ("B-09-S07", dict(gist="碰前段 v0−v1=a t1", cls="split", pt="B-09-S06",
                          ev="由 v0-v1=a t1 列式", note="")),
        ("B-09-S08", dict(gist="t1=0.1 s", cls="primary", pt="B-09-S06",
                          ev="得 t1=0.1 s", note="")),
        ("B-09-S09", dict(gist="碰后段 v_after−a t2=0", cls="split", pt="B-09-S07",
                          ev="由 v_after-a t2=0 列式", note="")),
        ("B-09-S10", dict(gist="t2=0.1 s", cls="split", pt="B-09-S07",
                          ev="得 t2=0.1 s", note="")),
        ("B-09-S11", dict(gist="T=t1+t2", cls="split", pt="B-09-S07",
                          ev="总时间等于碰前运动时间与碰后运动时间之和，即 T=t1+t2", note="")),
        ("B-09-S12", dict(gist="T=0.2 s", cls="primary", pt="B-09-S07",
                          ev="得 T=0.2 s", note="")),
    ]),
    "points": OrderedDict([
        ("B-09-S01", dict(home="1:n", by=["B-09-S05", "B-09-S06", "B-09-S03"],
                          note="表口径「只对甲或只对乙列式给 1 分」：模型对甲在 S05 列式，对乙在 S03 里写「加速度大小为 μg」，两边都有，可拿满；值 a=1 在 S06")),
        ("B-09-S02", dict(home="1:1", by=["B-09-S01"], note="")),
        ("B-09-S03", dict(home="1:1", by=["B-09-S02"], note="")),
        ("B-09-S04", dict(home="1:n", by=["B-09-S04", "B-09-S03"], note="算距离 + 比边框")),
        ("B-09-S05", dict(home="1:n", by=["B-09-S07", "B-09-S09", "B-09-S11"],
                          note="模型没写「甲分两段」这句判定，而用碰前段（S07）、碰后段（S09）、总时间＝两段之和（S11）把结构显式化——结构隐含型，见卡面缺口 §2")),
        ("B-09-S06", dict(home="1:n", by=["B-09-S08", "B-09-S07"], note="")),
        ("B-09-S07", dict(home="1:n", by=["B-09-S12", "B-09-S10", "B-09-S09", "B-09-S11"], note="四步拼出总时间")),
    ]),
    "judgment": dict(new_points=[], none_points=[]),
}

ANNOT["A-10"] = {
    "steps": OrderedDict([
        ("A-10-S01", dict(gist="判球外等效于中心集中质量", cls="split", pt="A-10-S01",
                          ev="球内物质对球外恒星的引力等效于全部质量 M 集中在星系中心",
                          note="即金标 S01「引力只由球内总质量 M 提供」的依据")),
        ("A-10-S02", dict(gist="列 GMm/r²=mv²/r", cls="primary", pt="A-10-S01",
                          ev="r>R 处万有引力提供向心力，列方程 GMm/r^2=mv^2/r",
                          alias=[dict(gold="Gc", model="G", why="引力常量，全题统一改名")], note="")),
        ("A-10-S03", dict(gist="v=√(GM/r)", cls="primary", pt="A-10-S02",
                          ev="得 v^2=GM/r，因此 v=sqrt(GM/r)",
                          alias=[dict(gold="Gc", model="G", why="引力常量")], note="")),
        ("A-10-S04", dict(gist="M(r)=M r³/R³", cls="primary", pt="A-10-S03",
                          ev="M(r)=M*r^3/R^3",
                          alias=[dict(gold="M0", model="M(r)", why="半径 r 内的质量")], note="")),
        ("A-10-S05", dict(gist="球内向心方程（用 M(r)）", cls="primary", pt="A-10-S04",
                          ev="列向心力方程 G*M(r)*m/r^2=mv^2/r",
                          alias=[dict(gold="M0", model="M(r)", why="半径 r 内的质量")], note="")),
        ("A-10-S06", dict(gist="得 v²=GMr²/R³ 与 v=r√(GM/R³)", cls="primary", pt="A-10-S05",
                          ev="得 v^2=GM*r^2/R^3，即 v=r*sqrt(GM/R^3)",
                          note="同一步也给出金标 S04 的代入结果，S04 记 1:n")),
        ("A-10-S07", dict(gist="判 r>R 速度几乎不变，取 v(nR)≈v(R)", cls="primary", pt="A-10-S06",
                          ev="r>R 区域恒星速度大小几乎不变，因此取 v(nR)≈v(R)",
                          note="金标 S06 还含 v₀²=GcM/R；模型把它放在 S08")),
        ("A-10-S08", dict(gist="v_R²=GM/R", cls="split", pt="A-10-S06",
                          ev="得 v_R^2=GM/R",
                          alias=[dict(gold="v0", model="v_R", why="R 处速率")], note="")),
        ("A-10-S09", dict(gist="判 nR 内含暗物质，等效质量 M+M′", cls="split", pt="A-10-S07",
                          ev="等效中心总质量为 M+M′", note="")),
        ("A-10-S10", dict(gist="nR 处列向心力", cls="split", pt="A-10-S07",
                          ev="对 r=nR 处恒星列万有引力提供向心力",
                          alias=[dict(gold="v0", model="v_n", why="nR 处速率")], note="")),
        ("A-10-S11", dict(gist="联立恒速条件", cls="primary", pt="A-10-S07",
                          ev="由 v_n≈v_R 且 v_R^2=GM/R，代入得 G(M+M′)/(nR)=GM/R", note="")),
        ("A-10-S12", dict(gist="M′=(n−1)M", cls="primary", pt="A-10-S08",
                          ev="(n-1)M", note="")),
    ]),
    "points": OrderedDict([
        ("A-10-S01", dict(home="1:n", by=["A-10-S02", "A-10-S01"], note="球壳定理 + 方程")),
        ("A-10-S02", dict(home="1:1", by=["A-10-S03"], note="")),
        ("A-10-S03", dict(home="1:1", by=["A-10-S04"], note="")),
        ("A-10-S04", dict(home="1:n", by=["A-10-S05", "A-10-S06"], note="方程 + 代入结果")),
        ("A-10-S05", dict(home="1:1", by=["A-10-S06"], note="")),
        ("A-10-S06", dict(home="1:n", by=["A-10-S07", "A-10-S08"], note="恒速判断 + v₀ 关系")),
        ("A-10-S07", dict(home="1:n", by=["A-10-S11", "A-10-S10", "A-10-S09", "A-10-S08"],
                          note="表口径「只写一处方程 0 分」：R 处方程在 S08（v_R²=GM/R，即两边除 R），nR 处在 S10，联立在 S11，三步齐才给满")),
        ("A-10-S08", dict(home="1:1", by=["A-10-S12"], note="")),
    ]),
    "judgment": dict(new_points=[], none_points=[]),
}

ANNOT["B-12"] = {
    "steps": OrderedDict([
        ("B-12-S01", dict(gist="整体法列 N1=(m+M)g", cls="primary", pt="B-12-S01",
                          ev="把滑块和滑杆看成一个整体",
                          note="同一步的方程也是金标 S02 的式子，S02 的 by 里也列本步")),
        ("B-12-S02", dict(gist="N1=8 N", cls="primary", pt="B-12-S02",
                          ev="得 N1=8 N", note="equation 字段照抄 S01，若只看该字段会误判 dup；实为取值步")),
        ("B-12-S03", dict(gist="判杆受摩擦力向上、隔离杆列式", cls="primary", pt="B-12-S03",
                          ev="滑杆受到的摩擦力向上；滑杆仍静止，对其竖直方向列平衡方程 N2+f=Mg", note="")),
        ("B-12-S04", dict(gist="N2=5 N", cls="primary", pt="B-12-S04",
                          ev="得 N2=5 N", note="")),
        ("B-12-S05", dict(gist="A→B 动能定理式", cls="primary", pt="B-12-S05",
                          ev="重力和摩擦力均做负功，由动能定理列式",
                          note="S05/S06 对应金标「列式 2 分 + 结果 1 分」两步")),
        ("B-12-S06", dict(gist="v1=8 m/s", cls="primary", pt="B-12-S06",
                          ev="解得滑块碰撞前速度大小 v1=8 m/s，方向向上",
                          note="金标 S05 的 value 字段也登记 v1=8，本步同时是 S05、S06 的证据（金标侧重复，见卡面缺口 §1）")),
        ("B-12-S07", dict(gist="完全非弹性碰撞动量守恒", cls="split", pt="B-12-S07",
                          ev="系统在竖直方向动量近似守恒；碰后完全非弹性",
                          note="用 v 记共同速度，没踩口径里的「把碰后速度写成 v₁」一票否决项")),
        ("B-12-S08", dict(gist="v=2 m/s", cls="primary", pt="B-12-S07",
                          ev="得碰后共同速度 v=2 m/s",
                          alias=[dict(gold="vc", model="v", why="碰后共同速度")], note="")),
        ("B-12-S09", dict(gist="列 ½(m+M)v²=(m+M)gh", cls="primary", pt="B-12-S08",
                          ev="由机械能守恒或运动学公式列最大高度方程",
                          note="[附录 A 裁定，v1 误标已撤] 金标写 v_c²=2gh；模型写 ½(m+M)v²=(m+M)gh，两边同除 (m+M) 再乘 2 即同式——属卡面 §6.2 明列的「两边同除」，本来就是代数等价，不该打 equiv_form 特批")),
        ("B-12-S10", dict(gist="h=0.2 m", cls="primary", pt="B-12-S09",
                          ev="得滑杆向上运动的最大高度 h=0.2 m", note="")),
    ]),
    "points": OrderedDict([
        ("B-12-S01", dict(home="1:1", by=["B-12-S01"], note="")),
        ("B-12-S02", dict(home="1:n", by=["B-12-S02", "B-12-S01"], note="方程在 S01、值在 S02")),
        ("B-12-S03", dict(home="1:1", by=["B-12-S03"], note="")),
        ("B-12-S04", dict(home="1:1", by=["B-12-S04"], note="")),
        ("B-12-S05", dict(home="1:n", by=["B-12-S05", "B-12-S06"],
                          note="金标 S05 的 value 也记 v1=8，与 S06 重复；模型 S06 同时是两点证据")),
        ("B-12-S06", dict(home="1:1", by=["B-12-S06"], note="")),
        ("B-12-S07", dict(home="1:n", by=["B-12-S08", "B-12-S07"], note="方程 + 值")),
        ("B-12-S08", dict(home="1:1", by=["B-12-S09"], note="")),
        ("B-12-S09", dict(home="1:1", by=["B-12-S10"], note="")),
    ]),
    "judgment": dict(new_points=[], none_points=[]),
}


# ---------------------------------------------------------------- 读输入
def load_json(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


def load_scores():
    import openpyxl
    wb = openpyxl.load_workbook(os.path.join(ROOT, "原始资料", "五卷力学大题_采分点总表_v2.xlsx"),
                                data_only=True)
    ws = wb["采分点总表"]
    out = OrderedDict()
    for row in ws.iter_rows(min_row=2, values_only=True):
        pid = row[0]
        if not pid:
            continue
        out[pid] = dict(score=row[8], text=row[7], judge=row[9])
    return out


def main():
    scores = load_scores()
    gold = {q: load_json(f"schema/examples/{q}.json") for q in ORDER}
    model = {q: load_json(f"评测/T20/out/{q}_validated.json") for q in ORDER}

    errors = []
    items = []

    for q in ORDER:
        gsteps = gold[q]["steps"]
        msteps = model[q]["steps"]
        assert len(msteps) == EXPECT_STEPS[q], (q, len(msteps))

        ann = ANNOT[q]
        gmap = {s["step_id"]: s for s in gsteps}
        mmap = {s["step_id"]: s for s in msteps}

        # 覆盖：人工表与模型步一一对应
        if set(ann["steps"]) != set(mmap):
            errors.append(f"[{q}] 人工表步集与模型步不一致：多 {set(ann['steps'])-set(mmap)}，缺 {set(mmap)-set(ann['steps'])}")
        if set(ann["points"]) != set(gmap):
            errors.append(f"[{q}] 人工表点集与金标不一致：多 {set(ann['points'])-set(gmap)}，缺 {set(gmap)-set(ann['points'])}")

        # 组 steps
        out_steps = []
        for s in sorted(msteps, key=lambda x: x["step_no"]):
            a = ann["steps"][s["step_id"]]
            ev = a["ev"]
            if ev not in s["statement"]:
                errors.append(f"[{q}] evidence 不是逐字子串：{s['step_id']} :: {ev!r}")
            out_steps.append(OrderedDict([
                ("step_id", s["step_id"]),
                ("step_no", s["step_no"]),
                ("kind", s["kind"]),
                ("gist", a["gist"]),
                ("class", a["cls"]),
                ("point_id", a.get("pt")),
                ("point_ids", a.get("pts")),
                ("dup_of", a.get("dup")),
                ("alias", a.get("alias", [])),
                ("inline_only", bool(a.get("inline", False))),
                ("equiv_form", bool(a.get("equiv", False))),
                ("evidence", ev),
                ("note", a.get("note", "")),
            ]))

        # 组 points
        out_points = []
        for s in gsteps:
            pid = s["step_id"]
            a = ann["points"][pid]
            out_points.append(OrderedDict([
                ("point_id", pid),
                ("score", scores[pid]["score"]),
                ("home", a["home"]),
                ("by", a["by"]),
                ("note", a.get("note", "")),
                ("closest", a.get("closest")),
                ("gap", a.get("gap")),
            ]))

        none_list = [dict(point_id=p["point_id"], closest=p["closest"], gap=p["gap"])
                     for p in out_points if p["home"] == "none"]

        items.append(OrderedDict([
            ("qid", q),
            ("gold_steps", len(gsteps)),
            ("model_steps", len(msteps)),
            ("steps", out_steps),
            ("points", out_points),
            ("judgment", OrderedDict([
                ("new_points", ann["judgment"]["new_points"]),
                ("none_points", none_list),
            ])),
        ]))

    doc = OrderedDict([
        ("meta", OrderedDict([
            ("built_at", BUILT_AT),
            ("revision", "v2（T20 对齐裁定后：R1 口径修订 / R2 A-02-S08 标 merged / 附录A 撤 B-12-S09 误标）"),
            ("rulings", "评测/对齐/T20对齐_裁定_20261125.md"),
            ("gold_steps", sum(len(gold[q]["steps"]) for q in ORDER)),
            ("model_steps", sum(len(model[q]["steps"]) for q in ORDER)),
            ("script", "评测/对齐/_build_t20align.py"),
            ("order", ORDER),
        ])),
        ("items", items),
    ])

    # ------------------------------------------------ §10 断言
    report = []

    # 1 覆盖
    all_sid = [s["step_id"] for it in items for s in it["steps"]]
    all_pid = [p["point_id"] for it in items for p in it["points"]]
    assert len(all_sid) == 101, len(all_sid)
    assert len(set(all_sid)) == 101, "step_id 有重复"
    assert len(all_pid) == 66 and len(set(all_pid)) == 66, (len(all_pid), len(set(all_pid)))
    report.append(f"[1 覆盖] step_id={len(all_sid)} 唯一={len(set(all_sid))}｜point_id={len(all_pid)} 唯一={len(set(all_pid))}｜通过")

    # 2 算术自洽
    tot = Counter()
    line2 = []
    for it in items:
        c = Counter(s["class"] for s in it["steps"])
        h = Counter(p["home"] for p in it["points"])
        s_sum = sum(c.values())
        p_sum = sum(h.values())
        ok1 = s_sum == it["model_steps"]
        ok2 = p_sum == it["gold_steps"]
        # R2 裁定：每个 merged 步至少要承载 1 个 home=merged 的点
        # （原卡 §10.2 要求「撑起 ≥2 个」，会把「一步合并两点、其中一点另有下游步」
        #   的形状逼成不敢报，merged 这一格永远是 0；真危险是「有一个点的部分对无处分摊」，
        #   不是「所有点都无处分摊」。见 评测/对齐/T20对齐_裁定_20261125.md R2）
        merged_ok = True
        if c["merged"]:
            hmg_ids = {p["point_id"] for p in it["points"] if p["home"] == "merged"}
            for s in it["steps"]:
                if s["class"] != "merged":
                    continue
                if not (set(s["point_ids"] or []) & hmg_ids):
                    merged_ok = False
                    errors.append(f"[{it['qid']}] {s['step_id']} 标了 merged 却没让任何一个它承载的点落入 home=merged")
        line2.append(f"{it['qid']}: 步 {it['model_steps']}=p{c['primary']}+s{c['split']}+m{c['merged']}+d{c['dup']}+n{c['new']}+x{c['meta']}"
                     f" {'OK' if ok1 else 'FAIL'}｜点 {it['gold_steps']}=1:1 {h['1:1']}+1:n {h['1:n']}+mg {h['merged']}+none {h['none']}"
                     f" {'OK' if ok2 else 'FAIL'}｜merged↔home {c['merged']}/{h['merged']}（每步≥1） {'OK' if merged_ok else 'FAIL'}")
        if not (ok1 and ok2 and merged_ok):
            errors.append(f"[{q}] 算术不自洽: {line2[-1]}")
        tot.update(c)
        for k, v in h.items():
            tot["home_" + k] += v
    report.append("[2 算术] " + line2[0])
    for l in line2[1:]:
        report.append("         " + l)
    report.append(f"         合计: 步 {sum(tot[k] for k in ['primary','split','merged','dup','new','meta'])}"
                  f"（p{tot['primary']}+s{tot['split']}+m{tot['merged']}+d{tot['dup']}+n{tot['new']}+x{tot['meta']}）"
                  f"｜点 {sum(v for k,v in tot.items() if k.startswith('home_'))}"
                  f"（1:1 {tot['home_1:1']} / 1:n {tot['home_1:n']} / merged {tot['home_merged']} / none {tot['home_none']}）")

    # 3 必填 + 跨引用
    for it in items:
        gids = {p["point_id"] for p in it["points"]}
        sids = {s["step_id"] for s in it["steps"]}
        for s in it["steps"]:
            if s["class"] in ("primary", "split"):
                if s["point_id"] not in gids:
                    errors.append(f"[{it['qid']}] {s['step_id']} point_id 不在金标：{s['point_id']}")
                if s["point_ids"]:
                    errors.append(f"[{it['qid']}] {s['step_id']} 非 merged 却填了 point_ids")
            elif s["class"] == "merged":
                ids = s["point_ids"] or []
                if len(ids) < 2 or len(set(ids)) != len(ids) or any(i not in gids for i in ids):
                    errors.append(f"[{it['qid']}] {s['step_id']} merged.point_ids 不合法：{ids}")
            elif s["class"] == "dup":
                if s["dup_of"] not in sids or s["dup_of"] == s["step_id"]:
                    errors.append(f"[{it['qid']}] {s['step_id']} dup_of 不合法：{s['dup_of']}")
            elif s["class"] == "new":
                if not s["note"]:
                    errors.append(f"[{it['qid']}] {s['step_id']} new 缺 note")
            elif s["class"] == "meta":
                pass
            else:
                errors.append(f"[{it['qid']}] {s['step_id']} 未知 class：{s['class']}")
        # by 里的步必须存在
        for p in it["points"]:
            for b in p["by"]:
                if b not in sids:
                    errors.append(f"[{it['qid']}] {p['point_id']} by 引用了不存在的步 {b}")
            if p["home"] != "none" and not p["by"]:
                errors.append(f"[{it['qid']}] {p['point_id']} home={p['home']} 但 by 为空")
    report.append(f"[3 必填] primary/split 单点、merged ≥2 点、dup 指向本题他步、by 引用存在｜错误 {len([e for e in errors if 'point_id' in e or 'merged' in e or 'dup_of' in e or 'by' in e])} 条")

    # 4 证据逐字（已在组装时断言，这里复核计数）
    n_ev = sum(1 for it in items for s in it["steps"] if s["evidence"])
    report.append(f"[4 逐字] evidence 总数 {n_ev}／步数 101，全部为 statement 子串｜通过")

    # 5 none 有交代
    n_none = 0
    for it in items:
        for p in it["points"]:
            if p["home"] == "none":
                n_none += 1
                if not p["closest"] or not p["gap"]:
                    errors.append(f"[{it['qid']}] {p['point_id']} none 缺 closest/gap")
    report.append(f"[5 none] none 点 {n_none} 个，均带 closest+gap｜通过")

    # 6 new 有内容
    n_new = 0
    for it in items:
        for s in it["steps"]:
            if s["class"] == "new":
                n_new += 1
                if len(s["note"]) < 6:
                    errors.append(f"[{it['qid']}] {s['step_id']} new 的 note 太短")
    report.append(f"[6 new] new 步 {n_new} 个（0 个即无补点候选）｜通过")

    if errors:
        print("\n".join(report))
        print("\n!!! 断言失败")
        for e in errors:
            print("  - " + e)
        sys.exit(1)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")

    print("\n".join(report))
    print(f"\n写出 {os.path.relpath(OUT, ROOT)}  ({os.path.getsize(OUT)} bytes)")
    # §11 三个结论的原始数字
    print(f"[§11-1] 补点候选 new = {tot['new']}")
    print(f"[§11-2] 冗余率 = (dup {tot['dup']} + meta {tot['meta']}) / 101 = {(tot['dup']+tot['meta'])/101:.4f}")
    print(f"[§11-3] home: 1:1 {tot['home_1:1']} / 1:n {tot['home_1:n']} / merged {tot['home_merged']} / none {tot['home_none']} （合计 66）")

    # 附加口径统计（说明 §3/§5 用）
    cross = []
    for it in items:
        cnt = Counter()
        for p in it["points"]:
            for b in p["by"]:
                cnt[b] += 1
        for sid, n in cnt.items():
            if n > 1:
                cross.append((it["qid"], sid, n))
    print(f"[跨点复用] 被 >=2 个点同时引用的模型步 {len(cross)} 个：" +
          "、".join(f"{q}/{s}({n}点)" for q, s, n in cross))
    ali = [(it["qid"], s["step_id"], a) for it in items for s in it["steps"] for a in s["alias"]]
    print(f"[alias] {len(ali)} 条：" + "、".join(f"{q}/{s}:{a['gold']}→{a['model']}" for q, s, a in ali))
    inl = [(it["qid"], s["step_id"]) for it in items for s in it["steps"] if s["inline_only"]]
    print(f"[inline_only] {len(inl)} 条：" + "、".join(f"{q}/{s}" for q, s in inl))
    eqv = [(it["qid"], s["step_id"], s["point_id"]) for it in items for s in it["steps"] if s["equiv_form"]]
    print(f"[等价形式] {len(eqv)} 条：" + "、".join(f"{q}/{s}→{p}" for q, s, p in eqv))


if __name__ == "__main__":
    main()
