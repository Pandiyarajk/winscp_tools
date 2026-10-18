"""
Tests for sftp_pilot.theme: palettes (key parity and WCAG contrast), mode
resolution, preferences, geometry fitting, sortable tables and ttk styling.
Tk-backed tests share one root per module and skip where there is no display.

Author: Pandiyaraj Karuppasamy
Date: Oct-18-2026
"""

import gc
import json
import re
import sys
import types

import pytest

tk = pytest.importorskip("tkinter")  # absent on a minimal Linux install: skip the module
ttk = pytest.importorskip("tkinter.ttk")

from sftp_pilot import theme as T  # noqa: E402

HEX = re.compile(r"^#[0-9a-f]{6}$")


# ----------------------------------------------------------------- helpers

def _channel(value: int) -> float:
    c = value / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(color: str) -> float:
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def norm(color) -> str:
    """Tk may hand back a Tcl_Obj or upper case hex; normalise to lower case str"""
    return str(color).lower()


# ------------------------------------------------------------------ fixtures

@pytest.fixture(scope="module")
def tk_root():
    """One Tk root for the module, gc off so a dead root is never finalised off-thread"""
    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no display available: {e}")
    root.withdraw()
    gc.disable()
    yield root
    gc.enable()
    root.destroy()


@pytest.fixture
def themed(tk_root):
    """The root with the light theme applied (tests may switch it; reset after)"""
    yield tk_root
    T.apply_theme(tk_root, "light")
    gc.collect()


# ------------------------------------------------------------------ PALETTES

class TestPalettes:
    def test_modes_listed(self):
        assert set(T.PALETTES) == set(T.MODES) == {"light", "dark"}

    def test_same_keys(self):
        assert set(T.PALETTES["light"]) == set(T.PALETTES["dark"])
        assert len(T.PALETTES["light"]) > 10

    @pytest.mark.parametrize("mode", ["light", "dark"])
    def test_values_are_hex(self, mode):
        for key, value in T.PALETTES[mode].items():
            assert HEX.match(value), f"{mode}.{key} = {value!r}"

    def test_contrast_helper_sanity(self):
        assert contrast("#000000", "#ffffff") == pytest.approx(21.0)
        assert contrast("#777777", "#777777") == pytest.approx(1.0)

    @pytest.mark.parametrize("mode", ["light", "dark"])
    @pytest.mark.parametrize("fg,bg", [
        ("text", "bg"), ("text", "surface"), ("text", "surface2"),
        ("accent_text", "accent"), ("selection_text", "selection"),
    ])
    def test_body_text_contrast(self, mode, fg, bg):
        p = T.PALETTES[mode]
        assert contrast(p[fg], p[bg]) >= 4.5, f"{mode}: {fg} on {bg} = {contrast(p[fg], p[bg]):.2f}"

    @pytest.mark.parametrize("mode", ["light", "dark"])
    def test_muted_contrast(self, mode):
        p = T.PALETTES[mode]
        assert contrast(p["muted"], p["bg"]) >= 3.0

    @pytest.mark.parametrize("mode", ["light", "dark"])
    @pytest.mark.parametrize("tone", ["danger", "success", "warning", "info"])
    def test_status_colours_on_surface(self, mode, tone):
        p = T.PALETTES[mode]
        assert contrast(p[tone], p["surface"]) >= 3.0, f"{mode}.{tone} = {contrast(p[tone], p['surface']):.2f}"

    def test_light_and_dark_differ(self):
        assert luminance(T.PALETTES["light"]["bg"]) > luminance(T.PALETTES["dark"]["bg"])
        assert luminance(T.PALETTES["light"]["text"]) < luminance(T.PALETTES["dark"]["text"])


# --------------------------------------------------------------- resolve_mode

class TestResolveMode:
    @pytest.mark.parametrize("system_dark", [True, False])
    @pytest.mark.parametrize("mode", ["light", "dark"])
    def test_explicit_passes_through(self, monkeypatch, mode, system_dark):
        monkeypatch.setattr(T, "system_prefers_dark", lambda: system_dark)
        assert T.resolve_mode(mode) == mode

    @pytest.mark.parametrize("pref", ["auto", "", "junk", "DARK", None])
    def test_auto_and_junk_follow_system_dark(self, monkeypatch, pref):
        monkeypatch.setattr(T, "system_prefers_dark", lambda: True)
        assert T.resolve_mode(pref) == "dark"

    @pytest.mark.parametrize("pref", ["auto", "", "junk", "DARK", None])
    def test_auto_and_junk_follow_system_light(self, monkeypatch, pref):
        monkeypatch.setattr(T, "system_prefers_dark", lambda: False)
        assert T.resolve_mode(pref) == "light"


# ---------------------------------------------------------- system_prefers_dark

class TestSystemPrefersDark:
    def test_false_off_windows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        assert T.system_prefers_dark() is False
        monkeypatch.setattr(sys, "platform", "darwin")
        assert T.system_prefers_dark() is False

    @staticmethod
    def _fake_winreg(monkeypatch, value=None, error=None):
        calls = []
        fake = types.ModuleType("winreg")
        fake.HKEY_CURRENT_USER = object()

        class Key:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def open_key(hive, path):
            calls.append(("open", path))
            if error:
                raise error
            return Key()

        def query(key, name):
            calls.append(("query", name))
            return (value, 4)

        fake.OpenKey = open_key
        fake.QueryValueEx = query
        monkeypatch.setitem(sys.modules, "winreg", fake)
        monkeypatch.setattr(sys, "platform", "win32")
        return calls

    def test_zero_means_dark(self, monkeypatch):
        calls = self._fake_winreg(monkeypatch, value=0)
        assert T.system_prefers_dark() is True
        assert ("query", "AppsUseLightTheme") in calls
        assert any("Personalize" in c[1] for c in calls if c[0] == "open")

    def test_one_means_light(self, monkeypatch):
        self._fake_winreg(monkeypatch, value=1)
        assert T.system_prefers_dark() is False

    def test_oserror_means_false(self, monkeypatch):
        self._fake_winreg(monkeypatch, error=FileNotFoundError("no key"))
        assert T.system_prefers_dark() is False

    def test_plain_oserror_means_false(self, monkeypatch):
        self._fake_winreg(monkeypatch, error=OSError("denied"))
        assert T.system_prefers_dark() is False


# --------------------------------------------------------------------- Prefs

class TestPrefs:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "prefs.json"
        p = T.Prefs(str(path))
        p.set("theme", "dark")
        p.set("geometry", "1000x700+10+20")
        p.save()
        again = T.Prefs(str(path))
        assert again.get("theme") == "dark"
        assert again.get("geometry") == "1000x700+10+20"
        assert json.loads(path.read_text(encoding="utf-8"))["theme"] == "dark"

    def test_get_default(self, tmp_path):
        p = T.Prefs(str(tmp_path / "none.json"))
        assert p.get("x") is None
        assert p.get("x", 5) == 5

    def test_missing_file(self, tmp_path):
        assert T.Prefs(str(tmp_path / "absent.json")).data == {}

    def test_corrupt_file(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        assert T.Prefs(str(path)).data == {}

    def test_empty_file(self, tmp_path):
        path = tmp_path / "empty.json"
        path.write_text("", encoding="utf-8")
        assert T.Prefs(str(path)).data == {}

    def test_list_file(self, tmp_path):
        path = tmp_path / "list.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        p = T.Prefs(str(path))
        assert p.data == {}
        p.set("a", 1)  # still usable
        assert p.get("a") == 1

    def test_non_utf8_file(self, tmp_path):
        path = tmp_path / "bin.json"
        path.write_bytes(b"\xff\xfe\x00\x80")
        assert T.Prefs(str(path)).data == {}

    def test_save_into_missing_folder(self, tmp_path):
        p = T.Prefs(str(tmp_path / "no" / "such" / "dir" / "prefs.json"))
        p.set("a", 1)
        p.save()  # must not raise
        assert not (tmp_path / "no").exists()

    def test_save_overwrites(self, tmp_path):
        path = tmp_path / "p.json"
        p = T.Prefs(str(path))
        p.set("a", 1)
        p.save()
        p.set("a", 2)
        p.save()
        assert T.Prefs(str(path)).get("a") == 2


# --------------------------------------------------------------- fit_geometry

class TestFitGeometry:
    DEFAULT = "900x600"

    @pytest.fixture
    def root(self, tk_root):
        w, h = tk_root.winfo_screenwidth(), tk_root.winfo_screenheight()
        if w < 800 or h < 500:
            pytest.skip("screen too small for these geometries")
        return tk_root

    def test_good_geometry(self, root):
        assert T.fit_geometry(root, "800x500+40+30", self.DEFAULT) == "800x500+40+30"

    def test_none_and_empty(self, root):
        assert T.fit_geometry(root, None, self.DEFAULT) == self.DEFAULT
        assert T.fit_geometry(root, "", self.DEFAULT) == self.DEFAULT

    @pytest.mark.parametrize("saved", ["599x500+0+0", "800x399+0+0", "100x100+0+0", "0x0+0+0"])
    def test_too_small(self, root, saved):
        assert T.fit_geometry(root, saved, self.DEFAULT) == self.DEFAULT

    def test_minimum_accepted(self, root):
        assert T.fit_geometry(root, "600x400+0+0", self.DEFAULT) == "600x400+0+0"

    def test_larger_than_screen(self, root):
        w, h = root.winfo_screenwidth(), root.winfo_screenheight()
        assert T.fit_geometry(root, f"{w + 1}x500+0+0", self.DEFAULT) == self.DEFAULT
        assert T.fit_geometry(root, f"800x{h + 1}+0+0", self.DEFAULT) == self.DEFAULT

    @pytest.mark.parametrize("saved", ["garbage", "axb+1+2", "800x+1+2", "800+1+2", "800x500+a+b",
                                       "800x500+1", "800x500+1+2+3", "x", "+", "1.5x2.5+0+0"])
    def test_garbage(self, root, saved):
        assert T.fit_geometry(root, saved, self.DEFAULT) == self.DEFAULT

    def test_no_position_defaults_to_origin(self, root):
        assert T.fit_geometry(root, "800x500", self.DEFAULT) == "800x500+0+0"

    def test_negative_position_clamped(self, root):
        assert T.fit_geometry(root, "800x500+-300+-200", self.DEFAULT) == "800x500+0+0"

    def test_far_off_screen_clamped_back(self, root):
        w, h = root.winfo_screenwidth(), root.winfo_screenheight()
        out = T.fit_geometry(root, "800x500+99999+88888", self.DEFAULT)
        assert out == f"800x500+{w - 120}+{h - 120}"
        x, y = (int(v) for v in out.split("+")[1:])
        assert 0 <= x < w and 0 <= y < h

    def test_result_is_valid_tk_geometry(self, root):
        out = T.fit_geometry(root, "800x500+99999+-5", self.DEFAULT)
        top = tk.Toplevel(root)
        try:
            top.withdraw()
            top.geometry(out)  # raises TclError if malformed
        finally:
            top.destroy()


# ------------------------------------------------------------- make_sortable

ARROW_UP, ARROW_DOWN = "▲", "▼"


def _build_tree(root, rows, columns=("name", "value")):
    tree = ttk.Treeview(root, columns=columns, show="headings")
    for c in columns:
        tree.heading(c, text=c.title())
    for i, row in enumerate(rows):
        values, tags = row if isinstance(row, tuple) and isinstance(row[1], (list, tuple)) and \
            isinstance(row[0], (list, tuple)) else (row, ())
        tree.insert("", "end", iid=f"r{i}", values=values, tags=tuple(tags))
    T.make_sortable(tree, list(columns))
    return tree


def _click(tree, column):
    cmd = tree.heading(column, "command")
    assert cmd, f"heading {column} has no command"
    tree.tk.call(cmd)


def _col(tree, column):
    return [tree.set(i, column) for i in tree.get_children("")]


class TestMakeSortable:
    @pytest.fixture
    def numeric_tree(self, tk_root):
        rows = [(["a", "10"], ()), (["b", "9"], ()), (["c", "100"], ()), (["d", "1"], ())]
        tree = _build_tree(tk_root, rows)
        yield tree
        tree.destroy()

    def test_numeric_ascending_then_descending(self, numeric_tree):
        tree = numeric_tree
        _click(tree, "value")
        assert _col(tree, "value") == ["1", "9", "10", "100"]  # not "1", "10", "100", "9"
        _click(tree, "value")
        assert _col(tree, "value") == ["100", "10", "9", "1"]
        _click(tree, "value")  # a third click goes back to ascending
        assert _col(tree, "value") == ["1", "9", "10", "100"]

    def test_values_with_units(self, tk_root):
        rows = [(["a", "100 ms"], ()), (["b", "9 ms"], ()), (["c", "10 ms"], ())]
        tree = _build_tree(tk_root, rows)
        try:
            _click(tree, "value")
            assert _col(tree, "value") == ["9 ms", "10 ms", "100 ms"]
        finally:
            tree.destroy()

    def test_numbers_sort_before_text_and_text_is_case_insensitive(self, tk_root):
        rows = [(["x", "banana"], ()), (["y", "20"], ()), (["z", "Apple"], ()), (["w", "3"], ()),
                (["v", "cherry"], ())]
        tree = _build_tree(tk_root, rows)
        try:
            _click(tree, "value")
            assert _col(tree, "value") == ["3", "20", "Apple", "banana", "cherry"]
        finally:
            tree.destroy()

    def test_text_column(self, numeric_tree):
        _click(numeric_tree, "name")
        assert _col(numeric_tree, "name") == ["a", "b", "c", "d"]
        _click(numeric_tree, "name")
        assert _col(numeric_tree, "name") == ["d", "c", "b", "a"]

    def test_decimals_and_negatives(self, tk_root):
        rows = [(["a", "2.5"], ()), (["b", "-1"], ()), (["c", "10"], ()), (["d", "0.5"], ())]
        tree = _build_tree(tk_root, rows)
        try:
            _click(tree, "value")
            assert _col(tree, "value") == ["-1", "0.5", "2.5", "10"]
        finally:
            tree.destroy()

    def test_empty_values_do_not_crash(self, tk_root):
        rows = [(["a", ""], ()), (["b", "5"], ()), (["c", ""], ())]
        tree = _build_tree(tk_root, rows)
        try:
            _click(tree, "value")
            assert _col(tree, "value")[0] == "5"  # numbers first, blanks (text) after
        finally:
            tree.destroy()

    def test_empty_tree(self, tk_root):
        tree = _build_tree(tk_root, [])
        try:
            _click(tree, "value")
            assert tree.get_children("") == ()
        finally:
            tree.destroy()

    def test_arrow_marker_follows_sorted_heading(self, numeric_tree):
        tree = numeric_tree
        assert ARROW_UP not in tree.heading("value", "text")
        _click(tree, "value")
        assert tree.heading("value", "text") == "Value  " + ARROW_UP
        assert tree.heading("name", "text") == "Name"
        _click(tree, "value")
        assert tree.heading("value", "text") == "Value  " + ARROW_DOWN
        _click(tree, "name")  # arrow leaves the previous heading
        assert tree.heading("value", "text") == "Value"
        assert tree.heading("name", "text") == "Name  " + ARROW_UP
        _click(tree, "name")
        assert tree.heading("name", "text") == "Name  " + ARROW_DOWN
        assert ARROW_UP not in tree.heading("name", "text")

    def test_switching_column_resets_to_ascending(self, numeric_tree):
        tree = numeric_tree
        _click(tree, "value")
        _click(tree, "value")  # descending on value
        _click(tree, "name")   # new column starts ascending
        assert _col(tree, "name") == ["a", "b", "c", "d"]

    def test_zebra_reapplied(self, numeric_tree):
        tree = numeric_tree
        _click(tree, "value")
        tags = [tree.item(i, "tags") for i in tree.get_children("")]
        assert [("even" in t, "odd" in t) for t in tags] == [(True, False), (False, True),
                                                             (True, False), (False, True)]
        _click(tree, "value")  # reversing re-stripes from the top
        tags = [tree.item(i, "tags") for i in tree.get_children("")]
        assert ["even" if "even" in t else "odd" for t in tags] == ["even", "odd", "even", "odd"]
        for t in tags:
            assert not ("even" in t and "odd" in t)

    def test_other_tags_kept_and_stale_zebra_replaced(self, tk_root):
        rows = [(["a", "3"], ["failed", "odd"]), (["b", "1"], ["ok", "even"]), (["c", "2"], ["muted"])]
        tree = _build_tree(tk_root, rows)
        try:
            _click(tree, "value")
            by_value = {tree.set(i, "value"): tree.item(i, "tags") for i in tree.get_children("")}
            assert "ok" in by_value["1"] and "even" in by_value["1"] and "odd" not in by_value["1"]
            assert "muted" in by_value["2"] and "odd" in by_value["2"] and "even" not in by_value["2"]
            assert "failed" in by_value["3"] and "even" in by_value["3"] and "odd" not in by_value["3"]
            _click(tree, "value")
            by_value = {tree.set(i, "value"): tree.item(i, "tags") for i in tree.get_children("")}
            assert "failed" in by_value["3"] and "ok" in by_value["1"] and "muted" in by_value["2"]
            for tags in by_value.values():
                assert sum(t in ("even", "odd") for t in tags) == 1
        finally:
            tree.destroy()

    def test_rows_keep_their_iids_and_all_columns(self, numeric_tree):
        tree = numeric_tree
        _click(tree, "value")
        assert sorted(tree.get_children("")) == ["r0", "r1", "r2", "r3"]
        assert tree.set("r0", "name") == "a" and tree.set("r0", "value") == "10"


class TestSortKey:
    def test_numeric_before_text(self):
        assert T._sort_key("5") < T._sort_key("abc")

    def test_numeric_order(self):
        assert T._sort_key("9") < T._sort_key("10") < T._sort_key("100 ms")

    def test_text_case_insensitive(self):
        assert T._sort_key("Apple") < T._sort_key("banana")

    def test_blank(self):
        assert T._sort_key("") == (1, "")
        assert T._sort_key("   ") == (1, "   ")


# --------------------------------------------------------------- apply_theme

class TestApplyTheme:
    @pytest.mark.parametrize("mode", ["light", "dark"])
    def test_returns_palette(self, themed, mode):
        assert T.apply_theme(themed, mode) is T.PALETTES[mode]

    def test_unknown_mode_falls_back_to_light(self, themed):
        assert T.apply_theme(themed, "bogus") is T.PALETTES["light"]

    @staticmethod
    def _check_styles(root, mode):
        p = T.PALETTES[mode]
        s = ttk.Style(root)
        assert s.theme_use() == "clam"
        assert norm(s.lookup("Primary.TButton", "background")) == p["accent"]
        assert norm(s.lookup("Primary.TButton", "foreground")) == p["accent_text"]
        assert norm(s.lookup("Danger.TButton", "foreground")) == p["danger"]
        assert norm(s.lookup("Danger.TButton", "background")) == p["surface"]
        assert norm(s.lookup("Treeview", "background")) == p["surface"]
        assert norm(s.lookup("Treeview", "foreground")) == p["text"]
        assert norm(s.lookup("Treeview", "fieldbackground")) == p["surface"]
        assert norm(s.lookup("TNotebook.Tab", "background")) == p["surface2"]
        assert norm(s.lookup("TNotebook.Tab", "foreground")) == p["muted"]
        assert norm(s.lookup("TNotebook", "background")) == p["bg"]
        assert norm(s.lookup("TLabel", "foreground")) == p["text"]
        assert norm(s.lookup("Muted.TLabel", "foreground")) == p["muted"]
        assert norm(s.lookup("Treeview.Heading", "background")) == p["surface2"]
        for tone in ("success", "danger", "warning", "info"):
            assert norm(s.lookup(f"{tone.capitalize()}.TLabel", "foreground")) == p[tone]
        assert norm(root.cget("background")) == p["bg"]

    @pytest.mark.parametrize("mode", ["light", "dark"])
    def test_styles_have_palette_colours(self, themed, mode):
        T.apply_theme(themed, mode)
        self._check_styles(themed, mode)

    def test_light_dark_light_leaves_no_stale_colour(self, themed):
        T.apply_theme(themed, "light")
        self._check_styles(themed, "light")
        T.apply_theme(themed, "dark")
        self._check_styles(themed, "dark")
        T.apply_theme(themed, "light")
        self._check_styles(themed, "light")

    def test_twice_in_a_row(self, themed):
        T.apply_theme(themed, "dark")
        T.apply_theme(themed, "dark")
        self._check_styles(themed, "dark")

    def test_selected_state_maps(self, themed):
        T.apply_theme(themed, "dark")
        p = T.PALETTES["dark"]
        s = ttk.Style(themed)
        assert norm(s.lookup("Treeview", "background", ["selected"])) == p["selection"]
        assert norm(s.lookup("Treeview", "foreground", ["selected"])) == p["selection_text"]
        assert norm(s.lookup("Primary.TButton", "background", ["active"])) == p["accent_hover"]
        assert norm(s.lookup("TNotebook.Tab", "foreground", ["selected"])) == p["accent"]

    def test_existing_toplevel_recoloured(self, themed):
        top = tk.Toplevel(themed)
        try:
            T.apply_theme(themed, "dark")
            assert norm(top.cget("background")) == T.PALETTES["dark"]["bg"]
            T.apply_theme(themed, "light")
            assert norm(top.cget("background")) == T.PALETTES["light"]["bg"]
        finally:
            top.destroy()

    def test_widgets_created_afterwards_use_theme(self, themed):
        T.apply_theme(themed, "dark")
        frame = ttk.Frame(themed)
        try:
            assert norm(ttk.Style(themed).lookup(frame.winfo_class(), "background")) == T.PALETTES["dark"]["bg"]
        finally:
            frame.destroy()


# ------------------------------------------------------------ style_tree_tags

class TestStyleTreeTags:
    @pytest.mark.parametrize("mode", ["light", "dark"])
    def test_status_foregrounds(self, tk_root, mode):
        p = T.PALETTES[mode]
        tree = ttk.Treeview(tk_root)
        try:
            T.style_tree_tags(tree, p)
            expected = {"ok": "success", "failed": "danger", "running": "info",
                        "retrying": "warning", "muted": "muted"}
            for tag, key in expected.items():
                assert norm(tree.tag_configure(tag, "foreground")) == p[key], tag
        finally:
            tree.destroy()

    @pytest.mark.parametrize("mode", ["light", "dark"])
    def test_zebra_backgrounds(self, tk_root, mode):
        p = T.PALETTES[mode]
        tree = ttk.Treeview(tk_root)
        try:
            T.style_tree_tags(tree, p)
            assert norm(tree.tag_configure("even", "background")) == p["surface"]
            assert norm(tree.tag_configure("odd", "background")) == p["surface2"]
        finally:
            tree.destroy()

    def test_restyle_switches_colours(self, tk_root):
        tree = ttk.Treeview(tk_root)
        try:
            T.style_tree_tags(tree, T.PALETTES["light"])
            T.style_tree_tags(tree, T.PALETTES["dark"])
            assert norm(tree.tag_configure("failed", "foreground")) == T.PALETTES["dark"]["danger"]
        finally:
            tree.destroy()


# --------------------------------------------------------------------- scale

class TestScale:
    def test_positive_int(self, tk_root):
        for px in (1, 6, 14, 26, 100):
            out = T.scale(tk_root, px)
            assert isinstance(out, int) and out >= 1

    def test_monotonic(self, tk_root):
        values = [T.scale(tk_root, px) for px in range(1, 200)]
        assert values == sorted(values)
        assert T.scale(tk_root, 200) > T.scale(tk_root, 10)

    def test_never_below_one(self, tk_root):
        assert T.scale(tk_root, 0) == 1

    def test_at_96_dpi_is_identity(self, tk_root, monkeypatch):
        monkeypatch.setattr(tk_root, "winfo_fpixels", lambda spec: 96.0, raising=False)
        assert T.scale(tk_root, 26) == 26

    def test_double_dpi_doubles(self, tk_root, monkeypatch):
        monkeypatch.setattr(tk_root, "winfo_fpixels", lambda spec: 192.0, raising=False)
        assert T.scale(tk_root, 26) == 52

    def test_tcl_error_returns_input(self):
        class Broken:
            def winfo_fpixels(self, spec):
                raise tk.TclError("dead")

        assert T.scale(Broken(), 17) == 17
