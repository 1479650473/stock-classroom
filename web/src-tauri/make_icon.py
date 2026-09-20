# -*- coding: utf-8 -*-
"""生成应用主图标（1024×1024 PNG）：
深色圆角底 + 金色 K 线柱 + 趋势线，风格与软件主题（石墨/金）一致。
输出：web/src-tauri/app-icon.png（交给 `cargo tauri icon` 生成全平台图标集）
"""
from PIL import Image, ImageDraw
import math
import os

S = 1024
SS = 4                      # 超采样倍数（先画 4 倍再缩，边缘更干净）
W = S * SS
img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# ── 圆角底：深色渐变（上浅下深）+ 极细金边 ──
r = int(W * 0.22)
grad = Image.new("RGBA", (1, W))
for y in range(W):
    t = y / W
    # 从 #1B1F26 到 #0B0D11
    top = (27, 31, 38)
    bot = (11, 13, 17)
    c = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
    grad.putpixel((0, y), c + (255,))
grad = grad.resize((W, W))
mask = Image.new("L", (W, W), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, W - 1], radius=r, fill=255)
img.paste(grad, (0, 0), mask)

# 金色内描边（1.5px * SS）
d.rounded_rectangle([int(W*0.012), int(W*0.012), W - int(W*0.012), W - int(W*0.012)],
                    radius=int(r * 0.92), outline=(212, 165, 116, 60), width=int(1.6 * SS))

GOLD = (212, 165, 116, 255)
GOLD_SOFT = (212, 165, 116, 150)
RED = (229, 72, 77, 255)          # A股：涨=红
GREEN = (63, 185, 80, 255)        # 跌=绿

# ── K 线柱：5 根，红绿交替，整体上升 ──
pad = int(W * 0.135)
inner = W - pad * 2
n = 5
slot = inner / n
bw = slot * 0.50                      # 实体宽
base_y = int(W * 0.79)
heights = [0.20, 0.32, 0.44, 0.58, 0.70]      # 实体高度占比
wick_top = [0.13, 0.25, 0.34, 0.48, 0.60]
for i in range(n):
    cx = pad + slot * (i + 0.5)
    body_h = inner * heights[i]
    top = base_y - body_h
    color = RED if i % 2 == 0 else GREEN
    # 影线
    wy0 = base_y - inner * (wick_top[i] + 0.06)
    d.line([(cx, wy0), (cx, base_y)], fill=color, width=int(S * 0.016))
    # 实体（圆角）
    d.rounded_rectangle([cx - bw / 2, top, cx + bw / 2, base_y],
                        radius=int(bw * 0.18), fill=color)

# ── 趋势线：金色折线，穿过柱顶，末尾加一点 ──
pts = [(pad + slot * (i + 0.5), base_y - inner * (wick_top[i] + 0.06) - inner * 0.045)
       for i in range(n)]
d.line(pts, fill=GOLD, width=int(S * 0.038), joint="curve")
# 端点圆
lx, ly = pts[-1]
d.ellipse([lx - S * 0.045, ly - S * 0.045, lx + S * 0.045, ly + S * 0.045], fill=GOLD)
d.ellipse([lx - S * 0.018, ly - S * 0.018, lx + S * 0.018, ly + S * 0.018],
          fill=(11, 13, 17, 255))

# ── 细网格（底部，弱化）──
for i in range(1, 4):
    y = base_y + int(inner * 0.09 * i)
    d.line([(pad, y), (W - pad, y)], fill=(255, 255, 255, 14), width=int(1.2 * SS))

# 顶部一抹金晕，增加"发光"质感
glow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
gd.ellipse([W * 0.18, -W * 0.35, W * 0.82, W * 0.45], fill=(212, 165, 116, 26))
glow = glow.filter(__import__("PIL.ImageFilter", fromlist=["GaussianBlur"]).GaussianBlur(W * 0.05))
img = Image.alpha_composite(img, glow)

# 缩回 1024 并输出
out = img.resize((S, S), Image.LANCZOS)
dst = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app-icon.png")
out.save(dst)
print("已生成", dst, out.size)
