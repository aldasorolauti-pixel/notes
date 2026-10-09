"""Run the local sanitizer against noisy variants and report roster leaks."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from p4.sanitize import Sanitizer  # noqa: E402
from tools.make_noisy_variants import read_roster  # noqa: E402


def _survivors(text: str, roster: list[str], altered: set[str]) -> list[str]:
    candidates = roster + sorted(altered)
    return sorted(
        {
            candidate
            for candidate in candidates
            if re.search(rf"(?<!\w){re.escape(candidate)}(?!\w)", text, re.IGNORECASE)
        },
        key=str.casefold,
    )


def check_directory(input_dir: Path, roster_path: Path) -> list[tuple[str, list[str]]]:
    roster = read_roster(roster_path)
    sanitizer = Sanitizer(
        entities_path=ROOT / "data" / "entities.json",
        nicknames_path=ROOT / "data" / "nicknames.json",
        participants=roster,
    )
    altered: set[str] = set()
    for name in roster:
        altered.update(name for name in (name.casefold(), name.replace("c", "k")) if name)
    rows: list[tuple[str, list[str]]] = []
    for path in sorted(input_dir.glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        try:
            masked, _ = sanitizer.mask(text, participants=roster)
            leaks = _survivors(masked, roster, altered)
        except RuntimeError:
            leaks = ["<sanitizer residue failure>"]
        rows.append((path.name, leaks))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=Path("test_files/noisy"))
    parser.add_argument("--roster", type=Path, default=Path("roster.txt"))
    args = parser.parse_args()
    print("| archivo | nombres sin enmascarar (cantidad) | cuales |")
    print("|---|---:|---|")
    for filename, leaks in check_directory(args.input_dir, args.roster):
        print(f"| {filename} | {len(leaks)} | {', '.join(leaks) if leaks else '-'} |")


if __name__ == "__main__":
    main()
