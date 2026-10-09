"""Generate deterministic, generic noisy variants of meeting notes."""

from __future__ import annotations

import argparse
import random
import re
import unicodedata
from pathlib import Path


SEED = 271828
MISHEARD_PAIRS = (
    ("deployment", "deploment"),
    ("certificate", "certificket"),
    ("database", "databace"),
    ("gateway", "gateaway"),
    ("release", "releese"),
    ("configuración", "configuració"),
    ("certificado", "sertificado"),
    ("despliegue", "despliege"),
)
FILLERS = ("eh", "o sea", "este", "mmm")
DATE_PHRASES = ("pasado mañana", "a fin de mes", "el trece del diez")


def read_roster(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _strip_diacritics(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )


def _name_variants(name: str) -> list[str]:
    variants = [_strip_diacritics(name)]
    if len(name) > 3:
        variants.append(name[0] + name[2:])
        variants.append(name + name[-1])
    if "c" in name.casefold():
        variants.append(re.sub("c", "k", name, flags=re.IGNORECASE))
    if len(name) > 4:
        variants.append(name[: max(2, len(name) // 2)])
    return list(dict.fromkeys(variant for variant in variants if variant and variant != name))


def make_names(text: str, roster: list[str], rng: random.Random) -> str:
    result = text
    for name in sorted(roster, key=len, reverse=True):
        variants = _name_variants(name)
        if not variants:
            continue
        replacement_index = 0

        def replace(match: re.Match[str]) -> str:
            nonlocal replacement_index
            value = variants[replacement_index % len(variants)]
            replacement_index += 1
            if match.group(0).isupper():
                return value.upper()
            if match.group(0)[0].isupper():
                return value[:1].upper() + value[1:]
            return value.casefold()

        result = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", replace, result, flags=re.IGNORECASE)
    return result


def make_nopunct(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\sáéíóúüñÁÉÍÓÚÜÑ]", " ", text)).casefold()


def make_fillers(text: str, rng: random.Random) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    output: list[str] = []
    for index, sentence in enumerate(sentences):
        if not sentence:
            continue
        filler = FILLERS[index % len(FILLERS)]
        output.append(f"{filler}, {sentence} {sentence[: max(8, len(sentence) // 5)]}...")
    return " ".join(output)


def make_misheard(text: str) -> str:
    result = text
    for source, target in MISHEARD_PAIRS:
        result = re.sub(re.escape(source), target, result, flags=re.IGNORECASE)
    return result


def make_timestamps(text: str) -> str:
    chunks = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(
        f"[00:{index % 60:02d}:{(index * 7) % 60:02d}] "
        f"{'Speaker ' + str((index % 4) + 1) + ': ' if index % 2 == 0 else ''}{chunk}"
        for index, chunk in enumerate(chunks)
        if chunk
    )


def make_dates(text: str, rng: random.Random) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if not sentences:
        return text
    additions = iter(DATE_PHRASES)
    result = []
    for index, sentence in enumerate(sentences):
        result.append(sentence)
        if index % 3 == 0:
            result.append(f" La fecha queda {next(additions, DATE_PHRASES[index % len(DATE_PHRASES)])}.")
    return " ".join(result)


def generate_variants(text: str, roster: list[str]) -> dict[str, str]:
    rng = random.Random(SEED)
    names = make_names(text, roster, rng)
    variants = {
        "names": names,
        "nopunct": make_nopunct(text),
        "fillers": make_fillers(text, rng),
        "misheard": make_misheard(text),
        "timestamps": make_timestamps(text),
        "dates": make_dates(text, rng),
    }
    variants["all"] = make_dates(make_timestamps(make_fillers(make_misheard(names), rng)), rng)
    return variants


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("texto_prueba_dificil_presencial.txt"))
    parser.add_argument("--roster", type=Path, default=Path("roster.txt"))
    parser.add_argument("--output-dir", type=Path, default=Path("test_files/noisy"))
    args = parser.parse_args()

    text = args.input.read_text(encoding="utf-8")
    variants = generate_variants(text, read_roster(args.roster))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in variants.items():
        (args.output_dir / f"{name}.txt").write_text(content, encoding="utf-8")
    print(f"generated {len(variants)} variants in {args.output_dir}")


if __name__ == "__main__":
    main()
