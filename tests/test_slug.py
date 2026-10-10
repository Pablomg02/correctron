from correctron.slug import slugify, student_slug


def test_slugify_basic():
    assert slugify("Mecánica de Vuelo") == "mecanica-de-vuelo"
    assert slugify("  Ñandú   (2º) ") == "nandu-2o"
    assert slugify("Claude Opus") == "claude-opus"


def test_slugify_empty_gives_x():
    assert slugify("") == "x"
    assert slugify("¿?!") == "x"


def test_student_slug():
    assert student_slug("Álvarez López", "Ana", set()) == "alvarez-lopez-ana"
    assert student_slug("Álvarez López", "Ana", {"alvarez-lopez-ana"}) == "alvarez-lopez-ana-2"
    taken = {"alvarez-lopez-ana", "alvarez-lopez-ana-2"}
    assert student_slug("Álvarez López", "Ana", taken) == "alvarez-lopez-ana-3"
