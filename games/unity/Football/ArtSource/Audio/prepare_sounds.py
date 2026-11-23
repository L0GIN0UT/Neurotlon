"""Звуки футбола из настоящих записей: python -I prepare_sounds.py <папка Kenney> <папка вывода>.

Источник: Kenney «Impact Sounds» (CC0, https://kenney.nl/assets/impact-sounds); свисток судьи — запись SpliceSound (CC0, Wikimedia Commons,
source/referee_whistle.wav). Запись меняют по высоте (ускорение), срезают верх,
при необходимости смешивают два слоя, обрезают, сглаживают конец и выравнивают по пику (дБ). Нужен ffmpeg в PATH.
Файлы кладутся в Assets/Audio.

Звук удара зависит от того, обо что бьётся мяч: kick — нога, tarp — ткань чехла ворот, net — сетка, ground — мягкая земля
(отскок от травы и удар о мишень). Остальные — касание конуса, итог попытки, метроном.
"""
import re
import subprocess
import sys
from pathlib import Path

# имя файла: (слои, длительность с, пик дБ); слой: (исходник, коэффициент высоты, срез верха Гц или 0, усиление дБ, задержка мс[, нарастание мс[, пропуск начала мс]])
SOUNDS = {
    "kick.wav": ([("impact_soft_medium_001", 0.95, 0, 0.0, 0)], 0.28, -4.0),           # удар по мячу: глухой «бум»
    "touch.wav": ([("impact_plank_medium_002", 2.1, 0, 0.0, 0)], 0.12, -8.0),          # касание конуса: сухой пластик
    "good.wav": ([("impact_generic_light_001", 1.9, 0, 0.0, 0)], 0.22, -9.0),          # итог элемента: отлично
    "soft.wav": ([("impact_wood_medium_001", 1.5, 0, 0.0, 0)], 0.20, -11.0),           # итог элемента: частично
    "miss.wav": ([("impact_wood_light_001", 0.85, 0, 0.0, 0)], 0.24, -12.0),           # итог элемента: мимо
    "tick.wav": ([("impact_generic_light_003", 2.6, 0, 0.0, 0)], 0.08, -16.0),         # начало элемента и метроном
    "target.wav": ([("impact_bell_heavy_002", 1.1, 0, 0.0, 0)], 0.7, -6.0),            # удар в мишень: звон металла, одинаковый во всех зонах
    "end.wav": ([("referee_whistle", 1.0, 0, 0.0, 0, 0, 60)], 1.5, -7.0),                                           # конец матча: свисток судьи
    # по материалам
    "post.wav": ([("impact_plate_medium_001", 1.75, 5000, 0.0, 0), ("impact_soft_medium_001", 1.2, 0, -5.0, 0)], 0.30, -4.0),      # штанга и перекладина: металл
    "tarp.wav": ([("impact_soft_heavy_001", 0.9, 2500, 0.0, 0), ("footstep_carpet_002", 1.1, 3000, -6.0, 15)], 0.36, -6.0),     # мяч в ткань чехла
    "net.wav": ([("footstep_carpet_003", 1.3, 4500, 0.0, 0), ("impact_soft_medium_001", 1.0, 0, -8.0, 30)], 0.46, -10.0),     # мяч в сетке
    "ground.wav": ([("impact_soft_heavy_002", 0.7, 380, 0.0, 0, 14)], 0.13, -5.0),                                       # мягкая земля и мишень: глухой «пуф» без щелчка
}


def find(source_dir: Path, name: str) -> Path:
    hits = list(source_dir.rglob(name + ".ogg")) + list((Path(__file__).parent / "source").glob(name + ".wav"))
    if not hits:
        raise SystemExit("нет файла " + name + ".ogg в " + str(source_dir) + " и " + name + ".wav в source/")
    return hits[0]


def peak_db(path: Path) -> float:
    probe = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    match = re.search(r"max_volume: (-?[\d.]+) dB", probe.stderr)
    return float(match.group(1)) if match else 0.0


def layer_chain(index: int, rate: float, lowpass: int, gain: float, delay_ms: int, fade_in_ms: int = 0, skip_ms: int = 0) -> str:
    parts = ["aformat=channel_layouts=mono", "aresample=44100"]
    if skip_ms:                                              # тишина в начале записи
        parts += ["atrim=start=%.3f" % (skip_ms / 1000.0), "asetpts=PTS-STARTPTS"]
    parts += ["asetrate=%d" % int(44100 * rate), "aresample=44100"]
    if lowpass:
        parts.append("lowpass=f=%d" % lowpass)
    if gain:
        parts.append("volume=%.1fdB" % gain)
    if delay_ms:
        parts.append("adelay=%d" % delay_ms)
    if fade_in_ms:                                           # мягкая земля гасит резкий щелчок удара
        parts.append("afade=t=in:d=%.3f" % (fade_in_ms / 1000.0))
    return "[%d:a]%s[l%d]" % (index, ",".join(parts), index)


def main(source_dir: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for target, (layers, duration, peak) in SOUNDS.items():
        fade = min(0.08, duration * 0.4)
        chains = [layer_chain(i, *layer[1:]) for i, layer in enumerate(layers)]
        mixed = "".join("[l%d]" % i for i in range(len(layers))) + "amix=inputs=%d:normalize=0" % len(layers) if len(layers) > 1 else "[l0]anull"
        tail = "atrim=0:%.3f,asetpts=PTS-STARTPTS,afade=t=out:st=%.3f:d=%.3f" % (duration, max(0.0, duration - fade), fade)
        graph = ";".join(chains + ["%s,%s[out]" % (mixed, tail)])
        cmd = ["ffmpeg", "-v", "error", "-y"]
        for source, *_ in layers:
            cmd += ["-i", str(find(source_dir, source))]
        tmp = out_dir / (target + ".tmp.wav")
        subprocess.run(cmd + ["-filter_complex", graph, "-map", "[out]", "-ar", "44100", "-ac", "1", str(tmp)], check=True)
        gain = peak - peak_db(tmp)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp), "-af", "volume=%.2fdB" % gain, "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le",
                        str(out_dir / target)], check=True)
        tmp.unlink()
        print("OK", target, "<-", ", ".join(l[0] for l in layers))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
