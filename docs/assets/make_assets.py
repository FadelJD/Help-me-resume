"""Regenerate the README assets from real runs.

    pip install pillow
    python docs/assets/make_assets.py

quickstart.gif: `cvforge init --example`, `build` and `check` run in a scratch folder; the GIF
replays their real output (vhs and agg are not used because their release downloads were not
reachable from the build environment). cv-check.png: page 1 of the Awesome-CV corpus build next
to its `check` summary. Needs the corpus fonts (tests/fixtures/templates/provision.sh).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "docs" / "assets"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
BG, FG, PROMPT, DIM, OK = (24, 26, 33), (220, 223, 228), (110, 200, 140), (140, 146, 158), (120, 210, 150)
CVFORGE = str(Path(sys.executable).with_name("cvforge"))


def run(cmd: list[str], cwd: Path) -> str:
    env = {**os.environ, "COLUMNS": "92", "SOURCE_DATE_EPOCH": "1793404800"}
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env, check=True)
    return (proc.stdout + proc.stderr).replace(str(cwd), ".")


def session(work: Path) -> list[tuple[str, list[str]]]:
    steps = [
        ["init", "--example"],
        ["build", "--compile", "-o", "out/cv.tex"],
        ["check", "out/cv.tex"],
    ]
    out = []
    for args in steps:
        text = run([CVFORGE, *args], work)
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if args[0] == "init":
            lines = lines[-1:]  # the profile itself scrolls past; keep the summary line
        if args[0] == "check":
            lines = [ln for ln in lines if "warning:" not in ln]
        wrapped = []
        for ln in lines:
            while len(ln) > 92:
                wrapped.append(ln[:92])
                ln = "  " + ln[92:]
            wrapped.append(ln)
        out.append(("cvforge " + " ".join(args), wrapped))
    return out


def gif(steps: list[tuple[str, list[str]]], target: Path) -> None:
    font = ImageFont.truetype(MONO, 15)
    w, h, lh, pad = 900, 430, 20, 16
    rows: list[tuple[str, tuple[int, int, int]]] = []
    frames: list[Image.Image] = []
    durations: list[int] = []

    def frame(ms: int) -> None:
        img = Image.new("RGB", (w, h), BG)
        d = ImageDraw.Draw(img)
        for i, (text, colour) in enumerate(rows[-((h - 2 * pad) // lh) :]):
            d.text((pad, pad + i * lh), text, font=font, fill=colour)
        frames.append(img.quantize(colors=16))
        durations.append(ms)

    for command, output in steps:
        for k in range(0, len(command) + 1, 3):
            rows.append(("$ " + command[:k], PROMPT))
            frame(60)
            rows.pop()
        rows.append(("$ " + command, PROMPT))
        frame(400)
        for line in output:
            colour = OK if line.startswith("check passed") else (DIM if ": " in line else FG)
            rows.append((line, colour))
        frame(1800)
        rows.append(("", FG))
    frame(3500)
    frames[0].save(target, save_all=True, append_images=frames[1:], duration=durations, loop=0)


def png(target: Path) -> None:
    sys.path.insert(0, str(ROOT))
    from tests.corpus import CORPUS, run_template

    entry = {"name": "awesome-cv"}
    with tempfile.TemporaryDirectory() as d:
        run_template(entry, Path(d))
        pdf = Path(d) / "awesome-cv" / "awesome-cv.pdf"
        subprocess.run(["pdftoppm", "-r", "70", "-png", "-f", "1", "-l", "1", str(pdf),
                        str(Path(d) / "page")], check=True)
        page = Image.open(next(Path(d).glob("page*.png"))).convert("RGB")
        summary = run([CVFORGE, "check", str(Path(d) / "awesome-cv" / "awesome-cv.tex"),
                       "--no-semantic"], Path(d))
    lines = ["cvforge check  (Awesome-CV, unchanged design)", ""]
    for ln in summary.splitlines():
        if "[gate]" in ln or "[advisory]" in ln or ln.startswith(("check ", "evidence", "density")):
            lines.append(ln)
    font = ImageFont.truetype(MONO, 14)
    panel_w = 520
    img = Image.new("RGB", (page.width + panel_w, page.height), BG)
    img.paste(page, (0, 0))
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        colour = OK if ln.startswith("check passed") else FG
        d.text((page.width + 20, 30 + i * 22), ln[:58], font=font, fill=colour)
    img.save(target, optimize=True)
    _ = CORPUS


def main() -> None:
    with tempfile.TemporaryDirectory() as d:
        gif(session(Path(d)), ASSETS / "quickstart.gif")
    png(ASSETS / "cv-check.png")
    for name in ("quickstart.gif", "cv-check.png"):
        size = (ASSETS / name).stat().st_size
        print(f"{name}: {size / 1024:.0f} KiB")
    shutil.rmtree(ROOT / "out" / "assets", ignore_errors=True)


if __name__ == "__main__":
    main()
