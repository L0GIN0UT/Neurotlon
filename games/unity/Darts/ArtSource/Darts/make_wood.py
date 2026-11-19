"""Текстура деревянной стены для сцены дартса: python -I make_wood.py <выходной png>.

Вертикальные доски с волокнами, сучками и тёмными стыками. Только numpy и Pillow, без внешних файлов.
Плитка 2048×2048 повторяется по стене (в Unity тайлинг задаётся в материале).
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

SIZE = 2048
PLANKS = 4


def smooth(a: np.ndarray, k: int, axis: int) -> np.ndarray:
    kernel = np.ones(k) / k
    return np.apply_along_axis(lambda m: np.convolve(m, kernel, mode="same"), axis, a)


def main(out: Path) -> None:
    rng = np.random.RandomState(11)
    img = np.zeros((SIZE, SIZE, 3), dtype=np.float32)
    pw = SIZE // PLANKS
    for p in range(PLANKS):
        base = np.array([0.30, 0.17, 0.09]) * rng.uniform(0.82, 1.15)
        tone = np.array([0.16, 0.09, 0.05])
        # волокна: длинные по вертикали шумовые полосы разной частоты
        grain = np.zeros((SIZE, pw), dtype=np.float32)
        for cols, weight in ((pw // 3, 0.34), (pw, 0.30), (pw * 2, 0.22)):
            noise = rng.rand(SIZE // 380 + 2, cols).astype(np.float32)            # мало строк: волокно длинное и плавное
            img_n = Image.fromarray((noise * 255).astype(np.uint8)).resize((pw, SIZE), Image.BICUBIC)
            grain += weight * (np.asarray(img_n, dtype=np.float32) / 255.0)
        grain = (grain - grain.min()) / (grain.max() - grain.min())
        # лёгкая волна колец роста
        x = np.linspace(0, 1, pw)[None, :]
        y = np.linspace(0, 1, SIZE)[:, None]
        rings = 0.5 + 0.5 * np.sin((x * 9.0 + 0.8 * np.sin(y * 3.0 + p) + grain * 1.6) * 6.28)
        mix = 0.55 * grain + 0.45 * rings
        plank = base[None, None, :] + (mix[:, :, None] - 0.5) * tone[None, None, :] * 2.2
        # сучки
        for _ in range(rng.randint(1, 3)):
            cy, cx, r = rng.randint(120, SIZE - 120), rng.randint(40, pw - 40), rng.randint(18, 34)
            yy, xx = np.mgrid[0:SIZE, 0:pw]
            d = np.sqrt(((xx - cx) * 1.0) ** 2 + ((yy - cy) * 0.55) ** 2)
            plank -= (np.exp(-(d / r) ** 2)[:, :, None] * np.array([0.10, 0.07, 0.04])[None, None, :]) * 2.0
        img[:, p * pw:(p + 1) * pw, :] = plank
        img[:, p * pw:p * pw + 3, :] *= 0.25            # тёмные стыки между досками
        img[:, (p + 1) * pw - 2:(p + 1) * pw, :] *= 0.45
    img = np.clip(img, 0.0, 1.0)
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((img * 255).astype(np.uint8)).save(out)
    print("OK", out)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
