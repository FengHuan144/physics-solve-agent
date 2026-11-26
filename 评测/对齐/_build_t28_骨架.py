# -*- coding: utf-8 -*-
"""T28：生成 7 题 66 点核对表骨架。只拼三方数据，判分列全部留 `—`。
输入（只读）：
  原始资料/五卷力学大题_采分点总表_v2.xlsx → 采分点总表[分值, 判分口径]
  schema/examples/{qid}.json → steps[].kind
  评测/对齐/T20步点对齐_v2.json → items[].points[home, by, note, closest, gap]
输出：评测/对齐/核对表_7题66点_骨架_20261125.md
"""
import json
import sys
from datetime import datetime

import openpyxl

sys.stdout.reconfigure(encoding='utf-8')

Q7 = ('A-02', 'A-08', 'A-10', 'B-02', 'B-09', 'B-12', 'B-20')
# 闸③ 的期望：题 -> (点数, 分)
EXPECT = {
    'A-02': (15, 20.0), 'A-08': (11, 19.0), 'A-10': (8, 12.0),
    'B-02': (6, 9.0), 'B-09': (7, 11.0), 'B-12': (9, 11.0), 'B-20': (10, 14.0),
}
OUT = '评测/对齐/核对表_7题66点_骨架_20261125.md'
DASH = '—'
EMPTY_COLS = [DASH] * 6  # 判分器credit / score / 判分器by / basis / 一致? / 裁定


def esc(s: str) -> str:
    """表格单元格转义：竖线会冲散列。"""
    return str(s).replace('|', '\\|')


def num(x: float):
    return int(x) if float(x).is_integer() else x


# ---------- 读三方 ----------
wb = openpyxl.load_workbook('原始资料/五卷力学大题_采分点总表_v2.xlsx', data_only=True)
ws = wb['采分点总表']
H = [c.value for c in ws[1]]
tab = {}
for r in ws.iter_rows(min_row=2, values_only=True):
    pid = r[0]
    if pid and str(pid).split('-S')[0] in Q7:
        pid = str(pid)
        if pid in tab:
            sys.exit(f'[停] 总表重复 point_id: {pid}')
        tab[pid] = {
            'fen': float(r[H.index('分值')]),
            'kou': r[H.index('判分口径')],
        }

kind = {}
for q in Q7:
    for s in json.load(open(f'schema/examples/{q}.json', encoding='utf-8'))['steps']:
        kind[s['step_id']] = s.get('kind')

al = json.load(open('评测/对齐/T20步点对齐_v2.json', encoding='utf-8'))
apts = {}
for it in al['items']:
    for p in it['points']:
        if p['point_id'] in apts:
            sys.exit(f'[停] 对齐表重复 point_id: {p["point_id"]}')
        apts[p['point_id']] = p

# ---------- 闸①再确认（不相等直接停）----------
if not (set(tab) == set(kind) == set(apts)):
    sys.exit('[停] 三方键集不相等，见 临时/t28_verify.py 输出')
if len(tab) != 66:
    sys.exit(f'[停] 键数 {len(tab)} != 66')

# 每题按步序
by_q = {q: sorted([p for p in tab if p.split('-S')[0] == q]) for q in Q7}
for q in Q7:
    n, f = EXPECT[q]
    got_n, got_f = len(by_q[q]), sum(tab[p]['fen'] for p in by_q[q])
    if (got_n, got_f) != (n, f):
        sys.exit(f'[停] {q} 实得 {got_n} 点 / {got_f} 分，期望 {n} 点 / {f} 分')


def render_by(pid, by):
    """[S01,S02] 形式；空列表照实写 []，不改写、不补。"""
    if not by:
        return '[]'
    return '[' + ','.join('S' + b.split('-S')[-1] for b in by) + ']'


def render_note(p):
    parts = []
    note = (p.get('note') or '').strip()
    if note:
        parts.append(note)
    tail = []
    if p.get('closest'):
        tail.append('closest=' + str(p['closest']).strip())
    if p.get('gap'):
        tail.append('gap=' + str(p['gap']).strip())
    if tail:
        parts.append('; '.join(tail))
    return '；'.join(parts) if parts else DASH


# ---------- 拼 markdown ----------
L = []
A = L.append
A('# 7 题 66 点核对表（骨架）')
A('')
A('> **用途**：`T25` S4 逐点 diff 的底表。本文件只把三方已知数据拼到一张表里，**不含任何判定**。')
A('> **生成**：2026-11-25 · `T28`（骨架）。输入三份，只读：')
A('> `原始资料/五卷力学大题_采分点总表_v2.xlsx`（`采分点总表`）／`schema/examples/{qid}.json`（`steps[]`）／`评测/对齐/T20步点对齐_v2.json`（`items[].points[]`）。')
A('> **右侧 6 列全部为 `—`**（`判分器credit` / `score` / `判分器by` / `basis` / `一致?` / `裁定`），只由 S4 填。')
A('')
A('## 读表约定')
A('')
A('- `分值`：总表 `分值` 列原值。逐题小计与卷面分对得上（见各节标题）。')
A('- `kind`：金标 `steps[].kind` —— `equation` / `value` / `judgment` / `discussion` / `critical`。')
A('- `金标步`：承载该点的金标步。本批 66 点均为 1:1，值与 `point_id` 相同。')
A('- `人工home`：对齐表 `points[].home` 原值，四种 —— `1:1` / `1:n` / `none` / `merged`，一字未改。')
A('- `人工by`：对齐表 `points[].by`，缩写成 `[S01,S02]`（`S` 后为步序），顺序照 JSON 原序。`[]` = 该点 `by` 为空（`home` 为 `none` 时出现）。')
A('- `人工备注`：对齐表 `note`；`closest` / `gap` 非空时追加为 `closest=…; gap=…`。无备注写 `—`。')
A('- 判分口径**不进主表**（长文本与本批 `B-02-S06` 含 `|`，会冲散列），66 段逐字收在附录 A。')
A('')
A('## 主表（7 节 / 66 行）')
A('')

for q in Q7:
    n, f = EXPECT[q]
    A(f'### {q}（{n} 点 / {num(f)} 分）')
    A('')
    A('| point_id | 分值 | kind | 金标步 | 人工home | 人工by | 人工备注 | 判分器credit | score | 判分器by | basis | 一致? | 裁定 |')
    A('|---|---|---|---|---|---|---|---|---|---|---|---|---|')
    for pid in by_q[q]:
        p = apts[pid]
        cells = [
            pid, str(num(tab[pid]['fen'])), kind[pid], pid,
            str(p.get('home')), render_by(pid, p.get('by') or []),
            esc(render_note(p)),
        ] + EMPTY_COLS
        A('| ' + ' | '.join(cells) + ' |')
    A('')

A('## 附录 A：逐点判分口径原文（66 段）')
A('')
A('> 逐字照抄总表 `判分口径` 列。不改写、不压缩、不改标点；错别字也照抄。')
A('')

for q in Q7:
    A(f'### {q}')
    A('')
    for pid in by_q[q]:
        kou = tab[pid]['kou']
        A(f'**{pid}**（{num(tab[pid]["fen"])} 分）')
        A('')
        if kou is None or str(kou).strip() == '':
            A('> （总表此列为空）')
        else:
            for line in str(kou).split('\n'):
                A('> ' + line)
        A('')

md = '\n'.join(L).rstrip() + '\n'
with open(OUT, 'w', encoding='utf-8', newline='\n') as fh:
    fh.write(md)

rows = sum(1 for line in md.splitlines() if line.startswith('| ') and line.split('|')[1].strip().startswith(tuple(Q7)))
print(f'[ok] 写出 {OUT}')
print(f'[ok] 主表数据行 {rows}（期望 66）；字节 {len(md.encode("utf-8"))}')
print(f'[ok] 分值合计 {sum(tab[p]["fen"] for p in tab)}（期望 96.0）')
