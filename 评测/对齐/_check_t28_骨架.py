# -*- coding: utf-8 -*-
"""T28 闸 ②③④⑤ 校验：对生成的骨架做独立复核（不依赖生成器内部状态，重新解析 md + xlsx）。"""
import re
import sys

import openpyxl

sys.stdout.reconfigure(encoding='utf-8')

Q7 = ('A-02', 'A-08', 'A-10', 'B-02', 'B-09', 'B-12', 'B-20')
EXPECT = {
    'A-02': (15, 20.0), 'A-08': (11, 19.0), 'A-10': (8, 12.0),
    'B-02': (6, 9.0), 'B-09': (7, 11.0), 'B-12': (9, 11.0), 'B-20': (10, 14.0),
}
MD = '评测/对齐/核对表_7题66点_骨架_20261125.md'
DASH = '—'

lines = open(MD, encoding='utf-8').read().splitlines()

# ---------- 解析主表 ----------
rows = []          # (section_q, [cells])
sec = None
for ln in lines:
    m = re.match(r'^### ([AB]-\d\d)（(\d+) 点 / (\d+) 分）$', ln)
    if m:
        sec = m.group(1)
        EXPECT[sec] = EXPECT[sec]  # 保留期望，另存实际
        continue
    if ln.startswith('| ') and re.match(r'^\| [AB]-\d\d-S\d\d ', ln):
        cells = [c.strip() for c in ln.strip().strip('|').split('|')]
        rows.append((sec, cells))

print(f'闸② 主表数据行数: {len(rows)}（期望 66）')

# 逐题点数/分值与步序
ok2 = len(rows) == 66
for q in Q7:
    rq = [c for s, c in rows if s == q]
    n_exp, f_exp = EXPECT[q]
    fen = sum(float(c[1]) for c in rq)
    steps = [int(c[0].split('-S')[1]) for c in rq]
    good = (len(rq) == n_exp and abs(fen - f_exp) < 1e-9 and steps == list(range(1, n_exp + 1)))
    ok2 &= good
    print(f'   {q}: {len(rq)} 点 / {fen:g} 分（期望 {n_exp} / {f_exp:g}）步序 {steps[0]}..{steps[-1]} 连续升序={steps == list(range(1, n_exp + 1))} -> {"OK" if good else "FAIL"}')
print(f'闸② 结论: {"PASS" if ok2 else "FAIL"}')

print()
print(f'闸③ 分值合计: {sum(float(c[1]) for s, c in rows):g}（期望 96）逐题小计见上 -> {"PASS" if abs(sum(float(c[1]) for s, c in rows) - 96.0) < 1e-9 and ok2 else "FAIL"}')

# ---------- 闸⑤ 右侧 6 列 ----------
print()
bad5 = []
for s, c in rows:
    tail = c[7:]
    if len(tail) != 6:
        bad5.append((c[0], 'col_count', len(c)))
        continue
    for v in tail:
        if v != DASH:
            bad5.append((c[0], v))
print(f'闸⑤ 右侧 6 列检查: {len(rows) * 6} 个单元格，违规 {len(bad5)} 个')
for b in bad5[:10]:
    print('   ', b)
print(f'闸⑤ 结论: {"PASS" if not bad5 else "FAIL"}')

# 全书不得出现 待填/TBD/?
suspect = [ln[:60] for ln in lines if re.search(r'待填|TBD|TODO|\?\?\?', ln)]
print(f'   全书扫描 待填/TBD/TODO: {len(suspect)} 处 -> {"PASS" if not suspect else suspect}')

# ---------- 闸④ 抽查 5 点，逐字 diff ----------
wb = openpyxl.load_workbook('原始资料/五卷力学大题_采分点总表_v2.xlsx', data_only=True)
ws = wb['采分点总表']
H = [c.value for c in ws[1]]
kou = {}
for r in ws.iter_rows(min_row=2, values_only=True):
    if r[0]:
        kou[str(r[0])] = r[H.index('判分口径')]

# 解析附录 A
app = {}
cur = None
buf = []
for ln in lines:
    m = re.match(r'^\*\*([AB]-\d\d-S\d\d)\*\*（(\d+) 分）$', ln)
    if m:
        if cur:
            app[cur] = '\n'.join(buf)
        cur = m.group(1)
        buf = []
        continue
    if cur and ln.startswith('> '):
        buf.append(ln[2:])
    elif cur and ln == '>':
        buf.append('')
if cur:
    app[cur] = '\n'.join(buf)

print(f'\n附录 A 解析到 {len(app)} 段（期望 66）')

SAMPLE = ['A-02-S01', 'B-02-S06', 'A-08-S10', 'B-09-S04', 'B-20-S05']
print(f'闸④ 抽查 {len(SAMPLE)} 点（含含竖线的 B-02-S06、合并步的 B-20-S05）:')
ok4 = True
for pid in SAMPLE:
    a = app.get(pid)
    b = kou.get(pid)
    same = (a == str(b))
    ok4 &= same
    print(f'   {pid}: {"逐字全等" if same else "不等"}  len(md)={len(a) if a is not None else None} len(xlsx)={len(str(b))}')
    if not same:
        print('     md  :', repr(a))
        print('     xlsx:', repr(b))
print(f'闸④ 结论: {"PASS" if ok4 else "FAIL"}')

# 附录完整性：只跟 7 题那 66 个键比（总表有 27 题 224 行，不能整表比）
kou66 = {k: v for k, v in kou.items() if k.split('-S')[0] in Q7}
print(f'   附录键集 vs 总表 66 键: {"相等" if set(app) == set(kou66) else "不等 " + str(set(kou66) ^ set(app))}')
# 66 段全部逐字比对（不止抽查 5 点）
full = [p for p in app if app[p] != str(kou66.get(p))]
print(f'   附录 66 段全量逐字比对: {"66/66 全等" if not full else str(len(full)) + " 段不等: " + str(full[:5])}')

# 主表键集 vs 附录
print(f'   主表键集 vs 附录: {"相等" if {c[0] for s, c in rows} == set(app) else "不等"}')
