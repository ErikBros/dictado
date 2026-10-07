from ecoscribe.wer import wer


def test_identical_is_zero():
    assert wer("hej och välkommen", "hej och välkommen") == 0.0


def test_one_substitution_in_four():
    assert wer("we meet on thursday", "we meet on tuesday") == 0.25


def test_punctuation_and_case_ignored():
    assert wer("Hej, och välkommen!", "hej och välkommen") == 0.0


def test_greek_punctuation_ignored_accents_kept():
    assert wer("Τι κάνεις; Καλά·", "τι κάνεις καλά") == 0.0
    assert wer("κάνεις", "κανεις") == 1.0  # a missing accent is a different word


def test_insertions_and_deletions():
    assert wer("a b c", "a c") == 1 / 3
    assert wer("a b", "a b c d") == 1.0


def test_empty_reference():
    assert wer("", "") == 0.0
    assert wer("", "x") == 1.0
