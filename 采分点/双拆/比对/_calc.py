# -*- coding: utf-8 -*-
"""按《一致率口径_v1.md》计算两档一致率。

用法：
    python 比对/_calc.py [边表路径]                 # 全 10 题（默认，行为不变）
    python 比对/_calc.py [边表路径] A-08,A-09      # 剔除指定题后的净样本

第 2 个可选参数由 T00 独立审核（2026-11-25 10:26）加入：A-08 封存后读到过
B 侧结论、A-09 的 B 侧经用户认定分值，两题都不作独立性证据，报数时应剔除。
不改默认调用，原报告的数仍可原样复现。
"""
import csv, sys, os
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
EDGE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, '边表_v1.csv')
EXCLUDE = set(sys.argv[2].split(',')) if len(sys.argv) > 2 else set()
T = ['A-08','A-09','A-10','B-01','B-02','B-06','B-09','B-12','B-17','B-19']
T = [t for t in T if t not in EXCLUDE]

def steps(path):
    with open(path, encoding='utf-8-sig') as f:
        return [r for r in csv.DictReader(f)]

# 步数
Na, Nb = {}, {}
for t in T:
    Na[t] = len(steps(os.path.join(ROOT, '%s.csv' % t)))

import openpyxl, re
PROJ = os.path.dirname(os.path.dirname(ROOT))
wb = openpyxl.load_workbook(os.path.join(PROJ, '原始资料', '五卷力学大题_采分点总表_v2.xlsx'),
                            read_only=True, data_only=True)
ws = wb['采分点总表']
for r in list(ws.iter_rows(values_only=True))[1:]:
    pid = str(r[0] or '')
    m = re.match(r'^([A-B]-\d+)-S(\d+)$', pid)
    if m and m.group(1) in T:
        Nb[m.group(1)] = max(Nb.get(m.group(1), 0), int(m.group(2)))
wb.close()

# 读边
edges = defaultdict(list)
with open(EDGE, encoding='utf-8-sig') as f:
    for r in csv.DictReader(f):
        edges[r['题号']].append((int(r['A侧步']), int(r['B侧步'])))

# 分值（用于加权 Dice）
WA, WB = {}, {}
for t in T:
    WA[t] = {int(r['步']): float(r['分值']) for r in steps(os.path.join(ROOT, '%s.csv' % t))}
wb = openpyxl.load_workbook(os.path.join(PROJ, '原始资料', '五卷力学大题_采分点总表_v2.xlsx'),
                            read_only=True, data_only=True)
ws = wb['采分点总表']
WB = defaultdict(dict)
for r in list(ws.iter_rows(values_only=True))[1:]:
    m = re.match(r'^([A-B]-\d+)-S(\d+)$', str(r[0] or ''))
    if m and m.group(1) in T:
        WB[m.group(1)][int(m.group(2))] = float(r[8] or 0)
wb.close()

def best_w(wa, wb):
    """分量内最大权重一对一匹配：边权 = min(a分值, b分值)。分量节点数 <=5，暴力即可。"""
    from itertools import permutations
    if len(wa) > len(wb):
        wa, wb = wb, wa
    if not wa:
        return 0
    return max(sum(min(wa[i], wb[p[i]]) for i in range(len(wa)))
               for p in permutations(range(len(wb)), len(wa)))

def components(pairs, na, nb):
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry: parent[rx] = ry
    for i in range(1, na+1): find(('a', i))
    for j in range(1, nb+1): find(('b', j))
    for i, j in pairs: union(('a', i), ('b', j))
    groups = defaultdict(list)
    for node in list(parent):
        groups[find(node)].append(node)
    return list(groups.values())

rows = []
for t in T:
    cn = components(edges.get(t, []), Na[t], Nb[t])
    comps = [(sum(1 for n in c if n[0] == 'a'), sum(1 for n in c if n[0] == 'b')) for c in cn]
    na, nb = Na[t], Nb[t]
    M = sum(min(a, b) for a, b in comps)
    K = sum(1 for a, b in comps if a >= 1 and b >= 1)
    nna = K + sum(a for a, b in comps if b == 0)
    nnb = K + sum(b for a, b in comps if a == 0)
    ps = 2 * M / (na + nb)
    pn = 2 * K / (nna + nnb)
    # 加权用「分量内 Σ分值取较小侧」：一对一 min 会系统性惩罚「一方拆细」，见口径 §4 注
    sw = sum(min(sum(WA[t].get(n[1], 0) for n in c if n[0] == 'a'),
               sum(WB[t].get(n[1], 0) for n in c if n[0] == 'b')) for c in cn)
    pw = 2 * sw / (sum(WA[t].values()) + sum(WB[t].values()))
    rows.append(dict(t=t, na=na, nb=nb, M=M, K=K, nna=nna, nnb=nnb, ps=ps, pn=pn, pw=pw, sw=sw,
                     lone_a=[(a, b) for a, b in comps if b == 0],
                     lone_b=[(a, b) for a, b in comps if a == 0],
                     comps=comps))

def agg(rs):
    na = sum(r['na'] for r in rs); nb = sum(r['nb'] for r in rs)
    M = sum(r['M'] for r in rs); K = sum(r['K'] for r in rs)
    nna = sum(r['nna'] for r in rs); nnb = sum(r['nnb'] for r in rs)
    sw = sum(r['sw'] for r in rs)
    tw = sum(sum(WA[r['t']].values()) + sum(WB[r['t']].values()) for r in rs)
    return 2*M/(na+nb), 2*K/(nna+nnb), 2*sw/tw, na, nb, M, K, nna, nnb

print('=' * 104)
print('%-6s %4s %4s %4s %5s %9s %9s %8s %9s' % ('题号','Na','Nb','M','K','P_strict','P_norm','粒度差','分值加权'))
print('-' * 104)
for r in rows:
    print('%-6s %4d %4d %4d %5d %8.2f%% %8.2f%% %+7.2f%% %8.2f%%' % (
        r['t'], r['na'], r['nb'], r['M'], r['K'], r['ps']*100, r['pn']*100, (r['pn']-r['ps'])*100, r['pw']*100))
print('-' * 104)
ps, pn, pw, na, nb, M, K, nna, nnb = agg(rows)
print('%-6s %4d %4d %4d %5d %8.2f%% %8.2f%% %+7.2f%% %8.2f%%' % ('合计', na, nb, M, K, ps*100, pn*100, (pn-ps)*100, pw*100))
print()
sub = [r for r in rows if r['t'] != 'A-09']
ps2, pn2, pw2, na2, nb2, M2, K2, nna2, nnb2 = agg(sub)
print('剔除 A-09（B 侧非独立产出）后 %d 题：' % len(sub))
print('  N_a=%d  N_b=%d  M=%d  K=%d  n_a\'=%d  n_b\'=%d' % (na2, nb2, M2, K2, nna2, nnb2))
print('  P_strict = %.2f%%   P_norm = %.2f%%   分值加权 = %.2f%%   闸(70%%)：%s' % (
    ps2*100, pn2*100, pw2*100, '过' if pn2 >= 0.7 else '不过'))
print()
print('缺口（单边分量）：')
for r in rows:
    for a, b in r['lone_a']:
        print('  [A独有] %s  a侧%d步  b侧0步' % (r['t'], a))
    for a, b in r['lone_b']:
        print('  [B独有] %s  a侧0步  b侧%d步' % (r['t'], b))
