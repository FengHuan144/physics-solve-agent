# T08e 子 agent 任务卡 · Schema 1.2.1（图指纹 + 空锚点）

> 交给：**做过 T08d 的人**（熟悉 `_build_examples.py` 与 `validate_schema.py` 的双实现）。
> 版本 v1 · 2026-11-25 15:48 · 工作区 `D:/峤的个人档案/做点东西/物理解题agent/`
> 前置：无（T08d 已收工，Schema 1.2 已定稿）。**但本卡做完才能开 T08f，顺序不能反。**

---

## 0. 一句话

修两个「数据自己不可信」的洞：**图文件不在任何指纹保护内**、**discussion 步可以没有任何可判定锚点**。

## 1. 两个缺陷的实证（不是推测）

### 缺陷 ① 图文件不受保护（严重度高）

现在的指纹算法是：

```
input_sha256 = sha256(stem_text + "\n\n#provides\n" + 规范化 provides)
```

**不含图文件字节。** 今天已经实证：`原始资料/题图/B-09_图1.png` 从 329×101 换成 780×314（换了个源），7 份样例照样 7/7 E0/W0。

后果：图是**数据源**（A-02 的四个读数、B-20 的三个量全在图里），却可以被静默替换成任意一张图，包括**另一道题的图**。`provides` 锁住了「读数说了什么」，锁不住「读数是从哪张图上读的」。

### 缺陷 ② discussion 步两头空（严重度中）

R15 只管 `judgment`/`critical` 必须有 `criterion` 且 `equation` 必须 null，反过来只管 `equation`/`value`。**`kind: "discussion"` 两边都不管** → 允许出现 `equation: null` 且 `criterion: null` 的步，这种步没有任何可判定锚点，判分器将来无从上手。

## 2. 要改的三件事

### 2.1 加两个字段（`figures[]` 内）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | `string \| null` | **是**（可为 null） | 相对工作区根的路径，如 `原始资料/题图/B-20_图乙.png`。**没有图就写 null，不许留空串** |
| `file_sha256` | `string \| null` | **是**（可为 null） | 图文件字节的 sha256（小写十六进制全文） |

`additionalProperties: false` 要同步放开这两个键。

### 2.2 三条新规则

| 规则 | 内容 | 级别 |
|---|---|---|
| **R16** | `file` 与 `file_sha256` **必须同时为 null 或同时非 null** | E |
| **R17** | `file` 非 null 时，从工作区根解析路径，**磁盘文件必须存在且 sha256 与 `file_sha256` 逐字相等** | E |
| **R18** | `kind == "discussion"` 的步，`criterion` 与 `equation` **至少一个非 null** | E |

再加一条 WARN（不算错，因为确实没有图）：

| 规则 | 内容 | 级别 |
|---|---|---|
| **W-fig** | `is_required == true` 且 `file == null` → WARN「必需图缺失」 | W |

### 2.3 版本号

`schema_version` 升 **`1.2.1`**，`enum` 加进 `"1.2.1"`，旧值 `1.0/1.1/1.2` 一律保留。

> **为什么不升 1.3**：1.3 已经预留给「式级驳回」（`review.rejected_steps[].part`）。两个不相干的改动挤进同一个版本号，将来没法说清哪次改的什么。

## 3. 现有数据怎么落（7 份样例）

| 题 | 图 | 现状 | `file` |
|---|---|---|---|
| A-02 | 图1（装置示意） | 无文件 | `null` |
| A-02 | 图2（v–t） | `原始资料/题图/A-02_图2.png` | 填路径 + 哈希 |
| A-08 | 图1 | 无文件 | `null` |
| A-10 | 图1 | 无文件 | `null` |
| B-09 | 图1（算盘） | `原始资料/题图/B-09_图1.png`（780×314 那版） | 填路径 + 哈希 |
| B-12 | 图1 | 无文件 | `null` |
| B-20 | 图甲 | `原始资料/题图/B-20_图甲.png` | 填路径 + 哈希 |
| B-20 | 图乙（a–F） | `原始资料/题图/B-20_图乙.png` | 填路径 + 哈希 |

**文件名的 `图` 字是真实存在的**（`B-20_图乙.png`），不要改成 `B-20_2.png`，也不要复制一份出来——原型侧已有 `FIG_ALIAS` 映射，改代码不改资产。

**哈希必须由脚本现算**（`_build_examples.py` 里读文件字节算），不许手抄。手抄的哈希下次就是假值。

## 4. 不许做的事

1. **不许复制/移动/重命名任何图文件**。本卡只读图。
2. **不许为了过校验把 `file_sha256` 填成常量或空串**。
3. **不许把 `file` 写成绝对路径**（换机器就失效）。
4. **不许顺手改 `input_sha256` 的算法**。图哈希是独立字段，不并进已有指纹——并进去会让 7 份样例的 `input_sha256` 全变，而 `stem_sha256` 又不动，三套哈希互相打架。
5. **不许动 `l4_condition.py`**。本卡只改契约与校验，不改判定逻辑。

## 5. 完成判据（贴命令输出，不接受「已完成」）

```bash
cd "D:/峤的个人档案/做点东西/物理解题agent"
# 1 七份样例全过
for f in schema/examples/*.json; do python schema/validate_schema.py "$f" | tail -1; done
# 2 生成器幂等（连跑两次哈希相同）
python schema/_build_examples.py && md5sum schema/examples/*.json > /tmp/a
python schema/_build_examples.py && md5sum schema/examples/*.json > /tmp/b
diff /tmp/a /tmp/b && echo "幂等 OK"
# 3 负例：改 file_sha256 一个字符 → 必须 E
# 4 负例：把一个 discussion 步的 criterion 与 equation 都置 null → 必须 E（R18）
# 5 负例：把 file 指向不存在路径 → 必须 E（R17）
# 6 回归不受影响
python 采分点/scripts/validate_points.py "原始资料/五卷力学大题_采分点总表_v2.xlsx" --strict
python 知识表/check_formula_lib.py
python 知识表/check_laws.py
python 验证器/tests/audit_regression.py
python 验证器/tests/l4_regression.py
python 原型/_build.py && python 原型/_selftest.py
```

- [ ] 7/7 样例 E0（W 允许，缺图题会有 W-fig 警告）
- [ ] 生成器幂等
- [ ] **4 条负例全部报 E 并退出 1**（第 3/4/5 条加一条自造：把 `file` 与 `file_sha256` 填成不一致）
- [ ] 五项回归全 0；原型自测 17/17
- [ ] CHANGELOG 写清：为什么加、加了什么、7 份样例哈希全变是预期的
- [ ] 报告里**逐条列出每张图的 `file_sha256` 前 12 位**，供 T00 抽样复算

## 6. 交货位置

- `schema/answer.schema.json`（升 1.2.1）
- `schema/_build_examples.py`（算 file 与哈希）
- `schema/validate_schema.py`（R16/R17/R18 + W-fig）
- `schema/CHANGELOG.md`（新增 1.2.1 段）
- `子agent/回执_T08e.md`（贴 §5 全部命令输出）
