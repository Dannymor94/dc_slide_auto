"""Self-check for the deterministic program parser. Run: python3 build/test_parse_program.py"""
from extract_program import parse_program, _validate


def test_basic_and_notes():
    prog = parse_program(
        "🔸 08:30 — Сбор в джагрити\n"
        "08:45 - Дхармачакра\n"
        "11:00 — Сатсанг (ведущий - Индранатха)\n"
        "Немного поговорим о том, как дела\n"
        "Полезные ссылки\n"          # section header → ignored, not a note
    )
    times = [p["time"] for p in prog]
    assert times == ["08:30", "08:45", "11:00"], times
    assert prog[0]["title"] == "Сбор в джагрити"
    assert prog[2]["title"] == "Сатсанг (ведущий - Индранатха)"   # inner dash kept
    assert prog[2]["note"].startswith("Немного"), prog[2]["note"]
    assert all(p["_llm_uncertain"] is False for p in prog)


def test_midnight_crossing():
    # Real 2026-02-13 all-night program — must not choke on 00:05/00:30.
    prog = parse_program("23:30 — Ишвара Пранидхана\n00:05 — прасад\n00:30 — Завершение")
    assert [p["time"] for p in prog] == ["23:30", "00:05", "00:30"]
    assert _validate(prog, "23:30 00:05 00:30", "regex", strict_titles=False) is None


def test_empty_and_no_schedule():
    assert parse_program("") == []
    assert parse_program("Намаскар, друзья! Приходите в 15:00.") == []   # prose, time mid-line


def test_non_cyrillic_title_rejected():
    # Real train-trip post lines «17:20 → 18:56» must NOT count as schedule items.
    prog = parse_program("Обратно:\n17:20 → 18:56\n17:45 → 19:32")
    assert prog == [], prog


def test_is_program_post_structural():
    from fetch_telegram import is_program_post
    assert is_program_post("08:30 — Сбор в джагрити\n08:45 — Дхармачакра") is True   # 2 items
    assert is_program_post("Едем в Таганрог.\n17:20 → 18:56\n17:45 → 19:32") is False  # 0 items
    assert is_program_post("Встречаемся в 10:00 в джагрити на программе") is False     # prose, 0 items
    assert is_program_post("12:30 — Дхармачакра") is False   # 1 item < N (needs Сбор+ДЧ)


if __name__ == "__main__":
    test_basic_and_notes()
    test_midnight_crossing()
    test_empty_and_no_schedule()
    test_non_cyrillic_title_rejected()
    test_is_program_post_structural()
    print("ok")
