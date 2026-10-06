"""Repeat guard tests on REAL data/history.json entries (run: cd pipeline && python test_repeat_guard.py, or pytest).

Each test takes the real history up to and including the real entry it needs, so the 15-video window is the one
production saw. The buffer is stubbed empty (no network).
"""
import copy

import repeat_guard as rg
from common import load_history

rg._BUFFER["metas"] = []  # no buffer reads in tests
HISTORY = load_history()


def _upto(title: str) -> list[dict]:
    """Real history up to (and including) the last entry with this title."""
    i = max(k for k, h in enumerate(HISTORY) if h.get("title") == title)
    return HISTORY[: i + 1]


def _entry(title: str) -> dict:
    return copy.deepcopy(next(h for h in reversed(HISTORY) if h.get("title") == title))


def test_baba_yaga_allowed_after_owlman():
    """The real Oct 5 false positive: every legend has subgenre 'legend / folklore'."""
    h = _upto("The Legend of the Cornish Owlman")
    assert rg.repeat_of("Baba Yaga", history=h) == ""  # picker stage
    assert rg.repeat_of("Baba Yaga The Witch In The Woods", "Baba Yaga", "legend / folklore", "Baba Yaga",
                        history=h) == ""  # finished-story stage (exactly what buffer_fill #12/#13 checked)


def test_second_baba_yaga_blocked():
    h = HISTORY + [{**_entry("The Legend of the Lougawou"), "date": "2099-01-01_0000", "buffered": "2099-01-01_0000",
                    "title": "Baba Yaga The Witch In The Woods", "case": "Baba Yaga", "source": "Baba Yaga",
                    "opening": None}]
    assert "baba yaga" in rg.repeat_of("Baba Yaga", history=h)
    assert rg.repeat_of("The Bone Hut of Baba Yaga", history=h)


def test_second_baba_yaga_blocked_without_case():
    """A legend entry that has no case / source: the subject comes from the title."""
    h = HISTORY + [{"date": "2099-01-01_0000", "buffered": "2099-01-01_0000", "mode": "lore",
                    "title": "Baba Yaga The Witch In The Woods", "subgenre": "legend / folklore"}]
    assert rg.repeat_of("Baba Yaga", history=h)


def test_lizzie_borden_blocked():
    h = _upto("The Lizzie Borden Murders")
    assert "lizzie borden" in rg.repeat_of("The Lizzie Borden Mystery", "Lizzie Borden", history=h)
    assert rg.repeat_of("Lizzie Borden", history=h)


def test_nachzehrer_remake_blocked():
    """The real remake entry's title ('The Corpse That Chewed Its Shroud') never names it; its case does."""
    h = _upto("The Corpse That Chewed Its Shroud")
    assert "nachzehrer" in rg.repeat_of("Nachzehrer", history=h)


def test_nachzehrer_blocked_without_case():
    e = _entry("The German Legend of the Nachzehrer")
    e.pop("case", None)
    h = HISTORY + [{**e, "buffered": "2099-01-01_0000"}]
    assert "nachzehrer" in rg.repeat_of("Nachzehrer", history=h)


def test_bloody_mary_blocked():
    h = _upto("Bloody Mary Mirror Legend")
    assert rg.repeat_of("Bloody Mary", history=h)
    assert rg.repeat_of("Bloody Mary origins: where did the name come from?", history=h)
    e = _entry("Bloody Mary Mirror Legend")
    e.pop("case", None)
    assert rg.repeat_of("Bloody Mary", history=HISTORY + [{**e, "buffered": "2099-01-01_0000"}])


def test_other_legends_allowed():
    h = _upto("The Legend of the Lougawou")
    for topic in ("Soucouyant", "Baba Yaga", "Wendigo", "Kappa"):
        assert rg.repeat_of(topic, history=h) == "", topic


def test_outside_window_allowed():
    """The Manananggal (Sept 25) is more than 15 videos back."""
    assert rg.repeat_of("Manananggal", history=HISTORY) == ""


def test_same_fiction_subgenre_blocked():
    h = _upto("Municipal Water Reservoir Security Camera")
    assert rg.repeat_of("found footage / old tape or camera roll", history=h)


def test_generic_words_never_match():
    h = _upto("The Legend of the Lougawou")
    assert rg.repeat_of("The Legend of the Witch", history=h) == ""
    assert rg.repeat_of("The Mysterious Disappearance", history=h) == ""


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for n, f in tests:
        f()
        print(f"PASS {n}")
    print(f"{len(tests)} passed")
