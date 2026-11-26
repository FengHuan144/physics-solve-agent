# T08 子 agent 任务卡 · 解析 Schema 定稿

> 交给：一个只做「定 Schema + 写校验器 + 造真样例」的子 agent。
> 不写生成器、不调模型、不做界面。你的产出是一份契约，后面 S1–S5、L1–L4、三档路由、驳回落库全部按它写。
> 版本 v1 · 2026-11-25 · 工作区 `D:/峤的个人档案/做点东西/物理解题agent/`

---

## 0. 一句话与三条边界

**一句话**：定义「步骤单元」JSON Schema，让一条解析能被五个 Skill 共用、被四层质检定位到步、被老师按步驳回，并附一份用 A-06 真题造的真样例。

**边界**

1. **不写生成器**。分段生成、重试、温度是 T12/T13 的事；你只在 Schema 里给出「支持分段」的字段结构。
2. **不做界面**。你只交一份「界面必须显示的字段清单」，线框在 D10 画。
3. **不动采分点表**。Schema 引用 `point_id`，不重定义它。

---

## 1. 背景：这个 Schema 要同时喂饱五个环节

| 环节 | 从 Schema 里取什么 |
|---|---|
| S1 情境解析 | 对象、已知条件、过程分段、所求量（四要素，缺一不可） |
| S2 建模列式 | 每一步的**显式符号方程** + 用了哪条定律（`law_ids`） |
| S3 求解讨论 | 结果值、单位、方向、有效数字、舍根说明 |
| S4 质检校验 | 每一步的 L1–L4 状态、失败层、错误码 |
| S5 采分点对齐 | 这一步命中哪个 `point_id`、得几分、漏了哪个点 |

三条来自方案的硬约束（不要改）：

- **D1 用采分点作解析骨架**：解析必须由若干「步骤单元」组成，每个单元绑定一个采分点，并给出符号方程。自由散文式解析一律不接受。
- **长输出会截断**：国产模型长 JSON 会字段漂移。Schema 必须支持「先出步骤大纲，再逐步展开」，且允许部分完成。
- **符号解析脆弱**：只接受受限 LaTeX 子集；解析失败要能标成 `degraded`，**不能记成判错**。

---

## 2. 开工前必须先解决的一个冲突（已核，照这个结论写）

三层材料对 L1/L2 的定义不一致：

| 材料 | 写法 |
|---|---|
| 方案 PDF（D2 决策 + 三屏线框） | L1 量纲、L2 回代 |
| `原始资料/agent.md` §2.2 | L1 计算、L2 量纲 |
| 采分点表 v2「错误码枚举」检测层列 | E-10 代入代数错 → L1；E-11 单位缺失 → L2；E-12 量纲不符 → L2 |

**结论：以错误码表为准**，因为日志、驳回原因、归因统计全按它写。

```
L1 计算（sympy 回代）  L2 量纲（pint）  L3 边界（扰动/极限）
L4 条件一致            L5 建模与依据（仅人工）  L6 表达（仅辅助）
```

Schema 的 `layer` 枚举锁死这 6 个值。**PDF 那段是笔误**，在 `字段清单.md` 顶部记一条「与方案 v1.2 的差异」，不要偷偷改，也不要两套并存。

---

## 3. 硬规则（编号即验收项）

- **R1 `step_id` 与 `point_id` 必须分开**。`step_id` 是这次解析的第几步（`A-06-S01`）；`point_id` 是金标采分点（`A-06-S04`）。生成时模型不知道 `point_id`，由 S5 对齐后回填。两者混用，自由生成必然错位。
- **R2 每个 step 必须能追到 outline**。`steps[].step_no` ⊆ `outline[].step_no`，不许出现大纲里没有的步骤。
- **R3 方程必须双表示**：`equation.latex`（受限子集）+ `equation.sympy`（归一化可解析串）+ `equation.symbols[]`（引用 T09 符号白名单的 `symbol_id`，不许自由文本）。
- **R4 解析失败是状态，不是错误**：`parse_status ∈ {ok, degraded, failed}`。`degraded` 单独统计比例；比例 >20% 时停用 L2，只保留 L1。**不得把 `degraded` 计入 `fail`。**
- **R5 置信度只能排序**：`confidence` 1–5，字段说明里写死「仅用于同批排序，禁止作为通过阈值」。这是方案 D4 的硬决策。
- **R6 引用完整性**：`grading.point_hits[].point_id` 必须存在于采分点表；`validation.failures[].step_id` 必须存在于 `steps`；`steps[].law_ids[]` 必须存在于 T10 的 12 条。
- **R7 不允许未知字段**：JSON Schema 用 draft-07，所有对象 `additionalProperties: false`。字段漂移要报错，不要静默忽略。
- **R8 分值闭合**：`sum(point_hits[].score_awarded) == grading.score_awarded`；`grading.score_total == 该题卷面分`。
- **R9 必填字段最小集 = UI 三屏能渲染**：题干 / 结构化理解四要素 / 按采分点切的步骤 / 质检面板 / 分档 / 裁决入口。少一个，D10 的线框就落不了地。

---

## 4. Schema 结构（照这个骨架写，字段名不要自创同义词）

```json
{
  "schema_version": "1.0",
  "meta": {
    "answer_id": "A-06-R1",
    "question_id": "A-06",
    "group": "A",
    "source": "2024 新课标卷",
    "question_no": 25,
    "full_score": 14,
    "mode": "gold",
    "model": "deepseek-v3",
    "prompt_version": "p1",
    "temperature": 0.2,
    "generated_at": "2026-11-25T00:00:00+08:00",
    "latency_ms": 0,
    "tokens": {"in": 0, "out": 0}
  },
  "question": {
    "stem_text": "……",
    "stem_sha256": "……",
    "figures": [{"fig_no": 1, "caption": "……", "caption_source": "vlm", "is_required": true}],
    "subquestions": [{"no": "(1)", "text": "……", "score": 6}]
  },
  "situation": {
    "objects": [{"id": "obj1", "name": "薄板", "mass_symbol": "M", "note": "质量与物块相等"}],
    "given": [{"symbol": "mu", "value": 0.3, "unit": "1", "text": "动摩擦因数 μ=0.3"}],
    "process_segments": [{"no": 1, "name": "相对滑动", "start": "物块滑上薄板", "end": "物块从右端飞出"}],
    "targets": [{"no": "(1)", "quantity": "v0", "text": "求物块初速度"}],
    "assumptions": ["平台光滑"]
  },
  "outline": [
    {"step_no": 1, "title": "判定板块间为滑动摩擦", "depends_on": []},
    {"step_no": 2, "title": "对物块列牛顿第二定律", "depends_on": [1]}
  ],
  "steps": [
    {
      "step_id": "A-06-S01",
      "step_no": 1,
      "title": "判定板块间为滑动摩擦",
      "point_id": "A-06-S01",
      "kind": "judgment",
      "statement": "物块相对薄板向右滑动，二者间为滑动摩擦，摩擦力大小 μmg。",
      "equation": {
        "latex": "f = \\mu m g",
        "sympy": "f - mu*m*g",
        "symbols": ["f", "mu", "m", "g"],
        "parse_status": "ok"
      },
      "value": null,
      "law_ids": ["L-05"],
      "checks": [{"layer": "L4", "status": "pass", "detail": "题目给出 μ 与接触面", "error_code": null}],
      "confidence": 5,
      "status": "checked"
    }
  ],
  "grading": {
    "point_hits": [{"point_id": "A-06-S01", "step_id": "A-06-S01", "score_awarded": 1, "score_possible": 1, "hit": true, "note": ""}],
    "missing_points": [],
    "extra_steps": [],
    "score_awarded": 1,
    "score_total": 14,
    "weighted_rate": 0.0714
  },
  "validation": {
    "layers": {"L1": "pass", "L2": "pass", "L3": "na", "L4": "pass"},
    "failures": [{"step_id": "A-06-S05", "layer": "L1", "error_code": "E-10", "detail": "回代不成立"}],
    "zero_point_hit": false,
    "rewrite_rounds": 0
  },
  "triage": {
    "level": "yellow",
    "signals": {"hard_check": "partial", "question_type_prior": "mid", "self_rank": 0.42, "rework_rate": null},
    "reason": "L1 有一处失败，未触碰归零点"
  },
  "review": {
    "verdict": "pending",
    "rejected_steps": [],
    "reason_codes": [],
    "diffs": [{"step_id": "A-06-S05", "before": "……", "after": "……"}],
    "added_steps": [],
    "reordered": false
  }
}
```

**字段说明只写容易写错的 8 个**

| 字段 | 约束 | 为什么 |
|---|---|---|
| `mode` | `gold` / `free` / `rewrite` 三值 | `gold` 下 `point_id` 必填；`free` 下由 S5 回填；`rewrite` 只改失败步 |
| `equation.sympy` | 左边减右边 = 0 的形式，如 `f - mu*m*g` | 回代需要「表达式 = 0」，写成 `f = mu*m*g` 无法直接 `solve` |
| `equation.parse_status` | `ok/degraded/failed` | 决定这一步参不参与 L2 统计，不是判错 |
| `kind` | `judgment` / `equation` / `value` / `discussion` | 对应采分点五类；`judgment` 允许 `law_ids` 为空 |
| `value.direction` | 只允许 `+x/-x/+y/-y/逆时针/顺时针/null` | 自由文本方向无法比对 |
| `confidence` | 1–5 整数 | 只排序，不设阈值 |
| `triage.level` | `green/yellow/red` | 归零点命中必须 `red`，见 R10 |
| `review.reason_codes` | 取值域 = 21 条错误码 | 驳回原因码不能自创 |

- **R10 归零点**：`validation.zero_point_hit = true` 时，`triage.level` 必须为 `red`，与其余分数无关。归零码目前是 `E-01`（基数/分母误取）与 `E-20`（图像读数错）。

---

## 5. 交付物（4 个文件，路径固定）

| 文件 | 内容 | 验收 |
|---|---|---|
| `schema/answer.schema.json` | draft-07 Schema，`additionalProperties:false` | `jsonschema.Draft7Validator.check_schema` 通过 |
| `schema/example_A-06.json` | 用 `采分点/样张_A-06.csv` 的 10 步造一条**真样例**，不许编题 | 能过校验器 |
| `schema/validate_schema.py` | Schema 校验 + 4 条业务规则（R1/R6/R8/R10） | 负测试能报错 |
| `schema/字段清单.md` | 给 D10 线框的「界面必须显示的字段」，按三屏分组；顶部记 L1/L2 冲突结论 | 一页 |

`validate_schema.py` 必须实现：

1. JSON Schema 校验
2. `step_id` 唯一、`step_no` 连续
3. `point_id` 在采分点表存在（读 xlsx 的 `采分点总表`）
4. 分值闭合（R8）
5. `zero_point_hit=true → level=red`

---

## 6. 验收（含负测试，缺一不算完）

```bash
cd "D:/峤的个人档案/做点东西/物理解题agent"

# 正测试
python3 schema/validate_schema.py schema/example_A-06.json          # 退出 0

# 负测试 1：删掉 point_id，应报错
# 负测试 2：把 layer 改成 "L7"，应报错
# 负测试 3：加一个未知字段 "foo"，应报错（additionalProperties）
# 负测试 4：把 score_awarded 改成 99，应报错（分值不闭合）
# 负测试 5：zero_point_hit=true 但 level=green，应报错
```

五个负测试各跑一次，把输出贴进回报。

---

## 7. 已知陷阱

| # | 陷阱 | 后果 |
|---|---|---|
| 1 | 把 `point_id` 当 `step_id` | 自由生成时 1:1 对不上，S5 命中率全废 |
| 2 | 用 `\text{}` 包中文 | sympy 解析失败率飙升，L2 直接不可用 |
| 3 | `\frac{1}{2}` 写成 `1/2` | sympy 按整数除法算成 0 |
| 4 | 把 `degraded` 记成 `fail` | L2 失败率虚高，误判模型能力，也会误判红档比例 |
| 5 | `confidence` 当阈值 | 违反 D4；模型自评绝对值不可信 |
| 6 | Schema 到处允许 `null` | 后续统计全是空值，指标算不出来 |
| 7 | 只定义「一道题的解析」，不定义「一次生成尝试」 | 没有 `rewrite_rounds`，三档路由拿不到「重写 2 轮仍失败」这个信号 |
| 8 | 忘了 `review.diffs` | D6 要求老师修改落成结构化字段，自由文本批注沉淀不成规则 |

---

## 8. 回报格式

```
交付：4 个文件（路径）
Schema 版本：1.0 · draft-07 · 对象数 N · 必填字段 M
正测试：通过 / 失败（贴最后一行）
负测试：5/5 报错（逐条贴错误信息首行）
与方案 v1.2 的差异：L1/L2 顺序（已在字段清单顶部记录）
未做的事：生成器、界面、采分点表改动（按边界）
需要裁定：无 / {具体问题}
```
