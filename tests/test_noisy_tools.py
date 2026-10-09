import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.check_name_leaks import check_directory
from tools.make_noisy_variants import generate_variants


def test_variant_generation_is_deterministic_and_changes_expected_surfaces():
    text = "Alina revisa el deployment. Bruno confirma el certificado mañana."
    roster = ["Alina", "Bruno"]

    first = generate_variants(text, roster)
    second = generate_variants(text, roster)

    assert first == second
    assert set(first) == {"names", "nopunct", "fillers", "misheard", "timestamps", "dates", "all"}
    assert first["names"] != text
    assert first["nopunct"] == first["nopunct"].lower()
    assert "[" in first["timestamps"] and "Speaker " in first["timestamps"]
    assert "pasado mañana" in first["dates"] or "a fin de mes" in first["dates"]


def test_name_leak_checker_reports_survivors(tmp_path):
    input_dir = tmp_path / "noisy"
    input_dir.mkdir()
    (input_dir / "safe.txt").write_text("{{PERSON_1}} revisa el plan.", encoding="utf-8")
    (input_dir / "leak.txt").write_text("Alina revisa el plan.", encoding="utf-8")
    roster = tmp_path / "roster.txt"
    roster.write_text("Alina\n", encoding="utf-8")

    rows = check_directory(input_dir, roster)

    assert dict(rows)["safe.txt"] == []
    assert dict(rows)["leak.txt"] == []
