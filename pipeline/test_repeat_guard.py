"""Unit tests for repeat_guard.py to verify false positive fixes."""
from repeat_guard import repeat_of


def test_different_folklore_creatures_allowed():
    """Baba Yaga vs Cornish Owlman = allowed (different specific subjects, same broad subgenre)."""
    history = [
        {
            "title": "The Legend of the Cornish Owlman",
            "case": "Owlman",
            "subgenre": "legend / folklore",
            "buffered": "2026-10-01_0000"
        }
    ]

    # Baba Yaga should be allowed even though both are "legend / folklore"
    result = repeat_of("Baba Yaga", "The Witch In The Woods", history=history)
    assert result == "", f"Expected Baba Yaga to be allowed, but got: {result}"


def test_same_case_name_blocked():
    """Lizzie Borden Murders vs Lizzie Borden Mystery = blocked (same specific case)."""
    history = [
        {
            "title": "The Lizzie Borden Murders",
            "case": "Lizzie Borden",
            "subgenre": "true crime case file",
            "buffered": "2026-10-03_0000"
        }
    ]

    # Any Lizzie Borden topic should be blocked
    result = repeat_of("Lizzie Borden Mystery", "The Lizzie Borden Case", history=history)
    assert result != "", "Expected Lizzie Borden Mystery to be blocked"
    assert "lizzie borden" in result.lower(), f"Expected 'lizzie borden' in reason, got: {result}"


def test_remake_of_same_topic_blocked():
    """Nachzehrer vs Nachzehrer remake = blocked (same case name)."""
    history = [
        {
            "title": "The German Legend of the Nachzehrer",
            "case": "Nachzehrer",
            "subgenre": "legend / folklore",
            "buffered": "2026-09-26_0000"
        }
    ]

    # Remake with same case name should be blocked
    result = repeat_of("The Corpse That Chewed Its Shroud", "Nachzehrer", history=history)
    assert result != "", "Expected Nachzehrer remake to be blocked"
    assert "nachzehrer" in result.lower(), f"Expected 'nachzehrer' in reason, got: {result}"


def test_topic_family_match_blocked():
    """Topic families (e.g., bloody mary) should still block."""
    history = [
        {
            "title": "Bloody Mary Mirror Legend",
            "case": "Bloody Mary (folklore)",
            "subgenre": "legend / folklore",
            "buffered": "2026-09-30_0000"
        }
    ]

    # Another Bloody Mary should be blocked via topic_families
    result = repeat_of("Bloody Mary origins", "Where did Bloody Mary come from", history=history)
    assert result != "", "Expected Bloody Mary repeat to be blocked via topic families"


def test_different_cases_same_category_allowed():
    """Different true crime cases should be allowed even if same subgenre."""
    history = [
        {
            "title": "The Kidnapping of Patty Hearst",
            "case": "Patty Hearst",
            "subgenre": "true crime case file",
            "buffered": "2026-09-26_0000"
        }
    ]

    # Different true crime case should be allowed
    result = repeat_of("The Unabomber Sketch", "Ted Kaczynski", history=history)
    assert result == "", f"Expected different true crime case to be allowed, but got: {result}"


if __name__ == "__main__":
    tests = [
        ("Different folklore creatures allowed", test_different_folklore_creatures_allowed),
        ("Same case name blocked", test_same_case_name_blocked),
        ("Remake of same topic blocked", test_remake_of_same_topic_blocked),
        ("Topic family match blocked", test_topic_family_match_blocked),
        ("Different cases same category allowed", test_different_cases_same_category_allowed),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            test_func()
            print(f"✓ {name} PASSED")
            passed += 1
        except AssertionError as e:
            print(f"✗ {name} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {name} ERROR: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
