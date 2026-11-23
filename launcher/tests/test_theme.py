from neurotlon_launcher import theme


def test_mix_blends_and_clamps() -> None:
    assert theme.mix((255, 0, 0), (0, 0, 255), 0.5) == (128, 0, 128)
    assert theme.mix((10, 20, 30), (200, 200, 200), 1) == (10, 20, 30)
    assert theme.mix((10, 20, 30), (200, 200, 200), -3) == (200, 200, 200)


def test_on_color_picks_readable_text() -> None:
    assert theme.on_color(theme.GREEN) == theme.BG
    assert theme.on_color(theme.YELLOW) == theme.BG
    assert theme.on_color((20, 20, 40)) == theme.TEXT
    for fill in (theme.ACCENT, theme.GREEN, theme.YELLOW, theme.SURFACE_HI):
        assert theme.contrast(theme.on_color(fill), fill) >= 4.5


def test_readable_on_dark_lifts_dark_team_colors() -> None:
    dark_blue = (20, 30, 120)
    lifted = theme.readable_on_dark(dark_blue)
    assert theme.contrast(lifted, theme.SURFACE) >= 4.5
    assert theme.readable_on_dark(theme.GREEN) == theme.GREEN


def test_initials_prefers_name_then_code_digits() -> None:
    assert theme.initials("анна", "NT03") == "А"
    assert theme.initials(None, "NT07") == "07"
    assert theme.initials("  ", "NT07") == "07"
    assert theme.initials(None, "XY") == "XY"
