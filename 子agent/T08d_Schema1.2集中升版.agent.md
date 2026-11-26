# T08d 子 agent 任务卡 · Schema 1.2 集中升版（四个缺陷一次清算）

> 交给：**写过 T08b / T08c 的人**（要熟悉 `_build_examples.py` 的生成链）。
> 版本 v1.2 · 2026-11-25 15:02（缺陷 ④ 已裁定按方案乙并入 1.2）· 工作区 `D:/峤的个人档案/做点东西/物理解题agent/`
> 前置：**`T12aR2`（验证器补漏）已完成** —— T00 于 14:38 实跑 `python 验证器/tests/audit_regression.py`，**退出码 0**，两个漏判均已修复。D 路现已解压，可派。

---

## 0. 开工前先看这张冲突表

| 与谁 | 冲突 | 处置 |
|---|---|---|
| **T12aR2（A 路）** | A 的验收条件是「7 份样例 `validation.layers` 一字不变」；本卡要重生成 7 份、哈希全变。**同时开会互相打脸** | **已解除**：A 于 14:38 完工，红测退出码 0，7 份样例判定未动。本卡可开 |
| **T19a（C 路）** | C 在**构建时**把 7 份 JSON 内联进 HTML | 不阻塞；但本卡改完样例后，C 需**重跑一次 `原型/_build.py`** |
| **T05R v2（B 路）** | 只写文档，不碰 JSON | 无冲突 |

---

## 1. 要改的四件事（一次改完，不许分批）

分三批改会造成「部分样例新、部分旧」，那比现在更糟（这正是缺陷 ② 的成因）。

### 缺陷 ① 图读数伪装成「题干给定」

| 项 | 内容 |
|---|---|
| 现象 | 从图上读出来的数（B-20 的 `k1/k2/b2`、A-02 的 `1.2v₀`）写进 `situation.given[]`，和题干给定混在一起，**无法区分来源** |
| 后果 | `question.stem_sha256` 只锁 `stem_text`，把 `k1` 从 0.5 改成 0.6，指纹不变、校验仍 E0 通过（**已实测**） |
| 该有的样子 | 读数是**输入的一部分**，改了就应当指纹失效 |

**改法（指定）**：

1. `question.figures[]` 每项新增可选 `provides[]`：
   ```json
   {"symbol": "k1", "value": 0.5, "unit": "kg^-1", "read_from": "图乙第一段斜率", "text": "由图乙第一段斜率读出"}
   ```
2. 新增 `question.input_sha256` = `sha256(stem_text + 规范化后的全部 figure.provides)`。
   **`stem_sha256` 保留不动**（其余工具还在用它），两个指纹并存。
3. `situation.given[]` 里凡是来自 `provides` 的项，标 `source: "figure"`；题干文字给的标 `source: "stem"`（可选字段，缺省视为 `stem`）。
4. `validate_schema.py` 新增规则：`given` 中标 `source:"figure"` 的 `symbol`，必须在某个 `figures[].provides` 里存在且数值一致（误差 ≤ 1e-9，或精确相等）。

### 缺陷 ② B-09 / B-12 整题 `L1: pass` 与步级 `na` 自相矛盾

| 项 | 内容 |
|---|---|
| 现象 | 整题层写死 `validation.layers.L1 = "pass"`，但 B-09 有 1 步 L1 是 `na`、B-12 有 2 步 |
| 根因 | 旧 `build()` 把整题层写死 pass；T08c 已改成「按步级反推」（有 fail 记 fail，有 na 记 na，全 pass 才 pass），但旧样例没重生成 |
| 改法 | **重生成全部 7 份**，让整题层=步级反推结果。B-09/B-12 的 L1 会从 `pass` 变 `na` —— 这是纠正，不是回归 |
| 必须留档 | 旧哈希清单记进 `schema/CHANGELOG.md`，并写一句「旧哈希失效原因」 |

### 缺陷 ③ L4 边界一致性判不了

| 项 | 内容 |
|---|---|
| 现象 | `l4_condition.py` 只能报 `boundary_na`，因为 Schema 没有「过程分段 ↔ 步」的映射，也没有「分段起点参照物」 |
| 改法 | ① `situation.process_segments[]` 每项新增 `boundary_reference`（字符串，如「以碰前瞬间为起点」「以弹簧原长为零势能点」）② `steps[]` 新增可选 `segment_id`，指向上面的 `process_segments[i].segment_id`（没有则现有字段里取，取不到就新增 `segment_id`）③ `validate_schema.py` 校验 `segment_id` 不悬空 |
| 边界 | **本卡只加字段 + 加校验，不改 `l4_condition.py` 的判定逻辑**。L4 拿新字段做什么，另开卡 |

### 缺陷 ④【新，14:45 由 C 路回执暴露】`equation` 必填不可空 → 判断步被迫伪装成方程步

> **这一条不是原定三件之一，是本轮审查新查出来的。它比另三条更底层，但改动面也最大，所以单独列、单独裁定。**

| 项 | 内容 |
|---|---|
| 现象 | `definitions.equation` 的 4 个字段（`latex` / `sympy` / `symbols` / `parse_status`）**全部 required 且类型不可为 null**；`definitions.step.required` 里也包含 `equation`。于是每一步都必须有式子，包括判断步 |
| 实测 | 7 份样例 **66 步，无 equation 的 0 步**。其中 `judgment`/`discussion`/`critical` 共 **29 步，全部带 equation**，且 `formula_id` 全为 null |
| 与总表冲突 | `知识表/覆盖率映射_v1.csv` 里 **43 个判断步的 `formula_id` 全为空**，说明采分点层面认为判断步「无独立方程」。**同一事实两个源给出相反形态（C11）** |
| 后果 1 | 原型（C 路）设计了「`equation` 为 null 时把叉打在 statement 上」的分支，但 66/66 都有 equation，**该分支永不触发**。判断步在页面上被打叉在式子上，本该打在文字判断上 |
| 后果 2 | L1 会去解判断步的表达式，而判断步的判据不是学生要解的方程（例：`Fnet - 0` 表示「合力为零」这个判断，不是要解的式子） |
| 后果 3 | 与 `采分点/采分点拆解规范_v1.md` §1 判断步定义直接冲突：判断步＝「不写式的定性判定」 |

**这一步要先分清两种情况，不能一刀切**（实看 29 步 equation 内容后）：

| 情况 | 例子 | 性质 |
|---|---|---|
| **真判据被塞进 equation** | `Fnet - 0`（合力为零）、`v2 - Rational(6,5)*v0`（v2＝1.2v₀） | 判据不是方程，**是 Schema 逼着找地方放** |
| **方程步被错标成 judgment** | `A-08-S06` 标 `judgment`，equation 是 `a2 - mu*g`（a₂＝μg，牛顿第二定律变形） | **kind 标错**，规范里属 ② 或 ③，不属 ① 判断 |

**✅ 用户 15:00 裁定：采用方案乙。** 原三方案留档备查：

| 方案 | 做法 | 状态 |
|---|---|---|
| 甲 | `equation` 改 nullable，判据迁到 `checks[]` | 未采用（`checks[]` 语义是校验项，塞判据会混） |
| **乙** | **`equation` 改 nullable ＋ 新增 `criterion` 专放判据** | **✅ 采用** |
| 丙 | `equation` 保留必填 ＋ 新增 `equation.role` | 未采用（判断步仍要背一个假式子） |

#### 缺陷 ④ 的具体改法（方案乙，已裁定）

**第 1 步 · 改 Schema**

1. `definitions.step` 的 `required` 里**删掉 `equation`**（`criterion` 也不加进 required）。
2. `definitions.step.properties.equation` 改为：
   ```json
   "equation": { "oneOf": [ {"type": "null"}, {"$ref": "#/definitions/equation"} ] }
   ```
3. 新增 `definitions.criterion`（**必填 4 项，不许空壳**）：
   ```json
   {
     "type": "object",
     "required": ["expr", "expected", "comparator", "text"],
     "properties": {
       "expr":       {"type": "string",  "description": "判据表达式，sympy 语法，如 Fnet"},
       "expected":   {"type": ["number","string","null"], "description": "期望值；纯定性判断可为 null"},
       "comparator": {"enum": ["eq","ne","gt","ge","lt","le","qualitative"]},
       "text":       {"type": "string",  "description": "判据的自然语言原文，必须能独立读懂"}
     }
   }
   ```
4. 新增一条 `validate_schema.py` 规则：**恰好一个** —— `kind` 为 `judgment`/`critical` 时，`equation` 必须为 `null` 且 `criterion` 必须存在；`kind` 为 `equation`/`value` 时，`equation` 必须非 null 且 `criterion` 必须不存在。**两条同时违反要报 E，不许只报 W。**

> `discussion`（多解取舍）**不强制**：它可以有 equation（联立求解），也可以只有 criterion。由数据自己选，校验不管。

**第 2 步 · 先修 kind 标注（这一步不许跳）**

T00 已把 7 份样例 37 个非 `equation` 步逐条判完，**执行者照下表改，不得自行改判**。有异议的写成 TODO 交回，不许静默改。

| 判定 | 步 | 处理 |
|---|---|---|
| **kind 对，判据迁 `criterion`**（11 步） | `A-02-S01`（读图读数）`A-02-S06`（`Fnet-0` 质心匀速）`A-02-S09`（最高点相同⇒速度仍 2v₀）`A-10-S06`（两处可联立）`B-02-S02`（`Fnet-0` 水平无外力）`B-02-S04`（`t2-t` 上下对称）`B-09-S05`（`Fnet-0` 分段）`B-12-S01`（`Fnet-0` 整体法成立）`B-12-S03`（`Fnet-0` 整体法失效）`B-20-S01`（弹力只能指向圆心）`B-20-S04`（转折点即临界） | `equation` → `null`；原 sympy 内容搬进 `criterion`，`criterion.text` 用现 `statement` 的判据句 |
| **kind 标错，改为 `value`**（11 步） | `A-02-S05`（代入求 Ep）`A-02-S15`（相加相除求 μ）`A-08-S06`（`a₂=μg` 是牛顿第二定律，**不是判断**）`A-08-S08`（算 v₂b=2）`A-10-S02`（约去 m 解出 v）`A-10-S03`（推出 M₀=Mr³/R³）`A-10-S05`（解出 v(r)）`A-10-S08`（两式相除得 M′）`B-02-S06`（算 d=x_A+x_B）`B-20-S03`（v=4）`B-20-S06`（由三个读数反解 M/m/μ） | `kind` 改成 `value`；`equation` 保留不动 |
| **本来就是对的，不动**（11 步） | `A-02-S03``A-02-S07``A-02-S08``A-08-S03``A-08-S07``B-09-S07``B-12-S02``B-12-S04``B-12-S06``B-12-S09``B-20-S07` | 无 |
| **discussion/critical 保留**（4 步） | `A-02-S12`（解二次+舍根）`A-08-S10`（critical 临界）`B-09-S04`（critical 恰好滑到边框）`B-20-S10`（解二次+舍根） | 有 equation 的保留；`A-08-S10`/`B-09-S04` 若判据性强再转 criterion，由执行者按「有没有学生要写的式子」定，并在 CHANGELOG 记一句 |

**第 3 步 · 改完必做的三条验收**

1. **重跑验证器**：`python 验证器/tests/audit_regression.py` 仍须退出码 **0**；若有步从 `judgment` 变 `value` 导致 L1 开始校验它、进而 fail，**不许改回 kind 来消错**，要记下是哪几步、单独报回 T00。
2. **重跑 C 路**：`python 原型/_build.py` ＋ `python 原型/_selftest.py`。**新增一条验收**：把某道题的 figure 去掉，判断步的叉必须打在 `statement` 上（现在 66 步全有 equation，改完应当出现真正无 equation 的判断步，这条终于可测）。
3. **哈希清单**：7 份样例重生成后，旧哈希记进 `schema/CHANGELOG.md`，写明「因 equation 改 nullable、判据迁 criterion，全部失效」。

**归属判定**：缺陷 ④ **并入 1.2**，不另开 1.3。理由：另三条缺陷本来就要重生成全部 7 份样例，分开做要生成两次、中间态更乱；且 1.2 若不一次改完，`equation` 的 nullable 会在 1.3 再破一次哈希。

---

## 2. 版本与留档（不许覆盖）

| 动作 | 路径 |
|---|---|
| 现版本归档 | `schema/answer.schema.v1.1.json`（**已有**，确认没被覆盖；若已存在则不动） |
| 新版本 | `schema/answer.schema.json` 升到 `1.2`，`schema_version` 的 enum 加 `"1.2"`（**不删 `"1.0"/"1.1"`**，否则旧档案读不进） |
| 变更说明 | `schema/CHANGELOG.md` 追加一节：三条缺陷 → 改了什么 → 旧哈希清单 → 迁移方法 |

**向后兼容要求**：`schema_version` 为 `"1.1"` 的输入，仍必须能通过 `validate_schema.py`（可给 W 提示新字段缺失，但不许 E）。

---

## 3. 三条负例（这是本卡的核心验收，不是附赠）

改完必须**造出这三个错误能被抓**，每条都要贴出发错时的输出：

| # | 负例 | 期望 |
|---|---|---|
| 1 | 把 B-20 的 `figures[].provides` 里 `k1` 从 0.5 改成 0.6 | `input_sha256` 失配 → **E** |
| 2 | 手改某份样例：整题 `validation.layers.L1 = "pass"`，但某步 `checks` 里 L1 是 `na` | **E**（整题层与步级矛盾） |
| 3 | 手改某步 `segment_id` 为 `"SEG-99"`（不存在） | **E**（悬空引用） |

**反例的做法**：复制一份到 `/tmp` 改，**不要改工作区里的正本**。跑完删掉。

---

## 4. 交付物

| # | 文件 | 内容 |
|---|---|---|
| 1 | `schema/answer.schema.json` | v1.2 |
| 2 | `schema/validate_schema.py` | 三条新规则（provides 一致、整题与步级一致、segment_id 不悬空） |
| 3 | `schema/_build_examples.py` | 支持 `provides` / `input_sha256` / `segment_id`；整题层按步级反推 |
| 4 | 重生成的 7 份 `schema/examples/*.json` | 全 E0/W0 |
| 5 | `schema/CHANGELOG.md` | v1.2 一节 + 旧哈希清单 |
| 6 | `schema/覆盖报告.md` 追加一节 | 三个缺陷各自的「改前 → 改后」证据 |

---

## 5. 完成判据

- [ ] `for f in schema/examples/*.json; do python schema/validate_schema.py "$f"; done` → **7/7 E0 W0**
- [ ] v1.1 格式的样例仍能过（抽 1 份把 `schema_version` 改回 `1.1`、删掉新字段 → 不许 E）
- [ ] B-09 / B-12 的整题 L1 已由 `pass` 变 `na`，且步级确实各有 1 / 2 步 `na`（对得上）
- [ ] 三条负例全部报 E，输出已贴进报告
- [ ] B-20 改 `k1` 后指纹失配（这是本卡存在的理由，必须实测）
- [ ] 采分点 `--strict`、公式库、定律表三个脚本**不受影响**（改 Schema 不该动它们，跑一遍确认没误伤）

**缺陷 ④ 专项（新增）：**

- [ ] `kind` 为 `judgment`/`critical` 的步，`equation` **全部为 null** 且 `criterion` **全部存在**（7 份样例实测计数贴出来）
- [ ] `kind` 为 `equation`/`value` 的步，`equation` **全部非 null**、`criterion` **全部不存在**
- [ ] 22 步 kind 改动（11 步迁 criterion ＋ 11 步改 value）逐条在 CHANGELOG 列出，一步不落
- [ ] `criterion.text` 能独立读懂，不许写「同上」「见式」这类
- [ ] 原型重跑后 17/17 全过；**判断步的叉打在 statement 上**这条终于有样本可测，不许再 SKIP
- [ ] 若某步改 kind 后 L1 由 pass 变 fail，**不许改回 kind 消错**，须单列报回 T00

---

## 6. 一句话提醒

这三个缺陷一直挂着的原因是「改要动 8 份样例哈希，代价大于收益」。现在动它的理由是：**它们已经不是记账问题，而是会让评测结论失真的问题**（图读数改了指纹不变 = 输入被篡改还能过闸；整题层说 pass 而步级说 na = 台账里记的是假事实）。

**但风险也是真的**：这是这一轮唯一会碰「已经通过的东西」的一路。所以：全部旧版本留档、全部旧哈希登记、三条负例先红后绿。**任何一步做不到，宁可停手退回，不要交一个半新半旧的 Schema。**
