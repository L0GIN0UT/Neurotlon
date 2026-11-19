"""Синтез звуков для дартса без внешних файлов: python -I make_sounds.py <папка вывода>.

Звуки: бросок («вап» с низким толчком руки), попадание в мишень, попадание в центр, промах, конец игры.
Формат: WAV, 16 бит, моно, 44,1 кГц.
"""
import math
import random
import struct
import sys
import wave
from pathlib import Path

RATE = 44100


def env(t: float, attack: float, decay: float) -> float:
    a = min(1.0, t / attack) if attack > 0 else 1.0
    return a * math.exp(-decay * t)


def tone(freq, seconds, decay, harmonics=((1.0, 1.0),), attack=0.003, glide=0.0):
    out, phase = [], 0.0
    for i in range(int(RATE * seconds)):
        t = i / RATE
        phase += 2 * math.pi * freq * (1.0 + glide * (1.0 - t / seconds)) / RATE
        out.append(sum(w * math.sin(phase * h) for h, w in harmonics) * env(t, attack, decay))
    return out


def noise(seconds, decay, seed=1, attack=0.0005):
    rng = random.Random(seed)
    return [(rng.random() * 2 - 1) * env(i / RATE, attack, decay) for i in range(int(RATE * seconds))]


def bandpass(samples, center, q):
    """резонансный фильтр (state variable): center(t) — частота в Гц от доли длительности 0…1"""
    low = band = 0.0
    out = []
    n = len(samples)
    for i, x in enumerate(samples):
        f = 2.0 * math.sin(math.pi * center(i / n) / RATE)
        low += f * band
        high = x - low - band / q
        band += f * high
        out.append(band)
    return out


def thump(ms, freq, gain=1.0):
    """низкий глухой толчок: рука отпускает дротик"""
    n = int(RATE * ms / 1000)
    return [math.sin(2 * math.pi * freq * i / RATE) * math.exp(-7 * i / n) * gain for i in range(n)]


def throw_sound():
    """бросок: очень короткий «вап» (0,12 с): широкий шум около 900 Гц и плотный низкий толчок"""
    n = int(RATE * 0.12)
    air = bandpass(noise(0.12, 0.0, seed=7, attack=0.0), lambda t: 1000 - 300 * t, 0.9)     # равномерный шум на 0,12 с
    shaped = []
    for i, x in enumerate(air):
        t = i / n
        a = t / 0.10 if t < 0.10 else (1.0 if t < 0.18 else max(0.0, 1.0 - (t - 0.18) / 0.82) ** 2.4)
        shaped.append(x * a)
    return mix(thump(24, 150, 1.0), [0.0] * int(RATE * 0.003) + shaped)


def mix(*parts):
    n = max(len(p) for p in parts)
    return [sum(p[i] if i < len(p) else 0.0 for p in parts) for i in range(n)]


def scale(samples, gain):
    return [s * gain for s in samples]


def concat(*parts):
    out = []
    for p in parts:
        out.extend(p)
    return out


def save(path: Path, samples):
    peak = max(1e-9, max(abs(s) for s in samples))
    gain = min(1.0, 0.89 / peak)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s * gain)) * 32767)) for s in samples))


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    save(out / "throw.wav", throw_sound())
    # попадание в мишень: сухой удар в пробку + короткий звон металла
    save(out / "hit.wav", mix(scale(noise(0.05, 90, 3), 0.7), scale(tone(180, 0.18, 30, ((1, 1), (2, 0.3)), glide=0.15), 0.9),
                              scale(tone(2400, 0.12, 40), 0.12)))
    # центр: тот же удар и светлый звон
    save(out / "bull.wav", mix(scale(noise(0.05, 90, 4), 0.6), scale(tone(190, 0.16, 30), 0.8),
                               scale(concat(tone(880, 0.12, 9, ((1, 1), (2, 0.3))), tone(1320, 0.35, 5, ((1, 1), (2, 0.3)))), 0.55)))
    # промах: глухой стук в стену
    save(out / "miss.wav", mix(scale(noise(0.07, 60, 5), 0.5), scale(tone(110, 0.22, 24, ((1, 1), (2, 0.2))), 0.9)))
    notes, parts = [523.25, 659.25, 783.99, 1046.5], []
    for i, f in enumerate(notes):
        last = i == len(notes) - 1
        parts.append(scale(tone(f, 0.55 if last else 0.14, 4 if last else 14, ((1, 1), (2, 0.3), (3, 0.12))), 0.8))
    save(out / "finish.wav", concat(*parts))
    print("OK", sorted(p.name for p in out.glob("*.wav")))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
