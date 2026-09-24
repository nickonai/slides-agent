#!/usr/bin/env python3
"""Package the portable slides skill for ChatGPT / OpenAI skill upload."""
from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "slides"
DEFAULT_OUT = ROOT / "dist" / "slides-skill.zip"


def package(out: Path) -> None:
    files = sorted(
        p for p in SKILL.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}
    )
    files.append(ROOT / "LICENSE")
    if not (SKILL / "SKILL.md").is_file():
        raise SystemExit("Missing skills/slides/SKILL.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(out, "w", ZIP_DEFLATED) as bundle:
        for path in files:
            relative = "LICENSE" if path == ROOT / "LICENSE" else path.relative_to(SKILL).as_posix()
            bundle.write(path, f"slides/{relative}")
    with ZipFile(out) as bundle:
        names = bundle.namelist()
        if names.count("slides/SKILL.md") != 1 or any(not n.startswith("slides/") for n in names):
            raise SystemExit("Invalid skill bundle")
        if bundle.testzip():
            raise SystemExit("Corrupt skill bundle")
    print(f"{out} ({len(names)} files, {out.stat().st_size} bytes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    package(parser.parse_args().out)
