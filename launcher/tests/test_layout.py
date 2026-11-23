from neurotlon_launcher.layout import (
    DEFAULT_TEAM_COLOR,
    Button,
    contains,
    fit_rect,
    parse_hex_color,
    wrap_text,
)


def measure(text: str) -> int:
    return len(text) * 10


def test_wrap_text_breaks_on_words() -> None:
    assert wrap_text("aa bb cc dd", 50, measure) == ["aa bb", "cc dd"]
    assert wrap_text("", 50, measure) == []
    assert wrap_text("short", 500, measure) == ["short"]


def test_wrap_text_keeps_long_word_whole() -> None:
    assert wrap_text("a verylongword b", 50, measure) == ["a", "verylongword", "b"]


def test_fit_rect_letterboxes_and_centers() -> None:
    assert fit_rect(640, 480, (0, 0, 800, 400)) == (133, 0, 533, 400)
    assert fit_rect(100, 100, (10, 20, 50, 100)) == (10, 45, 50, 50)
    assert fit_rect(0, 480, (0, 0, 10, 10)) == (0, 0, 0, 0)


def test_parse_hex_color() -> None:
    assert parse_hex_color("#aa00bb") == (170, 0, 187)
    for bad in (None, "", "red", "#12", "#gggggg"):
        assert parse_hex_color(bad) == DEFAULT_TEAM_COLOR


def test_button_hit_is_half_open() -> None:
    clicked: list[int] = []
    button = Button("x", (10, 10, 100, 50), lambda: clicked.append(1))
    assert button.hit((10, 10))
    assert button.hit((109, 59))
    assert not button.hit((110, 30))
    assert not button.hit((50, 60))
    assert contains((0, 0, 1, 1), (0, 0))
