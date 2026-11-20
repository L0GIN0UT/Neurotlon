"""Звуки удара ракетки и отскока от стола из настоящих записей: python -I prepare_real_sounds.py <папка Kenney> <папка вывода>.

Источник: Kenney «Impact Sounds» (CC0, https://kenney.nl/assets/impact-sounds). Нужны файлы
`impact_generic_light_001.ogg` (удар ракетки) и `impact_wood_medium_001.ogg` (отскок от стола) из любой подпапки.
Запись ускоряется (выше тон), обрезается, затухает и выравнивается по пику: так её слышно как «пок» и «тик» шарика.
Нужен ffmpeg в PATH. Остальные звуки понга синтезирует `make_sounds.py`.
"""
import re
import subprocess
import sys
from pathlib import Path

# имя файла: (исходник, коэффициент высоты, длительность с, пик в дБ)
SOUNDS = {
    "paddle_hit.wav": ("impact_generic_light_001", 1.4, 0.15, -4.0),
    "table_bounce.wav": ("impact_wood_medium_001", 2.8, 0.08, -9.0),
}


def find(source_dir: Path, name: str) -> Path:
    hits = list(source_dir.rglob(name + ".ogg"))
    if not hits:
        raise SystemExit("нет файла " + name + ".ogg в " + str(source_dir))
    return hits[0]


def peak_db(path: Path) -> float:
    probe = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
                           capture_output=True, text=True)
    match = re.search(r"max_volume: (-?[\d.]+) dB", probe.stderr)
    return float(match.group(1)) if match else 0.0


def main(source_dir: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for target, (source, rate, duration, peak) in SOUNDS.items():
        fade = min(0.06, duration * 0.4)
        chain = (
            "aformat=channel_layouts=mono,asetrate=%d,aresample=44100,atrim=0:%.3f,asetpts=PTS-STARTPTS,"
            "afade=t=out:st=%.3f:d=%.3f" % (int(44100 * rate), duration, max(0.0, duration - fade), fade)
        )
        tmp = out_dir / (target + ".tmp.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(find(source_dir, source)), "-af", chain, "-ar", "44100", "-ac", "1", str(tmp)],
                       check=True)
        gain = peak - peak_db(tmp)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp), "-af", "volume=%.2fdB" % gain, "-ar", "44100", "-ac", "1",
                        "-c:a", "pcm_s16le", str(out_dir / target)], check=True)
        tmp.unlink()
        print("OK", target, "<-", source)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
