#!/usr/bin/env python3
"""Compute horizontal centering for the Telegram plane SVG and patch docs/index.html."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
from svgpathtools import parse_path

PLANE_PATH = (
    "M9.417 15.181l-.397 5.584c.568 0 .814-.244 1.109-.537l2.663-2.545 "
    "5.518 4.041c1.012.564 1.725.267 1.998-.931L23.93 3.821c.321-1.431-.541-1.991"
    "-1.512-1.642L1.114 9.989c-1.453.564-1.431 1.374-.247 1.741l5.763 1.798"
    "L18.874 5.87c.645-.429 1.236-.191.751.239"
)
VIEW_SIZE = 24


def path_centroid(path_d: str, samples_per_segment: int = 100) -> tuple[float, float]:
    path = parse_path(path_d)
    xs: list[float] = []
    ys: list[float] = []
    for seg in path:
        for t in np.linspace(0, 1, samples_per_segment):
            z = seg.point(t)
            xs.append(z.real)
            ys.append(z.imag)
    return sum(xs) / len(xs), sum(ys) / len(ys)


def horizontal_offset(path_d: str, view_size: float = VIEW_SIZE) -> float:
    cx, _ = path_centroid(path_d)
    return round(view_size / 2 - cx, 3)


def view_box_for_shift(path_d: str, dx: float) -> str:
    path = parse_path(path_d)
    shifted = path.translated(dx)
    xmin, xmax, ymin, ymax = shifted.bbox()
    padding = 1.0
    side = max(xmax - xmin, ymax - ymin) + 2 * padding
    cx, cy = path_centroid(shifted.d())
    return f"{cx - side / 2:.3f} {cy - side / 2:.3f} {side:.3f} {side:.3f}"


def patch_index_html(html_path: Path, dx: float, view_box: str) -> None:
    block = (
        '            <div class="tg-logo" aria-hidden="true">\n'
        f'                <svg viewBox="{view_box}" xmlns="http://www.w3.org/2000/svg">\n'
        f'                    <path fill="#fff" transform="translate({dx}, 0)" d="{PLANE_PATH}" />\n'
        "                </svg>\n"
        "            </div>"
    )
    text = html_path.read_text()
    pattern = r'            <div class="tg-logo" aria-hidden="true">.*?</div>'
    updated, count = re.subn(pattern, block, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"Could not patch logo in {html_path}")
    html_path.write_text(updated)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--html",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docs" / "index.html",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    dx = horizontal_offset(PLANE_PATH)
    view_box = view_box_for_shift(PLANE_PATH, dx)
    print(
        f"path centroid x: {path_centroid(PLANE_PATH)[0]:.3f} (target {VIEW_SIZE / 2})"
    )
    print(f"horizontal translate: {dx}")
    print(f'viewBox="{view_box}"')

    if args.apply:
        patch_index_html(args.html, dx, view_box)
        print(f"Updated {args.html}")


if __name__ == "__main__":
    main()
