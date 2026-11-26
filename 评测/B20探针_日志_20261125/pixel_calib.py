# 仅为 §3.5 服务：给 pixel_digitize.py 的现有函数提供「量出来的」轴定标。
# 算法不变，只换了 box / 颜色 / 值域；定标来源全部打印出来，可复现。
import sys
sys.path.insert(0, r"D:/峤的个人档案/做点东西/_vlm_local")
from pixel_digitize import digitize, fit
from PIL import Image

IMG = r"D:/峤的个人档案/做点东西/物理解题agent/原始资料/题图/B-20_图乙.png"
im = Image.open(IMG).convert("RGB")
W, H = im.size
px = im.load()


def is_cyan(p):
    r, g, b = p
    return r < 110 and g > 110 and b > 170 and b - r > 90


def is_dark(p):
    r, g, b = p
    return r < 90 and g < 90 and b < 90


def clusters(idx):
    idx = sorted(idx)
    out, cur = [], [idx[0]]
    for k in idx[1:]:
        if k - cur[-1] <= 3:
            cur.append(k)
        else:
            out.append((cur[0], cur[-1], (cur[0] + cur[-1]) / 2))
            cur = [k]
    out.append((cur[0], cur[-1], (cur[0] + cur[-1]) / 2))
    return out


# 1) 青色虚线：竖线=x 定标（F=4 / F=8 标注点），横线=y 定标（a=2 / a=6）
cy_cols = [x for x in range(W) if sum(1 for y in range(H) if is_cyan(px[x, y])) > 30]
cy_rows = [y for y in range(H) if sum(1 for x in range(W) if is_cyan(px[x, y])) > 30]
cx = clusters(cy_cols)
cy = clusters(cy_rows)
print("青色竖线簇:", cx, " 青色横线簇:", cy)

# 2) 黑色坐标轴：竖轴列 / 横轴行
vax = max(range(80, 200), key=lambda x: sum(1 for y in range(180, 870) if is_dark(px[x, y])))
hax = max(range(800, 900), key=lambda y: sum(1 for x in range(100, 940) if is_dark(px[x, y])))
print("竖直轴 x=%d  水平轴 y=%d" % (vax, hax))

# 3) 三组已知点做最小二乘，得到仿射定标
#    x: (竖轴, F=0) (F=4 虚线) (F=8 虚线)
xs = [vax, cx[0][2], cx[1][2]]
fs = [0.0, 4.0, 8.0]
ys = [hax, cy[1][2], cy[0][2]]   # y 越大 a 越小：a=0 在 hax，a=2 在下方虚线，a=6 在上方虚线
as_ = [0.0, 2.0, 6.0]


def linfit(pxs, vals):
    n = len(pxs)
    sp, sv = sum(pxs), sum(vals)
    spp = sum(p * p for p in pxs)
    spv = sum(p * v for p, v in zip(pxs, vals))
    den = n * spp - sp * sp
    k = (n * spv - sp * sv) / den
    b = (sv - k * sp) / n
    return k, b


kx, bx = linfit(xs, fs)
ky, by = linfit(ys, as_)
print("x 定标: F = %.6f*x + %.4f   (%.3f px/N)" % (kx, bx, 1 / kx))
print("y 定标: a = %.6f*y + %.4f   (%.3f px/单位)" % (ky, by, -1 / ky))
print("  校验: x=0@%.1f  F=4@%.1f  F=8@%.1f | a=0@%.1f  a=2@%.1f  a=6@%.1f"
      % (-bx / kx, (4 - bx) / kx, (8 - bx) / kx,
         -by / ky, (2 - by) / ky, (6 - by) / ky))

# 4) 交给原有函数：box=(L,R,T,B), fmax, amax
FMAX, AMAX = 8.0, 8.0
L = (0 - bx) / kx
R = (FMAX - bx) / kx
B = (0 - by) / ky
T = (AMAX - by) / ky
print("box=(%.1f, %.1f, %.1f, %.1f) fmax=%.1f amax=%.1f" % (L, R, T, B, FMAX, AMAX))

rows = digitize(IMG, (L, R, T, B), FMAX, AMAX, color=(180, 50, 120), tol=60)
print("提取点数(F列去重):", len(rows))
print("F 范围: %.3f ~ %.3f" % (rows[0][0], rows[-1][0]))

s1 = fit(rows, 0.2, 3.6)
s2 = fit(rows, 4.4, 8.6)
print("第一段(0.2~3.6):", s1)
print("第二段(4.4~8.6):", s2)
if s1 and s2:
    cross = (s1["b"] - s2["b"]) / (s2["k"] - s1["k"])
    print("--- 四值 ---")
    print("折点 F = %.3f  (真值 4)" % cross)
    print("折点 a = %.3f" % (s1["k"] * cross + s1["b"]))
    print("k1 = %.4f (真值 0.5) 误差 %.1f%%" % (s1["k"], abs(s1["k"] - 0.5) / 0.5 * 100))
    print("k2 = %.4f (真值 1.0) 误差 %.1f%%" % (s2["k"], abs(s2["k"] - 1.0) / 1.0 * 100))
    print("b2 = %.4f (真值 -2.0) 误差 %.1f%%" % (s2["b"], abs(s2["b"] + 2.0) / 2.0 * 100))
