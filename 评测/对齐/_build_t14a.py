# -*- coding: utf-8 -*-
"""T14a 构建器：把 6 条模型错答切成段并对齐到金标步号。

切段方式：按 raw content 的行号区间取子串（"\\n".join(lines[a:b])），
保证 quote 必然是原文逐字子串，不做任何改写。
运行：python 评测/对齐/_build_t14a.py
"""
import json
import os
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "评测", "对齐", "model_answers_v1.json")


def S(a, b, step, role, conf, note, inv=False):
    return dict(a=a, b=b, step=step, role=role, conf=conf, note=note, inv=inv)


def U(a, b, reason):
    return dict(a=a, b=b, reason=reason)


ITEMS = [
    # ------------------------------------------------------------------ A-09 / v1
    dict(
        qid="A-09", variant="v1", failure_type="calc",
        segs=[
            S(0, 1, None, "setup", "high",
              "开头一句声明研究对象（小球）与初始、断绳两处几何位置，按 role=setup 不挂步。"
              "它把初始悬挂点放在 N 正下方（绳子一开始就绕过 N），后文所有高度差都由此推出。"),
            S(2, 6, None, "setup", "high",
              "题干给定量的重述（L、m、v₀、g），不承担采分点。"),
            S(8, 12, "A-09-S02", "judgment", "high",
              "该高度差正是金标 S02 守恒式里重力项所对应的高度。金标取断绳点距地 2L、初始在地面（Δh=2L）；"
              "此处按上一段几何取 Δh=2L−L=L。"),
            S(12, 16, "A-09-S02", "equation", "high",
              "与金标 S02 同一守恒式，仅重力项写成 mgL（随上段 Δh 取法）。"),
            S(16, 19, "A-09-S03", "equation", "high",
              "S03 的中间量 v²=90；金标由 2L 得 v²=80。"),
            S(19, 22, "A-09-S03", "value", "high",
              "v=3√10≈9.49 m/s；金标 4√5≈8.94 m/s。"),
            S(23, 24, "A-09-S04", "judgment", "high",
              "为 S04 径向方程提供前提（圆周最低点张力最大）。金标 S01 的半径序列（3L→2L→L）在此未展开，"
              "题干已直接给出断绳点位置。"),
            S(24, 27, "A-09-S04", "equation", "high",
              "与金标 S04 同一径向式 F_T−mg=mv²/L。"),
            S(27, 31, "A-09-S04", "value", "high",
              "T_max=19 N；金标 17 N。"),
            S(33, 37, "A-09-S05", "judgment", "high",
              "平抛的竖直高度，属 S05 分解式的前提；金标取断绳点距地 2L，此处取 h=L=0.5 m。"),
            S(37, 43, "A-09-S05", "equation", "high",
              "与金标 S05 同一竖直分式 2h=½gt²（h 取法见上段）。"),
            S(43, 47, "A-09-S06", "value", "high",
              "x=3 m；金标 4 m。"),
            S(49, 53, "A-09-S07", "equation", "high",
              "与金标 S07 同一临界式：金标记作 mg=mv₂²/(2L)，临界位置在 N 正上方、半径 2L。"),
            S(53, 56, "A-09-S07", "value", "high",
              "临界速度平方 v₁²=10；金标未单列此中间量，S08 直接代入。"),
            S(56, 60, "A-09-S08", "judgment", "high",
              "该高度差对应金标 S08 守恒式的重力项。金标取 N 正上方距地 5L；此处取升高 4L"
              "（承接第 1 段把地面定在 M 下方 2L 处）。"),
            S(60, 64, "A-09-S08", "equation", "high",
              "与金标 S08 同一守恒式，重力项为 mg·4L。"),
            S(64, 68, "A-09-S09", "equation", "high",
              "S09 的中间量 v_min²=50；金标 60。"),
            S(68, 71, "A-09-S09", "value", "high",
              "v_min=5√2≈7.07 m/s；金标 2√15≈7.75 m/s。"),
        ],
        unal=[
            U(74, 97,
              "重复：最终答案汇总，四个结果与正文同值（末项另给了 7.07 的近似值），无新增过程。"),
        ],
    ),
    # ------------------------------------------------------------------ B-17 / v1
    dict(
        qid="B-17", variant="v1", failure_type="calc",
        segs=[
            S(0, 1, None, "setup", "high",
              "只声明研究对象的质量符号，不承担采分点。"),
            S(4, 5, "B-17-S01", "judgment", "high",
              "与金标 S01 同一判断：恰好通过最高点 ⇒ 轨道弹力为零，仅重力提供向心力。"),
            S(5, 8, "B-17-S02", "equation", "high",
              "与金标 S02 同一式 mg=mv_D²/R。"),
            S(8, 17, "B-17-S03", "value", "high",
              "「因此…」到「答：」给的是同一结果 v_D=√(gR)。金标 S02 的结论即此式，S03 只要求结果用 g、R 表示（1 分），"
              "故这段挂 S03，S02 由上一段方程承担，避免同一式重复计入。"),
            S(22, 26, "B-17-S05", "judgment", "high",
              "该高度差进入 S05 的守恒式。金标取 C 点在 D 下方 R+Rcos60°=3R/2；此处取 R−Rcos60°=R/2。"),
            S(27, 31, "B-17-S05", "equation", "high",
              "与金标 S05 同一守恒式，h_CD 取法见上段。"),
            S(31, 39, "B-17-S05", "value", "high",
              "v_C=√(2gR)；金标 v_C=2√(gR)。"),
            S(40, 44, "B-17-S04", "judgment", "high",
              "与金标 S04 同一判断（沿切线进入 ⇒ 水平分速度 v_B=v_C cos60°），并把这式一并写出。"),
            S(44, 55, "B-17-S06", "equation", "low",
              "金标 S06 走 B→D 的能量式 mgH_BD=½mv_D²−½mv_B²；此处改走平抛运动学，先求 h_BC。"
              "所求量同为 H_BD，故挂 S06 但置信度降为 low。"),
            S(55, 68, "B-17-S07", "value", "high",
              "H_BD=R/4（B 比 D 高）；金标 S07 为 0（B 与 D 等高）。"),
            S(73, 81, "B-17-S09", "equation", "low",
              "为 S09 的动能定理准备 v_B²；金标该步直接以 v_B 代入，无独立中间式，故置信度 low。"),
            S(82, 86, "B-17-S08", "judgment", "high",
              "与金标 S08 同一判断：摩擦路程取半个圆周长 2πR，不是位移 4R。"),
            S(86, 90, None, "setup", "high",
              "题干已给 μ=1/(2π)，此处为重述，不承担采分点。"),
            S(90, 96, "B-17-S09", "equation", "high",
              "与金标 S09 同一摩擦功（金标写作 −μmg·2πR，此处取正号大小 W_f=mgR）。"),
            S(97, 101, "B-17-S09", "equation", "high",
              "与金标 S09 同一动能定理式，仅移项方向相反。"),
            S(101, 107, "B-17-S10", "equation", "high",
              "S10 的中间量 v_A²=5gR/2；金标 3gR。"),
            S(107, 120, "B-17-S10", "value", "high",
              "v_A=√(5gR/2)；金标 √(3gR)。「也可写为」是同一值的另一种形式。"),
        ],
        unal=[
            U(123, 139,
              "重复：最终答案汇总，三问结果与正文同值；末句只是单位说明。"),
        ],
    ),
    # ------------------------------------------------------------------ B-15 / v2
    dict(
        qid="B-15", variant="v2", failure_type="calc",
        segs=[
            S(0, 5, None, "setup", "high",
              "过程划分与研究对象声明，不承担采分点。"),
            S(5, 6, "B-15-S03", "judgment", "high",
              "与金标 S03 同一判断：P→B 恰好到达 ⇒ 该段合功为零。金标由此推出「A→B 到 B 的速度与 A→P 到 P 时相同」；"
              "此处改用「A→B 与 P→B 的净功之差」表达同一结论（见下方 S04 段）。"),
            S(10, 14, "B-15-S01", "equation", "high",
              "与金标 S01 同一式 mg sin45°−μmg cos45°=ma。"),
            S(14, 19, "B-15-S02", "equation", "high",
              "S02 的 a 式，与金标同形。"),
            S(19, 28, "B-15-S02", "equation", "high",
              "与金标 S02 同一结果 t=√(2√2d/((1−μ)g))，此处由 d=½at² 导出。"),
            S(30, 32, "B-15-S04", "judgment", "low",
              "承接 S03 的「净功为零」，改用 A→B 与 P→B 的净功之差求 v；金标 S04 走 v²=2ad。"
              "目标量相同、路径不同，置信度 low。"),
            S(32, 36, "B-15-S04", "equation", "high",
              "上述净功之差的方程；金标无此式（金标用 v²=2ad）。"),
            S(36, 41, "B-15-S04", "equation", "high",
              "化简到 ½v²=gd(1−μ)/√2。"),
            S(41, 46, "B-15-S05", "value", "high",
              "v=√(√2gd(1−μ))，与金标 S04 结果同形。S04 已由上面两段方程承担，此处把最终式挂到 S05"
              "（结果只用题给符号 d、μ、g 表示，不含 a、t）——该步没有独立文本，只能由结果式体现。"),
            S(46, 47, "B-15-S06", "judgment", "high",
              "该句判定 B 点飞出方向。金标 S06 为「沿 45° 坡道方向，飞出后做斜抛」；此处判为水平飞出，"
              "后文据此按平抛处理。"),
            S(49, 57, "B-15-S07", "equation", "low",
              "金标 S07 用斜抛射程 L=v cos45°·(2v sin45°/g)=v²/g；此处改按平抛轨迹与 45° 缓冲坡相切求平台长度上限。"
              "方法不同、目标量同为 L，置信度 low。"),
            S(57, 77, "B-15-S07", "equation", "high",
              "相切条件与判别式 Δ≥0 的推导，得 L≤v²/(2g)。金标同一问的结果为 L=v²/g。"),
            S(77, 83, "B-15-S08", "value", "high",
              "L_max=√2/2·d(1−μ)=d(1−μ)/√2；金标 √2d(1−μ)，二者差 2 倍。"),
        ],
        unal=[
            U(84, 102,
              "重复：结果汇总，三问答案与正文同值，末句为单位说明。"),
            U(103, 112,
              "讨论与自我检查：μ<1 的可行性、L=L_max 的临界说明、以及 P→B 用途的重述。均无新增采分内容，末条与 S03 重复。"),
        ],
    ),
    # ------------------------------------------------------------------ B-17 / v3
    dict(
        qid="B-17", variant="v3", failure_type="calc",
        segs=[
            S(0, 1, None, "setup", "high",
              "声明质量与两个半径符号，不承担采分点。"),
            S(2, 3, None, "setup", "high",
              "过程划分（A→B 滑动、B→C 平抛、C→D 圆弧），不承担采分点。"),
            S(6, 7, "B-17-S01", "judgment", "high",
              "与金标 S01 同一判断（恰好到达最高点 ⇒ 压力为零，重力提供向心力）。"),
            S(7, 10, "B-17-S02", "equation", "high",
              "与金标 S02 同一式。"),
            S(10, 14, "B-17-S03", "value", "high",
              "结果只用 g、R 表示，满足 S03；S02 由上一段方程承担，避免同一式重复计入。"),
            S(15, 19, "B-17-S05", "judgment", "high",
              "与金标 S05 的高度差一致（C 在 D 下方 R+Rcos60°=3R/2）。"),
            S(19, 23, "B-17-S05", "equation", "high",
              "与金标 S05 同一守恒式。"),
            S(23, 30, "B-17-S05", "value", "high",
              "v_C=2√(gR)，与金标 S05 结果一致。"),
            S(30, 31, "B-17-S04", "judgment", "high",
              "该句判定 C 点切线方向。金标 S04 为切线与水平成 60°（v_B=v_C cos60°）；此处判为 30°。"),
            S(31, 39, "B-17-S06", "equation", "low",
              "金标 S06 走 B→D 能量式；此处改走平抛运动学求 h_BC，所求量同为 H_BD，置信度 low。"),
            S(39, 45, "B-17-S07", "value", "high",
              "H_BD=R（D 比 B 高 R）；金标 S07 为 0。"),
            S(46, 52, "B-17-S04", "value", "high",
              "金标 S04 为 v_B=v_C cos60°=√(gR)；此处用 cos30° 得 √(3gR)。对齐依据是它承担 S04 的 v_B 计算；"
              "该值与金标 S10 的 v_A=√(3gR) 同形，但不是对齐依据。"),
            S(53, 57, "B-17-S08", "judgment", "high",
              "与金标 S08 同一判断（摩擦路程 2πR）。"),
            S(57, 63, "B-17-S09", "equation", "high",
              "与金标 S09 同一摩擦功 −μmg·2πR=−mgR。"),
            S(63, 67, "B-17-S09", "equation", "high",
              "与金标 S09 同一动能定理式。"),
            S(67, 72, "B-17-S10", "equation", "high",
              "S10 的中间量 v_A²=5gR；金标 3gR。"),
            S(72, 75, "B-17-S10", "value", "high",
              "v_A=√(5gR)；金标 √(3gR)。"),
        ],
        unal=[
            U(76, 86,
              "重复：结果汇总，三问与正文同值。"),
            U(87, 88,
              "自我检查/讨论：首句重复 S01 的临界判断，后句说明无舍根，无新增采分内容。"),
        ],
    ),
    # ------------------------------------------------------------------ B-18 / v3
    dict(
        qid="B-18", variant="v3", failure_type="calc",
        segs=[
            S(2, 4, None, "setup", "high",
              "研究对象与过程声明（含反弹规则的复述），不承担采分点。"),
            S(6, 10, "B-18-S01", "equation", "high",
              "与金标 S01 同一式 mgh=½mv₀²；但模型只留 v₁²=2gh，没有单独写出 v₀=4 m/s。"),
            S(10, 19, "B-18-S02", "equation", "high",
              "与金标 S02 同一碰撞式 mv₁=2mv_C，并化为 v_C²=gh/2。"),
            S(20, 24, "B-18-S02", "value", "high",
              "v_C=2 m/s，与金标 S02 结果一致。"),
            S(25, 29, "B-18-S03", "equation", "high",
              "与金标 S03 同一临界条件（金标记作 2mg=2m·v_D²/R，等效 v²=gR）。"),
            S(29, 34, "B-18-S04", "equation", "high",
              "与金标 S04 同一路径：C→C′ 机械能守恒，再逆推 h。"),
            S(34, 40, "B-18-S04", "value", "high",
              "h=2.0 m，与金标 S04 结果一致。"),
            S(41, 53, "B-18-S08", "equation", "low",
              "金标 S08 把 C′→F 的动能定理（含 EF 段摩擦 μmg cos37°·L）作为最后反推 h 的工具；"
              "此处提前给出通用式 v_F²=5h−13。金标反推所用的等效关系是 v_F²=5h−5（h=2.5→7.5、h=2→5），"
              "两式常数项不同，但同属 C→F 的能量关系，故挂 S08 且置信度 low。"),
            S(54, 60, "B-18-S06", "equation", "low",
              "该式即金标 S06/S07 共用的射程式（v_F cos37°·2v_F sin37°/g = v_F² sin74°/g）。"
              "S07 的反弹情形另按 1.5 倍飞行时间处理，此处用等比和表达，故挂 S06 且置信度 low。"),
            S(60, 64, "B-18-S05", "judgment", "high",
              "与金标 S05 同一判断（反弹后竖直分速度减半，故水平飞行距离减半）。金标只列「直接落入」与「反弹一次」两种情形，"
              "此处推广到 n 次并据此展开多解。"),
            S(64, 73, "B-18-S06", "equation", "high",
              "0.72 m 的落点条件，对应金标 S06 的直接落入。"),
            S(74, 79, "B-18-S06", "equation", "high",
              "n=1 直接落入：s=0.72，由 s=12v_F²/125 得 v_F²=7.5，与金标 S06 一致。"),
            S(79, 83, "B-18-S07", "equation", "high",
              "等价于金标 S07：0.72=v_F′cos37°·3v_F′sin37°/g，即 1.5s=0.72，得 v_F′²=5。"),
            S(100, 105, "B-18-S08", "equation", "high",
              "由 s=12(5h−13)/125 反解 h，与金标 S08 的反推动作相同。"),
            S(105, 117, "B-18-S08", "value", "high",
              "h=121/35、18/5、41/10（≈3.46、3.60、4.10 m）；金标 S08 为 2.5 m 或 2 m。"),
        ],
        unal=[
            U(83, 99,
              "超出金标情形：金标 S05 只列直接落入与反弹一次两种，n=3、n≥4 两段是模型自设的推广情形，采分点表无对应步。"),
            U(118, 138,
              "重复：结果汇总，三问（含三个 h 值及其近似值）与正文同值。"),
            U(139, 141,
              "自我讨论：把三个解分别对应到反弹次数，并声明无舍根；无新增采分内容。"),
        ],
    ),
    # ------------------------------------------------------------------ B-20 / v3
    dict(
        qid="B-20", variant="v3", failure_type="guessed_without_figure",
        segs=[
            S(2, 6, None, "setup", "high",
              "过程声明。其中「推力超过临界值后相对滑动」未给临界值，临界值在后文由图读出。"),
            S(8, 9, "B-20-S01", "judgment", "high",
              "与金标 S01 同一判断（3mg 与 mg 同向）。"),
            S(9, 12, "B-20-S02", "equation", "high",
              "与金标 S02 同一式 N+mg=mv²/R，N=3mg。"),
            S(12, 18, "B-20-S03", "value", "high",
              "v=4 m/s，与金标 S03 一致（(1) 问不依赖图）。"),
            S(19, 27, "B-20-S04", "judgment", "high",
              "题干（2）（ⅱ）只给了 F=8 N 一个数；折点坐标 (4 N, 1 m/s²) 与滑动段点 (8 N, 3 m/s²) 的读数在题干文字中都没有。"
              "金标图乙登记的 provides 是 k₁=0.5 kg⁻¹、k₂=1 kg⁻¹、b₂=−2 m/s²，对应折点 (4 N, 2 m/s²)。"
              "模型补出的读数与金标登记值不一致——这是 guessed_without_figure 的实证点。",
              inv=True),
            S(27, 36, "B-20-S05", "equation", "high",
              "斜率 1/(M+m)=1/4 由上段补出的 (4 N, 1 m/s²) 算得；金标 k₁=0.5 kg⁻¹（即 1/(M+m)，M+m=2 kg）。",
              inv=True),
            S(36, 40, "B-20-S05", "equation", "high",
              "临界时 a=μg 取的是补出的折点纵坐标 1 m/s²，得 μ=0.1；金标由 b₂=−2 m/s² 得 μ=0.2。",
              inv=True),
            S(40, 49, "B-20-S05", "equation", "high",
              "斜率由补出的两点 (4,1)、(8,3) 算得 1/2，得 M=2 kg；金标 k₂=1 kg⁻¹，M=1 kg。",
              inv=True),
            S(49, 53, "B-20-S06", "value", "high",
              "m=4−2=2 kg；金标 M=1 kg、m=1 kg、μ=0.2。此处三个参数全部由图读数补出。",
              inv=True),
            S(54, 60, "B-20-S07", "equation", "high",
              "由补出的 μ=0.1、m=2 kg、M=2 kg 代入得 a_T=3 m/s²（金标 S07 为 6 m/s²）。"
              "该数值同样不在题干中，但它由已补出的参数算得、不是新的读图动作，按本卡口径不重复标 invented_from_figure。"),
            S(61, 69, "B-20-S07", "equation", "high",
              "a_B=μg=1 m/s²、a_rel=2 m/s²；金标为 a_物=2 m/s²、a_rel=4 m/s²。参数沿用上文补出值。"),
            S(69, 73, "B-20-S08", "equation", "high",
              "与金标 S08 同一关系 L=½a_rel t²（a_rel 取 2 而非 4）。"),
            S(73, 81, "B-20-S08", "equation", "high",
              "与金标 S08 同一组速度式，系数随 a_T 变化（此处 V=3t、u=t；金标 6t、2t）。"),
            S(81, 93, "B-20-S09", "equation", "high",
              "与金标 S09 同一动量守恒式（质量取 2 kg、速度系数取 3t 与 t）。"),
            S(93, 99, "B-20-S09", "equation", "high",
              "与金标 S09 同一机械能守恒式（含 mg·2R）。"),
            S(99, 110, "B-20-S09", "equation", "high",
              "代入数值后的化简结果 10t²=U²+65。"),
            S(110, 118, "B-20-S10", "equation", "high",
              "与金标 S10 同一二次方程形态；系数随前面补出的参数变化。"),
            S(118, 130, "B-20-S10", "value", "high",
              "t=3 s、L=9 m；金标 t=1.5 s、L=4.5 m。金标舍去的根是 3.17 s，此处舍去的是 19/3≈6.33 s。"),
        ],
        unal=[
            U(131, 152,
              "重复：结果汇总，三问（含 M=2 kg）与正文同值。"),
            U(152, 156,
              "自我讨论/检查：弹力方向、F=8 N 必滑动、舍根说明；末句另给了 Q 点相对轨道速度 2 m/s 的自检，无新增采分内容。"),
        ],
    ),
]


def build():
    out = dict(
        meta=dict(
            built_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
            schema_note="本文件是对齐表，不属于 answer.schema（schema 只描述金标答案）。式级对齐属 Schema 1.3，本卡不碰契约。",
            source="评测/基线/raw/",
            gold="schema/examples/ + 采分点总表 223 步",
        ),
        items=[],
    )
    for it in ITEMS:
        raw_rel = "评测/基线/raw/{}/{}.json".format(it["variant"], it["qid"])
        content = json.load(open(os.path.join(ROOT, raw_rel), encoding="utf-8"))["content"]
        lines = content.split("\n")
        segs = []
        for n, s in enumerate(it["segs"], 1):
            quote = "\n".join(lines[s["a"]:s["b"]])
            assert quote and quote in content, (it["qid"], it["variant"], s["a"], s["b"])
            d = dict(i=n, quote=quote, step_id=s["step"], role=s["role"],
                     confidence=s["conf"], note=s["note"])
            if s["inv"]:
                d["invented_from_figure"] = True
            segs.append(d)
        unal = []
        for u in it["unal"]:
            quote = "\n".join(lines[u["a"]:u["b"]])
            assert quote and quote in content, (it["qid"], it["variant"], u["a"], u["b"])
            unal.append(dict(quote=quote, reason=u["reason"]))
        out["items"].append(dict(
            qid=it["qid"], variant=it["variant"], raw_file=raw_rel,
            verdict="wrong", failure_type=it["failure_type"],
            segments=segs, unaligned=unal,
        ))
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("wrote", OUT, "items:", len(out["items"]))


if __name__ == "__main__":
    build()
