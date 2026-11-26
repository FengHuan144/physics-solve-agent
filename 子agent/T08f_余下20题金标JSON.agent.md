# T08f 子 agent 任务卡 · 余下 20 题金标 JSON

> 交给：**做过 T08b/T08d 生成链的人**（必须走 `_build_examples.py`，不许手写 JSON）。
> 版本 v1 · 2026-11-25 15:48 · 工作区 `D:/峤的个人档案/做点东西/物理解题agent/`
> 前置：**`T08e`（Schema 1.2.1）必须先完工**。理由见 §0。

---

## 0. 为什么必须等 T08e

T08e 会给 `figures[]` 加 `file` / `file_sha256` 两个字段。如果本卡先做，20 份 JSON 生成完，T08e 一落地**这 20 份全部要重生成一遍**——等于同一件事做两次，而且第二次没人想再核一遍。

**开工前先确认**：`schema/answer.schema.json` 的 `schema_version` enum 里已经有 `"1.2.1"`，且 `figures[]` 里有 `file_sha256`。没有就停下来问 T00。

## 1. 现状：27 题里只有 7 题有结构化答案

| 已有（7） | 缺（20） |
|---|---|
| A-02、A-08、A-10、B-02、B-09、B-12、B-20 | A-01、A-03、A-04、A-05、A-06、A-09、B-01、B-03、B-04、B-05、B-06、B-07、B-08、B-10、B-13、B-15、B-16、B-17、B-18、B-19 |

原型的下拉里现在只能翻 7 题。补完这 20 题，才谈得上「27 题端到端」。

## 2. 输入（全部只读）

| 用途 | 文件 |
|---|---|
| 步、分值、类别、口径 | `原始资料/五卷力学大题_采分点总表_v2.xlsx` → `采分点总表` |
| 题干与答案原文 | `采分点/题干原文/{qid}_*.md`（27 题全有） |
| 格式模板 | `schema/examples/` 现有 7 份 |
| 生成器 | `schema/_build_examples.py` |
| 图 | `原始资料/题图/` |

## 3. 硬纪律（每条都有前车之鉴）

1. **步数以总表为准，一步不许增删**。总表 223 步是闭合过的（每题分值合计 = 卷面分），你自己加一步就破闭合。
2. **`kind` 按 R15 判，不许所有步都写成 `equation`**。判据：
   - 要学生**写出式子**的 → `equation`（配 `equation`，`criterion: null`）
   - 要学生**下判断/比较**的，哪怕背后有式子 → `judgment` / `critical`（配 `criterion`，`equation: null`）
   - **拿不准的看判分口径**：口径写「未给出 X 与 Y 的比较则 0 分」的就是判断步。
   - T08d 的 37 步判定表在 `子agent/T08d_Schema1.2集中升版.agent.md` §1 缺陷④，照同一原则办。
3. **缺图就写 `file: null`**。不许找相似题的图、不许 AI 生成示意图、不许把教辅配图当原图。宁可 W-fig 警告。
4. **图读数只登记在 `provides`，且只登记数值读数**。几何关系、方位、结构一律不写（R4-EX，见 `原始资料/agent.md` §6）。
5. **不许手改 JSON**。改了生成器再重生成；手改的下次重生成就丢。
6. **一题一提交**。每完成一题跑一次校验，过不了就停下来修，别攒 20 题一起炸。
7. **遇到总表与原文冲突**：以原文为准记进「需上报」，**不许自行改总表**（总表是 T00 维护的，改它要备份 + 回归）。
8. **每题必须能落到 `point_id` 级**（2026-11-25 T20 复盘后新增，来源见 `评测/对齐/B-20失分对不上_复核_20261125.md`）。`step_id` 要与总表 `point_id` **一一对上**，不许出现「一个 step 覆盖两个采分点却分不清各占几分」的步。理由：T20 首跑出现过题级 13/14 与点级 9/10 两个独立落笔的数，中间没有任何东西绑定——**判分器要按采分点给分，缺这一层就只能按步糊过去**。若总表本身是合步（如 A-05-S10、B-20-S09），照抄总表但在 `note` 写明「合步：承载 X 与 Y 两个事实，分不清各占几分」，并列入「需上报」。这条**不改变步数**（第 1 条优先），只要求把不确定性写出来。
9. **`equation.sympy` 不许把单位算进数值系数**（2026-11-25 新增，见 `schema/字段清单.md` 同名条目）。写 `Rational(1,2)*a*t**2`，不写 `2*t**2`——即使 a=4 已经算出。理由：`2*t**2` 里的 2 单位是 m/s²，sympy 串存不住，L2 只能看到 `s²`，会把这个**正确**的式子判成 E-12。验证器已加兜底（含整数系数的不符项落 `na`），但那是兜底不是许可；新写的一律按本条。**已发布的历史产物不回改**，只在报告里登记为已知假 fail。

## 4. 分批（每批 5 题，交中间件）

| 批 | 题 | 备注 |
|---|---|---|
| 批 1 | A-01、A-03、A-04、A-05、A-06 | A 组；A-01 的 S01 是刚修正过的表述，注意按新表述写；A-05-S10 是「合步」（动量+能量两式一步），照抄并在 note 留痕 |
| 批 2 | A-09、B-01、B-03、B-04、B-05 | B-03 有阅卷案例逐式赋分 7 项，步内分值按总表现值，别自己重分配 |
| 批 3 | B-06、B-07、B-08、B-10、B-13 | — |
| 批 4 | B-15、B-16、B-17、B-18、B-19 | B-16 是「最终式对、化简错」的判例，`statement` 要写清哪一步化简出问题 |

## 5. 完成判据（贴命令输出）

```bash
cd "D:/峤的个人档案/做点东西/物理解题agent"
# 1 总数 27
ls schema/examples/*.json | wc -l
# 2 逐份校验
for f in schema/examples/*.json; do echo -n "$(basename $f): "; python schema/validate_schema.py "$f" | tail -1; done
# 3 幂等
python schema/_build_examples.py && md5sum schema/examples/*.json > /tmp/a
python schema/_build_examples.py && md5sum schema/examples/*.json > /tmp/b
diff /tmp/a /tmp/b && echo "幂等 OK"
# 4 步数与分值对账（脚本自写，不许目测）
python - <<'EOF'
import json,glob,openpyxl
wb=openpyxl.load_workbook("原始资料/五卷力学大题_采分点总表_v2.xlsx",data_only=True)
ws=wb["采分点总表"]; h=[c.value for c in ws[1]]; ix={k:i for i,k in enumerate(h)}
gold={}
for r in ws.iter_rows(min_row=2,values_only=True):
    if not r[0]: continue
    q=r[0].split("-S")[0]; gold.setdefault(q,[0,0]); gold[q][0]+=1; gold[q][1]+=r[ix["分值"]]
for f in sorted(glob.glob("schema/examples/*.json")):
    d=json.load(open(f,encoding="utf-8")); q=d["meta"]["answer_id"]
    n=len(d["steps"]); s=sum(x.get("score") or 0 for x in d["steps"])
    flag="" if (n,s)==tuple(gold[q]) else "  ★不符"
    print(f"{q}: JSON {n}步/{s}分  总表 {gold[q][0]}步/{gold[q][1]}分{flag}")
EOF
# 5 回归
python 原型/_build.py && python 原型/_selftest.py
python 采分点/scripts/validate_points.py "原始资料/五卷力学大题_采分点总表_v2.xlsx" --strict
python 验证器/tests/audit_regression.py; python 验证器/tests/l4_regression.py
```

- [ ] **27 份齐**，新增 20 份全部 E0（W-fig 允许）
- [ ] **第 4 步对账表零「★不符」** —— 步数与总分逐题等于总表
- [ ] 生成器幂等
- [ ] 原型题目下拉 27 项；`_selftest.py` 17/17 不回归
- [ ] 20 题里 `kind=judgment` 的步**必须有 `criterion`**（贴计数）
- [ ] 「需上报」一节：总表与原文冲突处逐条列出

## 6. 交货位置

- `schema/examples/` 新增 20 份
- `schema/_build_examples.py`（新增 20 题的生成段）
- `子agent/回执_T08f.md`（贴 §5 全部输出 + 分批中间件）
