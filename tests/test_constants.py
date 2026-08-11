"""
Sanity checks for the app.constants package: every declared __all__ name is
actually exported, values are of sane types, and the aggregating __init__
re-exports everything from the submodules.
"""
import app.constants as constants
from app.constants import colors, fonts, sizes, spacing


MODULES = [colors, fonts, sizes, spacing]


def test_every_module_all_entries_are_defined_and_exported():
    for module in MODULES:
        for name in module.__all__:
            assert hasattr(module, name), f"{module.__name__} declares {name!r} in __all__ but doesn't define it"
            assert hasattr(constants, name), f"app.constants doesn't re-export {name!r} from {module.__name__}"
            assert getattr(constants, name) is getattr(module, name)


def test_size_constants_are_positive_numbers():
    for name in sizes.__all__:
        value = getattr(sizes, name)
        if isinstance(value, tuple):
            assert all(isinstance(v, (int, float)) and v > 0 for v in value)
        else:
            assert isinstance(value, (int, float))
            assert value > 0


def test_spacing_margin_tuples_are_4_element_int_tuples():
    assert spacing.MARGIN_NONE == (0, 0, 0, 0)
    assert len(spacing.MARGIN_COMPACT) == 4
    assert all(isinstance(v, int) for v in spacing.MARGIN_COMPACT)


def test_color_row_tuples_are_valid_rgb():
    for name in ("COLOR_ROW_PENDING", "COLOR_ROW_DISCOUNT", "COLOR_ROW_PAYMENT",
                 "COLOR_ROW_PAYMENT_DARK", "COLOR_ROW_DIVIDER"):
        rgb = getattr(colors, name)
        assert len(rgb) == 3
        assert all(0 <= c <= 255 for c in rgb)


def test_color_border_light_is_a_hex_string():
    assert colors.COLOR_BORDER_LIGHT.startswith("#")


def test_font_sizes_increase_with_prominence():
    # cart item font should be bigger than the compact row font, and the
    # footer total should be the largest — encodes the intended visual hierarchy.
    assert fonts.FONT_SIZE_CART_ROW < fonts.FONT_SIZE_CART_ITEM < fonts.FONT_SIZE_FOOTER_TOTAL


def test_dialog_widths_increase_sm_to_xl():
    assert sizes.DIALOG_WIDTH_SM < sizes.DIALOG_WIDTH_MD < sizes.DIALOG_WIDTH_LG < sizes.DIALOG_WIDTH_XL


def test_main_window_minimums_are_reasonable_for_a_touchscreen_pos():
    assert sizes.MAIN_WINDOW_MIN_WIDTH >= 800
    assert sizes.MAIN_WINDOW_MIN_HEIGHT >= 600
