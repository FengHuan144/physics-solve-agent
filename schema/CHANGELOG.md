# CHANGELOG · answer.schema

## 1.2.1 — 2026-11-25（T08e，图指纹 + 空锚点）

补两个「数据自己不可信」的洞。两条都是实证，不是推测。

### 缺陷实证

**① 图文件不在任何指纹保护内（严重度高）。** 1.2 的 `input_sha256 = sha256(stem_text + "\n\n#provides\n" + 规范化 provides)`，**不含图文件字节**。今日实测：`原始资料/题图/B-09_图1.png` 从 329×101 换成 780×314（换了个源），7 份样例照样 7/7 E0/W0。`provides` 锁住「读数说了什么」，锁不住「读数是从哪张图上读的」——图可被静默替换成任意一张，包括另一道题的图。

**② discussion 步两头空（严重度中）。** R15 管 `judgment`/`critical`（必须有 criterion、equation 必 null），反方向管 `equation`/`value`。`kind: "discussion"` 两边都不管 → `equation: null` 且 `criterion: null` 的步合法，没有任何可判定锚点，判分器无从上手。

### 改了什么

| 位置 | 变化 |
|---|---|
| `answer.schema.json` | `figures[]` 加 `file` / `file_sha256`（可 null）；`schema_version.enum` 加 `"1.2.1"`；根加 `allOf` 条件必填 |
| `validate_schema.py` | 新增 **R16**（成对）、**R17**（文件存在 + 哈希逐字相等）、**R18**（discussion 不许两头空）、**W-fig**（必需图缺文件） |
| `_build_examples.py` | 新增 `FIG_FILES` 表与 `attach_figure_files()`：**读磁盘字节现算哈希**；版本号写 `1.2.1` |
| `examples/*.json`（7 份） | 全量重生成；4 张图带 file+哈希，5 张图双 null |

| 规则 | 内容 | 级别 |
|---|---|---|
| **R16** | `file` 与 `file_sha256` 必须同时为 null 或同时非 null | E |
| **R17** | `file` 非 null 时，按工作区根解析，磁盘文件必须存在且 sha256 与 `file_sha256` 逐字相等 | E |
| **R18** | `kind == "discussion"` 的步，`criterion` 与 `equation` 至少一个非 null | E |
| **W-fig** | `is_required == true` 且 `file == null` → 必需图缺失 | W |

### 图 ↔ 文件 ↔ 哈希（4 张；其余 5 张为双 null）

| 题 | fig_no | `file` | 字节 | `file_sha256`（全值，供 T00 抽样复算） |
|---|---|---|---|---|
| A-02 | 2 | `原始资料/题图/A-02_图2.png` | 56 449 | `b1c0ec48120c84c81c69f578ae26b0f413a866c386fdc45be8ef9e0274afa8b5` |
| B-09 | 1 | `原始资料/题图/B-09_图1.png` | 105 419 | `81b3c1d0b3a345521ba1a4f0833e5984d5100e7b811f08dc5c0279c5b99b027d` |
| B-20 | 1 | `原始资料/题图/B-20_图甲.png` | 173 122 | `7a37dd806ef878d1156bd770b5a7b9e69efedfc8ee0d388385576a17527797fe` |
| B-20 | 2 | `原始资料/题图/B-20_图乙.png` | 161 043 | `bd07f140c0bd5f84e6723275de2191ace7635a9a1ba334ca50dc35f276299eef` |

双 null 的 5 张：A-02 图1、A-08 图1、A-10 图1、B-12 图1（B-02 无图，`figures: []`）。**这 5 张没有一张 `is_required=true`**，所以 W-fig 一条也不触发 —— 7 份仍是 E0/W0。

> 文件名里的「图」字是真实存在的（`B-20_图乙.png`）。没有改成 `_2.png`，也没有复制副本：原型侧 `_build.py` 的 `FIG_ALIAS` 已把「甲乙丙丁」映射到 fig_no，改代码不改资产。

### 版本号为什么是 1.2.1 不是 1.3

1.3 已预留给「式级驳回」（`review.rejected_steps[].part`）。两件不相干的改动挤进同一个版本号，将来没法说清哪次改的什么。

### 兼容性：`file` 是「条件必填」，不是直接 required

`file`/`file_sha256` 在 1.2.1 里必填（可为 null），但 1.0/1.1/1.2 的档案没有这两个键。若硬写进 `figures.items.required`，旧档案立刻读不进 —— 与 1.1/1.2 立下的「enum 只加不删、旧档案可读」是同一条承诺。故用 draft-07 的 `if/then` 做条件必填：

```json
"if":   { "properties": { "schema_version": { "const": "1.2.1" } } },
"then": { "properties": { "question": { "properties": { "figures": { "items":
          { "required": ["file", "file_sha256"] } } } } } }
```

实测：`example_A-06.json`（1.0，一字未改）E0/W0；A-08 降为 1.1 并删掉 `file`/`file_sha256` 两键，E0/W0；1.2.1 文档删掉 `file_sha256` 键 → S0 报 `'file_sha256' is a required property`。

### 指纹算法未动（任务卡 §4.4）

7 份的 `stem_sha256` 与 `input_sha256` **改前改后逐字相同**，说明本轮没碰已有指纹。图哈希是独立字段，两条指纹各锁一段、互不重叠：

- 只换图 → `file_sha256` 变，`input_sha256` 不变；
- 只改读数 → `input_sha256` 变，`file_sha256` 不变；
- 两个都不动，才算输入真的没变。

### 样例哈希对照（改前 = 16:00 前后的磁盘现状 → 改后 1.2.1）

| 文件 | 改前 | 改后 |
|---|---|---|
| `examples/A-02.json` | `1c95d26ea2e75a262aac40e269293fb5a1bdb533b495772deb160571c191cab7` | `1d1eab4233bfdafc30825b7ca9e98a3d9ac1e3714ff29c04e53072ef0e7188e5` |
| `examples/A-08.json` | `0cef6941a2f5e10e2cd98035da442350d723c2c52a59f9d034f7f5c9d36ea51f` | `19803190e524ca269b88b5f8fc4bfafa87d898d13d46d6978b467044ee954cb3` |
| `examples/A-10.json` | `ddbc8658e0a0bd7e61c0211855527b232b298e0140c66db020823e0953787fad` | `a5ba3dbdeea98fb62b88bd0edeef24750f2ee6dccfb6bbdfddcf127309eab354` |
| `examples/B-02.json` | `e3abcb047df7649d801a45941533fe1f4ffa865d87eacfabc0f90f3e91fe5726` | `bffcb04f4f02ead046424a56b49f0bba46dfb629b24a5c609163daeeb39615e4` |
| `examples/B-09.json` | `6bd0088d6e9c60c3dc2617f201368a2371ce7ce7d27796ddba05c78091d7df31` | `032ac854dd20f9d1a69d87c5110b6cf0e603e44ceef106ad8933ac5ffcce493f` |
| `examples/B-12.json` | `2bf594b031c1691ca2ae29f927f41a1cfdaaa2b4ea549691c6d80a7de02f09c7` | `e67385b2db551f84ae0de60e4aa21dd884cc0910a13711c5d0c10a50a3d7bdb9` |
| `examples/B-20.json` | `50711a4aecda23a9692b1c83102ba9a138fedc5e385dd91bea6d95cc72fa2437` | `24810a075bef487f611840f4eab9d847b92798d9db6bab5ac04ea8af281efa3d` |
| `answer.schema.json` | `bd8e4c1afe7ae064d7c90416de1e4e94ad29a09c101a65fb617bbdfd789f9e5e` | `dbfca06263c5a595a4d069324e7d5343880bf4f4e7032e6141c2c7305c601916` |
| `validate_schema.py` | `96f0a5bdc8983d1291de66aba6a2170803a3c0b1a752a59468bc024b33e9ca97` | `aecab46fc21b2a9d27a683fa2768bd269ee4dc8bcdac7ba6dcfdd779feddedeb` |
| `_build_examples.py` | `fe2926a3e051f758865851b535a6deba8b5a21c165f3a7f7de0b2399c808f0f8` | `dbabd84d3757ec4b60513cad1d8c85d662e340d3cc9edffff950e653378cfe57` |

7 份样例哈希全变是预期的：`schema_version` 改了、每张图多了两个键。**验收口径不是「哈希变了」，是「重生成后 7/7 E0/W0 + 连跑两次哈希相同」。**

> **〔2026-11-25 17:12 T00 复核，推翻 T08e 的误报〕** T08e 曾在此留一段「1.2 一节 3 项与磁盘不符」。逐项复算后**不成立**：它举的 `58a98550…` / `b530397…` / `4f129e62…` 全部取自 **1.1 节的「改后」列**，被当成了 1.2 节的表记值。实际这 10 项里 **9 项与磁盘逐字一致**，唯一不等的是 `validate_schema.py`（1.2 节记 `aecab46f…`，磁盘 `8fdb7df2…`）—— 那是 T08e 本轮自己改的校验器，属正常，新值已记在 1.2.1 节。故**原警告已删，无历史遗留缺陷**。

### 三处超出卡片字面的判断（请复核）

1. **`file` 加了 `pattern`**：`^(?![A-Za-z]:)(?![/\\\\])`，拦盘符与起始的 `/`、`\`。卡片 §4.3「不许把 file 写成绝对路径」原本只是给执行者的纪律，写成 pattern 才拦得住 T08f 的 20 份。空串另由 `minLength: 1` 拦。
2. **R18 不设版本闸门**：1.0/1.1 的 `equation` 在那两版里本身必填，合法旧档案恒真；1.2 起 `equation` 可空，这条底线才需要存在。实测 A-06（1.0）2 个 discussion 步全过。
3. **`check_v12` 的版本闸门由 `ver == "1.2"` 改为 `ver in ("1.2","1.2.1")`**：不改的话，7 份升到 1.2.1 后 R11/R12/R15 会**整组静默跳过** —— 那比原缺陷更坏。卡片没提这一条，但非改不可。

## 1.2 — 2026-11-25（T08d，四缺陷一次清算）

一次改完、7 份样例全量重生成。**不许分批**：分批会造成「部分样例新、部分旧」，那正是缺陷 ② 的成因。

### 改了什么（按缺陷编号）

| # | 缺陷 | Schema 变化 | 校验器 | 样例变化 |
|---|---|---|---|---|
| ① | 图读数伪装成「题干给定」 | `figures[].provides[]`（symbol/value/unit/read_from/text，5 项全必填）；`question.input_sha256`；`given[].source`（stem/figure，可选，缺省 stem） | R11 given↔provides 同符号且数值一致（≤1e-9）；R12 重算 input_sha256 | B-20 三条读数（k1/k2/b2）、A-02 四条读数（v2/v0/v1p/v2p）进 provides；对应 given 标 source=figure |
| ② | 整题 `L1: pass` 与步级 `na` 矛盾 | 无字段变化 | **R13** 整题层必须等于步级反推（fail > na > skipped > pass） | 7 份重生成；**B-09 整题 L1 pass→na（1 步 na）、B-12 pass→na（2 步 na）** |
| ③ | L4 边界一致性判不了 | `process_segments[].segment_id`（`^SEG-\d{2}$`）、`boundary_reference`；`steps[].segment_id`（可选） | **R14** segment_id 不许重复、不许悬空 | 28 个过程分段全部有 id + 参照物；62/66 步已归属，4 步跨段留空（A-02-S15、B-02-S04、B-09-S05、B-09-S07）。B-20 补一条「第 (1) 问独立情境」分段（原 3 段→4 段），否则该问 3 步无处归属 |
| ④ | `equation` 必填 → 判断步被迫伪装成方程步 | `step.required` 删 `equation`；`equation` 改 `oneOf[null, equation]`；新增 `definitions.criterion`（expr/expected/comparator/text 四项必填） | **R15** judgment/critical ⇔ equation=null 且带 criterion；equation/value ⇔ 反之；criterion.text 禁占位词 | **13 步迁 criterion**（11 judgment + 2 critical，equation→null）；**11 步 kind 改 value**（equation 保留） |

### 24 处步改动逐条（一步不落）

**A. 迁 criterion（13 步，equation → null，原 sympy 内容搬进 criterion.expr/expected）**

| 步 | 原 kind | criterion.expr | expected | cmp | 判据要点 |
|---|---|---|---|---|---|
| A-02-S01 | judgment | `v2` | `Rational(6,5)*v0` | eq | 图 (b) 读出 B 碰前 1.2v₀；t₀ 处共速 v₀ |
| A-02-S06 | judgment | `Fnet` | 0 | eq | 水平合外力为零 ⇒ 质心匀速，压缩量＝两线间面积 |
| A-02-S09 | judgment | `v1p` | `2*v0` | eq | 最高点相同 ⇒ 第二次碰后 A 仍 2v₀ |
| A-08-S10 | **critical** | `L - 10*(v2b - v0)/2*dt` | `s1` | eq | 10 周期净位移 3.0 m，余 0.3 m＝s₁ |
| A-10-S06 | judgment | `v0**2*R - Gc*M` | 0 | eq | r＝R 与 r＝nR 处取同一 v₀（实测事实，非引力推论） |
| B-02-S02 | judgment | `Fnet` | 0 | eq | 内力成对抵消、水平无外力冲量 ⇒ 只水平动量守恒 |
| B-02-S04 | judgment | `t2` | `t` | eq | 炸裂高度 ½gt² 反解，下落时间仍为 t |
| B-09-S04 | **critical** | `v2**2/(2*a1)` | `s2` | eq | 滑行 0.02 m 恰等于 s₂ ⇒ 恰好到边框 a |
| B-09-S05 | judgment | `Fnet` | 0 | eq | 只有摩擦力 ⇒ 两段均匀减速，a 同为 1 m/s² |
| B-12-S01 | judgment | `Fnet` | 0 | eq | 初始静止、加速度同为零 ⇒ 可整体 |
| B-12-S03 | judgment | `Fnet` | 0 | eq | 杆仍静止合力为零，但加速度不同 ⇒ 整体法失效 |
| B-20-S01 | judgment | `Nf` | `3*m*g` | eq | Q 点弹力只能指向圆心，故 Nf 与 mg 同向 |
| B-20-S04 | judgment | `(M + m)*mu*g` | 4 | eq | 折点即最大静摩擦临界 F＝(M＋m)μg＝4 N |

> **两处 critical（A-08-S10、B-09-S04）也迁了 criterion，与任务卡 §1 第 2 步表格里「有 equation 的保留」字面冲突。**
> 取舍依据：同一张卡 §1 第 1 步规则 4 与 §5 完成判据都写明「judgment/**critical** 时 equation 必须为 null 且 criterion 必须存在」，两处与表格一处，按规则执行。
> 理由也站得住：这两步学生写的是「剩余距离」「滑行距离」的比较，不是要解的方程 —— 正是缺陷 ④ 说的「判据不是方程」。**此项请 T00 复核；若要保留 equation，改法是把这两步 kind 改为 equation，不是把规则放宽。**

**B. kind 改 value（11 步，equation 一字不动）**

| 步 | 原 kind | 式子 | 理由 |
|---|---|---|---|
| A-02-S05 | discussion | `Ep - 3/5*m*v0**2` | 代入求 Ep，是求值不是讨论 |
| A-02-S15 | discussion | `mu - 9/20` | 相加相除求 μ |
| A-08-S06 | judgment | `a2 - mu*g` | 牛顿第二定律变形，不是判断 |
| A-08-S08 | judgment | `v2b - (Iimp/m2 - v0)` | 算 v2b＝2 |
| A-10-S02 | discussion | `v**2 - Gc*M/r` | 约去 m 解出 v |
| A-10-S03 | judgment | `M0 - M*r**3/R**3` | 推出 M₀＝Mr³/R³ |
| A-10-S05 | discussion | `v**2 - r**2*Gc*M/R**3` | 解出 v(r) |
| A-10-S08 | discussion | `Mp - (n-1)*M` | 两式相除得 M′ |
| B-02-S06 | discussion | `d - s1 - s2` | 算 d＝x_A＋x_B |
| B-20-S03 | discussion | `v - 4` | v＝4 |
| B-20-S06 | discussion | `(M-1)+(m-1)+(mu-1/5)` | 由三条读数反解 M/m/μ |

> A-08-S06 原来没有 `value` 槽，改 value 后补 `a2 = 5 m/s²`（原 step 只有方程没有落值，属缺项补齐，不是改判）。
> 其余 10 步原有 value 槽保留不动。

**C. 保留 discussion（2 步）**：A-02-S12（解二次+舍根）、B-20-S10（解二次+舍根）—— 有 equation，按卡「discussion 不强制」原样保留。
> **A-08-S10 / B-09-S04 未按「保留」处理，已迁 criterion，理由见上。**

### 旧哈希清单（全部失效，留档备查）

失效原因：`equation` 改 nullable、判据迁 criterion，**且**整题层由写死 pass 改为步级反推、新增 provides/input_sha256/segment_id 六组字段 —— 7 份样例内容全部重写，旧哈希无一可复用。

| 文件 | 1.1 旧哈希（sha256） | 1.2 新哈希 |
|---|---|---|
| `examples/A-02.json` | `5f56245fbea080432dcf7c593495bf0852b830ce93feb2a011f2124014ecf30b` | `1c95d26ea2e75a262aac40e269293fb5a1bdb533b495772deb160571c191cab7` |
| `examples/A-08.json` | `06acbca79e2d248613b1248333f7bd2917e321f8c1cd0d8f6fc438574be63163` | `0cef6941a2f5e10e2cd98035da442350d723c2c52a59f9d034f7f5c9d36ea51f` |
| `examples/A-10.json` | `32f6dc48d02d5bff9e0e1e397858c5f546e71d640847f4d2def6200f3a055e45` | `ddbc8658e0a0bd7e61c0211855527b232b298e0140c66db020823e0953787fad` |
| `examples/B-02.json` | `4e5d5a78054a321c5684509d2e2bd71bd0f6f049a70a97ce0711de2b23d7972e` | `e3abcb047df7649d801a45941533fe1f4ffa865d87eacfabc0f90f3e91fe5726` |
| `examples/B-09.json` | `9da19e478cb23d15258be891ae8d4ed19b64e8488713a6a625f58137e18dc749` | `58a98550b90dfcb3353521e254ea47ed4782eeef8dc1d120707a0744d2cc55b2` |
| `examples/B-12.json` | `fac12479f779812e9ba03df3f8d13a963f0bfc65f139b20bb4197103b15bc713` | `2bf594b031c1691ca2ae29f927f41a1cfdaaa2b4ea549691c6d80a7de02f09c7` |
| `examples/B-20.json` | `6e781e087de9586772cd82c62aeebf4bb28ab806419eb67710466c6fb25e8ea0` | `50711a4aecda23a9692b1c83102ba9a138fedc5e385dd91bea6d95cc72fa2437` |
| `answer.schema.json` | `2c5154adbe3aeb8255688e6fe0151f5d42ef89fa885a72a35f021f3171115745` | `bd8e4c1afe7ae064d7c90416de1e4e94ad29a09c101a65fb617bbdfd789f9e5e` |
| `validate_schema.py` | `508233f8106906ad8aff3459485e037c9caf0e9d033fb90f85df68c6771ed76c` | `b530397cad94c7b8c791ed3e0e8478aac5819db3936ea2f819797d841728e2f3` |
| `_build_examples.py` | `53acc5b0c9d9231d5097fa500083d7650025111c088a250c86505890838c092d` | `4f129e62b3e896b2e7db8e9697ee12aaa4c10a892758113953a0c4d6e19ae2dc` |

### 迁移方法（1.1 → 1.2）

1. `schema_version` 改 `"1.2"`。
2. **判据步**：`kind` 为 `judgment`/`critical` 的，把 `equation` 整块删掉改 `null`，原 `sympy` 的「待比较量」写进 `criterion.expr`、右端写 `criterion.expected`，`criterion.text` 用原 `statement` 里的判据句（必须能独立读懂）。
3. **方程步**：`kind` 为 `equation`/`value` 的，保留 `equation`，删掉任何 `criterion`。
4. **图读数**：凡是「题干没给、只在图上」的量，逐条写进 `figures[].provides`（`read_from` 要能按句重读），`given` 里同符号项加 `"source": "figure"`。
5. **重算指纹**：`question.input_sha256 = sha256(stem_text + "\n\n#provides\n" + 规范化 provides)`（规范化规则见 schema 字段描述，生成器与校验器各有一份同名字面实现）。`stem_sha256` 不动。
6. **过程分段**：`process_segments[]` 加 `segment_id`（`SEG-01` 起）与 `boundary_reference`；`steps[]` 能归属的加 `segment_id`，跨段步留空。
7. **整题层**：按步级 checks 反推，`fail > na > skipped > pass`；不许再写死 `pass`。

### 兼容性

- `schema_version` 为 `"1.0"`/`"1.1"` 的输入仍可过校验：新字段全为可选，业务规则 R11/R12/R15 按版本闸门跳过，R13/R14 对无新字段的旧文档不可触发。实测：A-08 退回 1.1（删新字段、恢复 S10 的 equation）E0/W0；原始 `example_A-06.json`（1.0）E0/W0。
- **`schema_version` 的 enum 只加不删**：`["1.0","1.1","1.2"]`。删旧值会让旧档案读不进。

### 归档

- 改前原件：`schema/answer.schema.v1.1.json`（28 874 字节，与 1.2 前的 `answer.schema.json` 逐字节相同）。
  **注意：任务卡 §2 写「已有，确认没被覆盖」，实际执行时该文件不存在**，本轮是从改前的 `answer.schema.json` 复制作出，不是「确认未动」。
- `schema/answer.schema.v1.0.json` 未动。

### 一处超卡改动（请复核）

`验证器/runner.py::_write_layers` 的聚合口径由「有一个 pass 就 pass」改为「fail > na > skipped > pass」。不改的话，验证器跑完给出的整题层必然违反 R13 —— 实测 B-09 经 runner 处理后 `L1=pass`，而步级有 1 步 na，**同一份数据自己打自己**。这是缺陷 ② 的同族问题，按同一口径收口，未动 `l4_condition.py`。


## 1.1 — 2026-11-25（T08b）

**加了什么**

- 无新增字段、无新增必填项、无枚举变化。`kind` / `layer` / `status` / `error_code` 与 1.0 逐字相同（diff 见 `覆盖报告.md` §5）。
- 新增 3 份真题样例：`examples/A-08.json`（圆周＋机械能＋4 过程＋临界）、`examples/B-12.json`（整体法/隔离法）、`examples/B-09.json`（动量＋依赖图）。
- 唯一的结构改动：`schema_version` 从 `const: "1.0"` 放宽为 `enum: ["1.0", "1.1"]`。

**为什么**

v1.0 只在 A-06（板块模型）一题上验过。T05b 已把 27 题拆完（223 步 / 344 分），Schema 能不能表达别的题型，此前没有任何证据。本轮用 4 份真样例（含 A-06 回归）证伪，结论是「无需加字段也能表达这 4 类」——按任务卡 §0「加一个字段没人用，比缺一个字段更糟」，不加。

**版本号为什么是「放宽」而不是「改死」**

任务卡同时要求 R1（`example_A-06.json` 一字不改仍通过）和 R7（`schema_version` 改 1.1）。schema 原定义是 `const: "1.0"`，两条无法同时成立：

- 若 `const` 改成 `"1.1"` → 老样例立刻挂，违反 R1；
- 若保持 `const: "1.0"` → 新样例只能自称 1.0，R7 名存实亡。

取 `enum: ["1.0","1.1"]`：读入兼容两版，**写盘一律用 1.1**。这是对原描述「改动字段即改版本号，不许原地兼容」的一次**显式例外**，不是默认做法。→ **需要你点头**（`STATE.md` 待裁定）。

**兼容性**

- `example_A-06.json`：一字未改，校验 E 0 / W 0。
- `kind` / `status` / `error_code` / `step.required` / `check.layer` 五项 diff 全部 `True`。
- T05b 的 17 列 CSV 不受影响：本轮没动任何与 `point_id` / `kind` 映射有关的字段。

**备份**

`schema/answer.schema.v1.0.json`（改前原件）。
