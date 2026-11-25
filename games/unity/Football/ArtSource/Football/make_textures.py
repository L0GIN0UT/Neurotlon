"""Процедурные текстуры футбольной полосы: конус, сетка ворот, чехол ворот, круглая мишень.

Запуск: uv run --with pillow --with numpy --with scipy python -I make_textures.py <папка вывода> [<папка Poly Haven>]
Файлы: cone_albedo.png, cone_normal.png, net.png (RGBA, бесшовная), target_rings.png, goal_tarp.png и, если даны два последних
аргумента, grass_albedo.png, grass_normal.png и stripes.png (газон).
Всегда: ball_albedo.png и ball_normal.png (мяч, рисуется математически).
Шрифт цифр — встроенный шрифт Pillow (Aileron, общественное достояние); чужих изображений нет.
"""
import math
import sys
from pathlib import Path

import numpy as np
import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

RNG = np.random.RandomState(21)


def smooth_noise(h, w, cells, rng):
    g = rng.rand(cells, cells).astype(np.float32)
    img = Image.fromarray((g * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
    img = img.filter(ImageFilter.GaussianBlur(max(1.0, w / cells * 0.55)))      # без «кубиков» при малом числе клеток
    return np.asarray(img, dtype=np.float32) / 255.0


def normal_from_height(height, strength):
    gx = np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)
    gy = np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)
    nx, ny, nz = -gx * strength, gy * strength, np.ones_like(height)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    n = np.stack([nx / ln * 0.5 + 0.5, ny / ln * 0.5 + 0.5, nz / ln * 0.5 + 0.5], axis=2)
    return (n * 255).astype(np.uint8)


# ---------------- конус ----------------
def cone(out: Path, size=1024):
    """v (по вертикали) идёт от основания (0) к вершине (1); u — вокруг конуса."""
    h = w = size
    rng = np.random.RandomState(5)
    base = np.array([0.95, 0.23, 0.02], dtype=np.float32)
    lowfreq = smooth_noise(h, w, 6, rng) * 0.10 + smooth_noise(h, w, 24, rng) * 0.05
    img = np.empty((h, w, 3), dtype=np.float32)
    img[:] = base
    img *= (0.92 + lowfreq)[..., None]
    v = 1.0 - (np.arange(h, dtype=np.float32) + 0.5) / h                                            # 0 внизу, 1 вверху
    dirt = np.clip(1.0 - v * 4.0, 0, 1)[:, None]                                                      # грязь у основания
    img *= (1.0 - 0.45 * dirt * (0.4 + smooth_noise(h, w, 40, rng)))[..., None]
    # светоотражающая полоса
    band = ((v > 0.56) & (v < 0.70)).astype(np.float32)[:, None]
    edge = np.clip(np.minimum(v - 0.56, 0.70 - v) / 0.008, 0, 1)[:, None]
    white = np.array([0.80, 0.80, 0.80], dtype=np.float32) * (0.92 + 0.08 * smooth_noise(h, w, 120, rng))[..., None]
    img = img * (1 - band * edge)[..., None] + white * (band * edge)[..., None]
    # царапины и потёртости
    im = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))
    d = ImageDraw.Draw(im, "RGBA")
    for _ in range(260):
        x, y = rng.randint(0, w), rng.randint(int(h * 0.02), int(h * 0.7))
        ln = rng.randint(10, 70)
        a = rng.uniform(0, math.pi)
        d.line((x, y, x + math.cos(a) * ln, y + math.sin(a) * ln * 0.3), fill=(255, 235, 215, int(rng.randint(20, 80))), width=1)
    im.save(out / "cone_albedo.png")
    # нормали: рёбра у основания и микропризматический рисунок на светоотражающей полосе
    hh = np.zeros((h, w), dtype=np.float32)
    uu = (np.arange(w, dtype=np.float32) + 0.5) / w
    ribs = (0.5 + 0.5 * np.cos(uu * 2 * math.pi * 24))[None, :] * np.clip(1.0 - v * 8.0, 0, 1)[:, None]
    hh += 0.6 * ribs
    px = np.arange(w)[None, :] / 16.0
    py = np.arange(h)[:, None] / 16.0
    prism = 0.5 + 0.5 * np.cos(2 * math.pi * px) * np.cos(2 * math.pi * (py + px * 0.5))
    hh += (band * 0.8) * prism
    hh += 0.08 * smooth_noise(h, w, 200, rng)
    Image.fromarray(normal_from_height(hh, 2.2)).save(out / "cone_normal.png")


# ---------------- сетка ворот: бесшовная плитка, прозрачный фон ----------------
def net(out: Path, size=576):
    """узловая ромбовидная сетка: две системы нитей под ±45° и узлы на пересечениях."""
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32)
    period = size / 3.0                                    # три ромба в плитке по каждой оси
    thread = 6.5
    d1 = np.abs(((xs + ys) % period) - period / 2)          # расстояние до нити первой системы
    d2 = np.abs(((xs - ys) % period) - period / 2)
    a1 = np.clip(1.0 - (np.minimum(d1, period - d1) - 0) / thread, 0, 1)
    d1m = np.minimum(((xs + ys) % period), period - ((xs + ys) % period))
    d2m = np.minimum(((xs - ys) % period), period - ((xs - ys) % period))
    t1 = np.clip(1.0 - d1m / thread, 0, 1)
    t2 = np.clip(1.0 - d2m / thread, 0, 1)
    alpha = np.maximum(t1, t2)
    knot = np.clip(1.0 - np.sqrt(d1m ** 2 + d2m ** 2) / (thread * 2.1), 0, 1)
    alpha = np.maximum(alpha, knot)
    twist = 0.88 + 0.12 * np.sin((xs + ys) * 0.9) * np.sin((xs - ys) * 0.9)
    rgb = np.stack([twist * 0.93, twist * 0.93, twist * 0.94], axis=-1)
    rgba = np.concatenate([rgb, np.clip(alpha, 0, 1)[..., None]], axis=-1)
    Image.fromarray((np.clip(rgba, 0, 1) * 255).astype(np.uint8), "RGBA").save(out / "net.png")


# ---------------- ограждающая сетка за зоной остановки: толстое канатное плетение ----------------
# Плитка 0,3 × 0,3 м (UV в build_football.py: cell=0,3): канат ≈ 2,5 см (8 % плитки) виден и с 12 м. Бесшовная.
def stop_net(out: Path, size=256):
    ss = 4
    n = size * ss
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    rope = int(n * 0.08)
    for k in (0, n):                                                         # линии на границах плитки рисуем с двух сторон — бесшовно
        d.rectangle((k - rope // 2, 0, k + rope // 2, n), fill=(255, 255, 255, 255))
        d.rectangle((0, k - rope // 2, n, k + rope // 2), fill=(255, 255, 255, 255))
    for k in (n // 2,):
        d.rectangle((k - rope // 2, 0, k + rope // 2, n), fill=(255, 255, 255, 255))
        d.rectangle((0, k - rope // 2, n, k + rope // 2), fill=(255, 255, 255, 255))
    # складка каната: тёмная полоска вдоль середины
    for k in (0, n // 2, n):
        d.rectangle((k - 1, 0, k + 1, n), fill=(190, 190, 190, 255))
        d.rectangle((0, k - 1, n, k + 1), fill=(190, 190, 190, 255))
    im.resize((size, size), Image.LANCZOS).save(out / "stop_net.png")


# ---------------- круглая мишень: кольца на прозрачном фоне ----------------
# Радиусы колец в долях радиуса мишени совпадают с FootballTuning: жёлтое и красное (до 0,38) дают 2 очка, остальные 1.
def target(out: Path, size=2048):
    rng = np.random.RandomState(9)
    ss = 2                                                                   # рисуем вдвое крупнее и уменьшаем: гладкие края
    n = size * ss
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = n / 2
    rings = [(1.00, (244, 244, 238)), (0.78, (24, 24, 28)), (0.58, (28, 92, 205)), (0.38, (214, 40, 36)), (0.19, (255, 204, 24))]
    for r, col in rings:
        rr = r * c * 0.985
        d.ellipse((c - rr, c - rr, c + rr, c + rr), fill=col)
        d.ellipse((c - rr, c - rr, c + rr, c + rr), outline=(12, 12, 16), width=int(n * 0.0035))
    font = ImageFont.load_default(size=int(n * 0.11))
    d.text((c, c), "2", font=font, fill=(24, 24, 28), anchor="mm", stroke_width=int(n * 0.002), stroke_fill=(24, 24, 28))
    small = ImageFont.load_default(size=int(n * 0.05))
    d.text((c, c - 0.89 * c * 0.985), "1", font=small, fill=(24, 24, 28), anchor="mm")
    d.text((c, c + 0.89 * c * 0.985), "1", font=small, fill=(24, 24, 28), anchor="mm")
    im = im.resize((size, size), Image.LANCZOS)
    arr = np.asarray(im, dtype=np.float32) / 255.0
    # печать на виниле: низкая частота света, мелкая зернистость, лёгкие потёртости
    arr[..., :3] *= (0.94 + 0.10 * smooth_noise(size, size, 5, rng))[..., None]
    arr[..., :3] *= (0.97 + 0.05 * smooth_noise(size, size, 400, rng))[..., None]
    out_im = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8), "RGBA")
    dd = ImageDraw.Draw(out_im, "RGBA")
    for _ in range(300):
        x, y = rng.randint(0, size), rng.randint(0, size)
        ln = rng.randint(20, 160)
        a = rng.uniform(0, math.pi)
        dd.line((x, y, x + math.cos(a) * ln, y + math.sin(a) * ln * 0.2), fill=(255, 255, 255, int(rng.randint(8, 34))), width=1)
    r, g, b, alpha = out_im.split()
    out_im = Image.merge("RGBA", (r, g, b, im.split()[3]))                   # царапины не выходят за круг
    out_im.save(out / "target_rings.png")


# ---------------- чехол на ворота: полотно с тремя отверстиями по диагонали ----------------
# Размер полотна 2,35 × 1,35 м, отверстия ⌀ 0,52 м в точках FootballTuning.TarpHoleX/Z (±0,80; ±0,33): верх-лево, центр, низ-право.
# Цифры — порядок попыток (1 — верх-лево, 2 — низ-право, 3 — центр). В свободных углах — эмблемы.
def tarp(out: Path, width=1600, height=920):
    rng = np.random.RandomState(5)
    ss = 2
    w, h = width * ss, height * ss
    yy = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
    top, bottom = np.array([9, 22, 60], np.float32), np.array([26, 66, 156], np.float32)
    base = top[None, None, :] * (1 - yy[..., None]) + bottom[None, None, :] * yy[..., None]
    base = np.repeat(base, w, axis=1)
    xx = np.linspace(0.0, 1.0, w, dtype=np.float32)[None, :]
    for k in range(6):                                                       # косые световые полосы
        centre = 0.12 + k * 0.19
        band = np.clip(1.0 - np.abs((xx + yy * 0.35) - centre) / 0.035, 0.0, 1.0)
        base += band[..., None] * 16.0
    rgb = np.clip(base, 0, 255).astype(np.uint8)
    im = Image.fromarray(rgb, "RGB").convert("RGBA")
    d = ImageDraw.Draw(im, "RGBA")
    step = int(h * 0.045)                                                    # мелкий ромбовидный рисунок, как у спортивной ткани
    for i in range(-h, w + h, step):
        d.line((i, 0, i + h, h), fill=(255, 255, 255, 12), width=2)
        d.line((i, h, i + h, 0), fill=(255, 255, 255, 12), width=2)
    pad = int(h * 0.025)
    d.rectangle((0, 0, w - 1, h - 1), outline=(246, 246, 240, 255), width=pad)
    d.rectangle((pad, pad, w - 1 - pad, h - 1 - pad), outline=(255, 204, 24, 255), width=int(pad * 0.3))
    sx, sy = w / 2.35, h / 1.35                                              # пикселей на метр
    cx, cy = w / 2, h / 2
    # (x, z, номер попытки, куда сдвинуть значок от центра отверстия)
    holes = [(-0.80, 0.33, "1", (1.0, 0.0)), (0.80, -0.33, "2", (-1.0, 0.0)), (0.0, 0.0, "3", (0.75, 0.66))]
    r_hole = 0.26 * sx
    for hx, hz, label, _ in holes:
        x, y = cx + hx * sx, cy - hz * sy
        for r, col in ((r_hole + 0.048 * sx, (246, 246, 240, 255)), (r_hole + 0.034 * sx, (214, 40, 36, 255)), (r_hole + 0.014 * sx, (246, 246, 240, 255))):
            d.ellipse((x - r, y - r, x + r, y + r), fill=col)

    def medallion(mx, mz, text, size):
        x, y = cx + mx * sx, cy - mz * sy
        for r, col in ((0.27, (246, 246, 240, 255)), (0.247, (10, 24, 62, 255)), (0.23, (60, 216, 255, 255)), (0.208, (10, 24, 62, 255))):
            rr = r * sy
            d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=col)
        f = ImageFont.load_default(size=int(size * sy))
        d.text((x, y), text, font=f, fill=(246, 246, 240, 255), anchor="mm", stroke_width=2, stroke_fill=(246, 246, 240, 255))

    medallion(0.80, 0.33, "BCI", 0.21)                                       # верх-право
    medallion(-0.80, -0.33, "2027", 0.15)                                    # низ-лево
    # номера попыток
    for hx, hz, label, (ux, uz) in holes:
        x, y = cx + hx * sx, cy - hz * sy
        ln = (ux * ux + uz * uz) ** 0.5
        dist = r_hole + 0.075 * sx
        bx, by = x + ux / ln * dist, y - uz / ln * dist
        rb = 0.088 * sy
        d.ellipse((bx - rb, by - rb, bx + rb, by + rb), fill=(255, 204, 24, 255), outline=(10, 24, 62, 255), width=int(0.012 * sy))
        f = ImageFont.load_default(size=int(0.115 * sy))
        d.text((bx, by), label, font=f, fill=(10, 24, 62, 255), anchor="mm", stroke_width=2, stroke_fill=(10, 24, 62, 255))
    # отверстия: прозрачные пиксели
    for hx, hz, label, _ in holes:
        x, y = cx + hx * sx, cy - hz * sy
        mask = Image.new("L", (w, h), 255)
        ImageDraw.Draw(mask).ellipse((x - r_hole, y - r_hole, x + r_hole, y + r_hole), fill=0)
        a = np.minimum(np.asarray(im.split()[3]), np.asarray(mask))
        im.putalpha(Image.fromarray(a))
    im = im.resize((width, height), Image.LANCZOS)
    arr = np.asarray(im, dtype=np.float32) / 255.0
    arr[..., :3] *= (0.95 + 0.08 * smooth_noise(height, width, 6, rng))[..., None]
    arr[..., :3] *= (0.97 + 0.05 * smooth_noise(height, width, 300, rng))[..., None]
    Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8), "RGBA").save(out / "goal_tarp.png")


# ---------------- газон: фото-текстура Poly Haven, перекрашенная в свежую траву, рельеф и полосы покоса ----------------
def grass(out: Path, ph_dir: Path):
    """grass_albedo.png / grass_normal.png — бесшовная плитка (основа leafy_grass, Poly Haven, CC0): оттенок сдвинут в зелёный,
    добавлены мелкие травинки, рельеф считается из яркости; stripes.png — полосы покоса (накладываются один раз на всё поле)."""
    from scipy import ndimage

    src = Image.open(ph_dir / "leafy_grass_diff_2k.jpg").convert("RGB")
    a = np.asarray(src, dtype=np.float32) / 255.0
    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    lo, hi = np.percentile(lum, 2), np.percentile(lum, 98)
    v0 = np.clip((lum - lo) / (hi - lo), 0, 1)
    rng = np.random.RandomState(31)
    soft = ndimage.gaussian_filter(v0, sigma=7, mode="wrap")
    blades = ndimage.gaussian_filter(rng.rand(*v0.shape).astype(np.float32), sigma=(3.2, 0.8), mode="wrap")
    blades = (blades - blades.min()) / (blades.max() - blades.min())
    fine = ndimage.gaussian_filter(rng.rand(*v0.shape).astype(np.float32), sigma=0.7, mode="wrap")
    fine = (fine - fine.min()) / (fine.max() - fine.min())
    v = 0.40 * v0 + 0.30 * soft + 0.45 * blades + 0.30 * fine
    v = (v - v.min()) / (v.max() - v.min())
    v = np.clip((v - 0.5) * 1.55 + 0.5, 0, 1)                          # контраст: травинки и тени между ними читаются
    hue = 0.250 + 0.040 * (v - 0.5)
    sat = 0.70 + 0.16 * (1 - v)
    val = 0.14 + 0.62 * v
    h6 = hue * 6.0
    i = np.floor(h6).astype(int) % 6
    f = h6 - np.floor(h6)
    pp = val * (1 - sat)
    q = val * (1 - sat * f)
    t = val * (1 - sat * (1 - f))
    rgb = np.zeros_like(a)
    for k, (r, g, bb) in enumerate([(val, t, pp), (q, val, pp), (pp, val, t), (pp, q, val), (t, pp, val), (val, pp, q)]):
        m = i == k
        rgb[..., 0][m], rgb[..., 1][m], rgb[..., 2][m] = r[m], g[m], bb[m]
    small = (1024, 1024)                                               # плитка 1,4 м: 1 мм на пиксель достаточно
    Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8)).resize(small, Image.LANCZOS).save(out / "grass_albedo.png")
    Image.fromarray(normal_from_height(ndimage.gaussian_filter(v, 0.6), 5.0)).resize(small, Image.LANCZOS).save(out / "grass_normal.png")
    # полосы покоса: 12 полос по длине поля, мягкий край, лёгкая разница оттенка и неровность
    size = 1024
    y = (np.arange(size, dtype=np.float32) + 0.5) / size
    band = np.sin(y * 2 * math.pi * 6 - math.pi / 2)
    band = np.tanh(band * 2.2) * 0.5 + 0.5
    rng2 = np.random.RandomState(12)
    patch = smooth_noise(size, size, 12, rng2) * 0.10 + smooth_noise(size, size, 60, rng2) * 0.05
    mult = 0.78 + 0.22 * band[:, None] + patch - 0.075
    tint = np.stack([mult * (0.98 + 0.02 * band[:, None]), mult, mult * (0.95 + 0.05 * band[:, None])], axis=-1)
    Image.fromarray((np.clip(tint, 0, 1) * 255).astype(np.uint8)).save(out / "stripes.png")


# ---------------- мяч: усечённый икосаэдр, цвет и швы-канавки (нормали) ----------------
def ball(out: Path, width=2048, height=1024):
    """12 чёрных пятиугольников (вершины икосаэдра, одна — на полюсе) и 20 белых шестиугольников (центры граней).
    Панель определяется по ближайшему центру с поправкой на угловой размер; шов — там, где два ближайших центра почти равноудалены."""
    s5 = 5 ** 0.5
    top = [(0.0, 0.0, 1.0)]
    ring_a = [(2 / s5 * math.cos(2 * math.pi * k / 5), 2 / s5 * math.sin(2 * math.pi * k / 5), 1 / s5) for k in range(5)]
    ring_b = [(2 / s5 * math.cos(2 * math.pi * (k + 0.5) / 5), 2 / s5 * math.sin(2 * math.pi * (k + 0.5) / 5), -1 / s5) for k in range(5)]
    verts = np.array(top + ring_a + ring_b + [(0.0, 0.0, -1.0)], dtype=np.float32)
    edge = math.dist(verts[0], verts[1])
    faces = []
    for i in range(12):
        for j in range(i + 1, 12):
            for k in range(j + 1, 12):
                if all(abs(math.dist(verts[x], verts[y]) - edge) < 1e-3 for x, y in ((i, j), (j, k), (i, k))):
                    c = verts[i] + verts[j] + verts[k]
                    faces.append(c / np.linalg.norm(c))
    assert len(faces) == 20, len(faces)
    centers = np.concatenate([verts, np.array(faces, dtype=np.float32)])
    radius = np.array([20.07] * 12 + [23.8] * 20, dtype=np.float32) * math.pi / 180
    is_pent = np.array([True] * 12 + [False] * 20)
    rng = np.random.RandomState(4)
    albedo = np.zeros((height, width, 3), dtype=np.float32)
    hmap = np.zeros((height, width), dtype=np.float32)
    lon = (np.arange(width, dtype=np.float32) + 0.5) / width * 2 * math.pi - math.pi
    leather = smooth_noise(height, width, 900, rng) * 0.04 + smooth_noise(height, width, 300, rng) * 0.03
    black = np.array([0.028, 0.028, 0.032], dtype=np.float32)
    white = np.array([0.90, 0.90, 0.88], dtype=np.float32)
    step = 64
    for y0 in range(0, height, step):
        y1 = min(height, y0 + step)
        lat = math.pi / 2 - (np.arange(y0, y1, dtype=np.float32) + 0.5) / height * math.pi
        cl, sl = np.cos(lat)[:, None], np.sin(lat)[:, None]
        d = np.stack([cl * np.cos(lon)[None, :], cl * np.sin(lon)[None, :], np.broadcast_to(sl, (y1 - y0, width))], axis=-1)
        ang = np.arccos(np.clip(d @ centers.T, -1, 1)) / radius
        order = np.argsort(ang, axis=-1)
        best = np.take_along_axis(ang, order[..., :1], -1)[..., 0]
        second = np.take_along_axis(ang, order[..., 1:2], -1)[..., 0]
        idx = order[..., 0]
        margin = second - best                                       # 0 на шве, растёт к центру панели
        groove = np.exp(-(margin / 0.03) ** 2)                       # канавка шва
        base = np.where(is_pent[idx][..., None], black, white)
        shade = 1.0 - 0.70 * groove
        albedo[y0:y1] = base * shade[..., None] * (1.0 - 0.10 * np.clip(0.18 - margin, 0, 1)[..., None] * 3.0)
        hmap[y0:y1] = -1.0 * groove + 0.30 * (1.0 - np.clip(best, 0, 1)) ** 2          # швы вдавлены, панели чуть вздуты
    albedo *= (0.97 + leather)[..., None]
    # естественность: пятна грязи, потёртости, зернистая кожа (шестиугольные пупырышки)
    dirt = np.clip(smooth_noise(height, width, 10, rng) * 1.6 - 0.55, 0, 1) * np.clip(smooth_noise(height, width, 40, rng) * 1.5, 0, 1)
    smudge = np.array([0.50, 0.46, 0.36], dtype=np.float32)
    albedo = albedo * (1 - 0.30 * dirt[..., None]) + smudge * (0.30 * dirt[..., None]) * (albedo.mean(axis=-1, keepdims=True) > 0.3)
    im = Image.fromarray((np.clip(albedo, 0, 1) * 255).astype(np.uint8))
    dr = ImageDraw.Draw(im, "RGBA")
    for _ in range(450):                                           # потёртости: короткие светлые царапины
        x, y = rng.randint(0, width), rng.randint(int(height * 0.08), int(height * 0.92))
        ln = rng.randint(15, 100)
        a = rng.uniform(0, math.pi)
        dr.line((x, y, x + math.cos(a) * ln, y + math.sin(a) * ln * 0.5), fill=(150, 150, 146, int(rng.randint(16, 56))), width=int(rng.randint(1, 3)))
    im.save(out / "ball_albedo.png")
    xs = np.arange(width, dtype=np.float32)[None, :]
    ys = np.arange(height, dtype=np.float32)[:, None]
    k = 2 * math.pi / 8.75                                          # ~230 пупырышек по экватору
    pebble = (np.cos(k * xs) + np.cos(k * (0.5 * xs + 0.866 * ys)) + np.cos(k * (0.5 * xs - 0.866 * ys))) / 3.0
    irregular = 0.55 + 0.9 * smooth_noise(height, width, 700, rng)                          # зерно неравномерное, без «сетки»
    hmap = hmap + 0.030 * np.clip(pebble, -0.5, 1.0) * irregular + leather * 0.8
    Image.fromarray(normal_from_height(hmap, 7.0)).save(out / "ball_normal.png")


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    cone(out)
    net(out)
    target(out)
    tarp(out)
    stop_net(out)
    ball(out)
    if len(sys.argv) >= 3:
        grass(out, Path(sys.argv[2]))
    print("OK", sorted(p.name for p in out.glob("*.png")))
