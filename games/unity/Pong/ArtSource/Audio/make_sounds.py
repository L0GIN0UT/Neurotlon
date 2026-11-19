"""Синтез звуков для понга без внешних файлов: python -I make_sounds.py <папка вывода>.

Звуки простые и короткие: удар ракетки, отскок от стола, отскок от края, очко, золотой мяч, победа.
Формат: WAV, 16 бит, моно, 44,1 кГц.
"""
import math
import random
import struct
import sys
import wave
from pathlib import Path

RATE = 44100


def envelope(t: float, attack: float, decay: float) -> float:
    a = min(1.0, t / attack) if attack > 0 else 1.0
    return a * math.exp(-decay * t)


def tone(freq: float, seconds: float, decay: float, harmonics=((1.0, 1.0),), attack: float = 0.002, glide: float = 0.0):
    n = int(RATE * seconds)
    out = []
    phase = 0.0
    for i in range(n):
        t = i / RATE
        f = freq * (1.0 + glide * (1.0 - t / seconds))
        phase += 2 * math.pi * f / RATE
        s = sum(w * math.sin(phase * h) for h, w in harmonics)
        out.append(s * envelope(t, attack, decay))
    return out


def noise(seconds: float, decay: float, seed: int = 1):
    rng = random.Random(seed)
    n = int(RATE * seconds)
    return [(rng.random() * 2 - 1) * envelope(i / RATE, 0.0005, decay) for i in range(n)]


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


def silence(seconds: float):
    return [0.0] * int(RATE * seconds)


def save(path: Path, samples):
    peak = max(1e-9, max(abs(s) for s in samples))
    gain = min(1.0, 0.89 / peak)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s * gain)) * 32767)) for s in samples))


def main(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    # удар ракетки: щелчок + звонкий тон
    save(out_dir / "paddle_hit.wav", mix(
        scale(noise(0.03, 160, 3), 0.55),
        scale(tone(640, 0.14, 38, ((1, 1.0), (2, 0.35), (3, 0.15))), 0.75)))
    # отскок от стола: глухой короткий стук
    save(out_dir / "table_bounce.wav", mix(
        scale(tone(330, 0.1, 52, ((1, 1.0), (2, 0.25)), glide=0.12), 0.8),
        scale(noise(0.02, 220, 5), 0.25)))
    # отскок от края: сухой щелчок повыше
    save(out_dir / "wall_bounce.wav", scale(tone(980, 0.07, 75, ((1, 1.0), (2, 0.2))), 0.7))
    # очко: две ноты вверх
    save(out_dir / "point.wav", concat(
        scale(tone(523.25, 0.2, 9, ((1, 1.0), (3, 0.2)), attack=0.004), 0.8),
        scale(tone(784.0, 0.4, 6, ((1, 1.0), (3, 0.2)), attack=0.004), 0.8)))
    # золотой мяч: три коротких сигнала
    pulse = scale(tone(880, 0.12, 12, ((1, 1.0), (2, 0.3)), attack=0.004), 0.8)
    save(out_dir / "overtime.wav", concat(pulse, silence(0.07), pulse, silence(0.07), pulse))
    # победа: арпеджио до-ми-соль-до
    notes = [523.25, 659.25, 783.99, 1046.5]
    parts = []
    for i, f in enumerate(notes):
        last = i == len(notes) - 1
        parts.append(scale(tone(f, 0.55 if last else 0.14, 4 if last else 14, ((1, 1.0), (2, 0.3), (3, 0.12)), attack=0.004), 0.8))
    save(out_dir / "win.wav", concat(*parts))
    print("OK", sorted(p.name for p in out_dir.glob("*.wav")))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
