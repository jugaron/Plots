#!/usr/bin/env python3

# Copyright 2021-2022 Alexander Huntley

# This file is part of Plots.

# Plots is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# Plots is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with Plots.  If not, see <https://www.gnu.org/licenses/>.

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gdk, GLib, Gio, GdkPixbuf, Adw

from plots import formula, formularow, rowcommands, preferences, utils, graph
from plots.i18n import _
import plots.i18n
import sys
import importlib.resources as resources

class Plots(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.github.alexhuntley.Plots")
        self.rows = []
        self.slider_rows = []
        self.history = []
        self.history_position = 0  # index of the last undone command / next in line for redo
        self.overlay_source = None
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.PREFER_LIGHT)
        utils.install_excepthook()
        plots.i18n.bind()

    def do_activate(self):
        builder = Gtk.Builder()
        builder.add_from_string(utils.read_ui_file("plots.ui"))

        self.window = builder.get_object("main_window")
        self.add_window(self.window)
        self.window.set_title(_("Plots"))
        self.scroll = builder.get_object("equation_scroll")
        self.formula_box = builder.get_object("equation_box")
        self.add_equation_button = builder.get_object("add_equation")
        self.undo_button = builder.get_object("undo")
        self.redo_button = builder.get_object("redo")
        self.window.connect("close-request", self.delete_cb)

        self.gl_area = builder.get_object("gl")
        self.gl_area.app = self

        self.errorbar = builder.get_object("errorbar")
        self.errorbar.set_message_type(Gtk.MessageType.ERROR)
        self.errorbar.connect("response", lambda id, data: self.errorbar.set_property("revealed", False))
        self.errorbar.props.revealed = False
        self.errorlabel = builder.get_object("errorlabel")

        add_equation_action = Gio.SimpleAction.new("add-equation", None)
        add_equation_action.connect("activate", lambda _, __: self.add_equation(None))
        add_equation_action.set_enabled(True)
        self.add_action(add_equation_action)
        self.set_accels_for_action("app.add-equation", ["Return"])
        self.add_equation_button.set_action_name("app.add-equation")

        undo_action = Gio.SimpleAction.new("undo", None)
        undo_action.connect("activate", lambda _, __: self.undo(None))
        undo_action.set_enabled(True)
        self.add_action(undo_action)
        self.set_accels_for_action("app.undo", ["<primary>z"])
        self.undo_button.set_action_name("app.undo")

        redo_action = Gio.SimpleAction.new("redo", None)
        redo_action.connect("activate", lambda _, __: self.redo(None))
        redo_action.set_enabled(True)
        self.add_action(redo_action)
        self.set_accels_for_action("app.redo", ["<primary>y", "<primary><shift>z"])
        self.redo_button.set_action_name("app.redo")

        self.osd_revealer = builder.get_object("osd_revealer")
        self.osd_box = builder.get_object("osd_box")
        self.zoom_reset_revealer = builder.get_object("zoom_reset_revealer")
        self.graph_overlay = builder.get_object("graph_overlay")
        self.zoom_in_button = builder.get_object("zoom_in")
        self.zoom_out_button = builder.get_object("zoom_out")
        self.zoom_reset_button = builder.get_object("zoom_reset")

        zoom_in_action = Gio.SimpleAction.new("zoom-in", None)
        zoom_in_action.connect("activate", lambda _, __: self.gl_area.zoom(_, -1))
        zoom_in_action.set_enabled(True)
        self.add_action(zoom_in_action)
        self.set_accels_for_action("app.zoom-in", ["<primary>plus"])
        self.zoom_in_button.set_action_name("app.zoom-in")

        zoom_out_action = Gio.SimpleAction.new("zoom-out", None)
        zoom_out_action.connect("activate", lambda _, __: self.gl_area.zoom(_, 1))
        zoom_out_action.set_enabled(True)
        self.add_action(zoom_out_action)
        self.set_accels_for_action("app.zoom-out", ["<primary>minus"])
        self.zoom_out_button.set_action_name("app.zoom-out")

        zoom_reset_action = Gio.SimpleAction.new("zoom-reset", None)
        zoom_reset_action.connect("activate", lambda _, __: self.gl_area.reset_zoom(_))
        zoom_reset_action.set_enabled(True)
        self.add_action(zoom_reset_action)
        self.set_accels_for_action("app.zoom-reset", ["<primary>0"])
        self.zoom_reset_button.set_action_name("app.zoom-reset")
        self.gl_area.update_zoom_reset()

        menu_button = builder.get_object("menu_button")

        self.menu = Gio.Menu()
        self.menu.append(_("_Export…"), "app.export")
        self.menu.append(_("_Preferences"), "app.preferences")
        self.menu.append(_("Keyboard Shortcuts"), "win.show-help-overlay")
        self.menu.append(_("Help"), "app.help")
        self.menu.append(_("About Plots"), "app.about")
        menu_button.set_menu_model(self.menu)

        shortcuts_builder = Gtk.Builder()
        shortcuts_builder.add_from_string(utils.read_ui_file("shortcuts.ui"))
        shortcuts_dialog = shortcuts_builder.get_object("shortcuts_dialog")
        self.window.set_help_overlay(shortcuts_dialog)
        self.set_accels_for_action("win.show-help-overlay", ["<primary>question"])

        self.about_action = Gio.SimpleAction.new("about", None)
        self.about_action.connect("activate", self.about_cb)
        self.about_action.set_enabled(True)
        self.add_action(self.about_action)

        help_action = Gio.SimpleAction.new("help", None)
        help_action.connect("activate", self.help_cb)
        help_action.set_enabled(True)
        self.add_action(help_action)
        self.set_accels_for_action("app.help", ["F1"])

        export_action = Gio.SimpleAction.new("export", None)
        export_action.connect("activate", self.export_cb)
        export_action.set_enabled(True)
        self.add_action(export_action)
        self.set_accels_for_action("app.export", ["<primary>e"])

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", self.quit_cb)
        quit_action.set_enabled(True)
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<primary>q"])

        close_action = Gio.SimpleAction.new("close", None)
        close_action.connect("activate", self.close_cb)
        close_action.set_enabled(True)
        self.add_action(close_action)
        self.set_accels_for_action("app.close", ["<primary>w"])

        prefs_action = Gio.SimpleAction.new("preferences", None)
        prefs_action.connect("activate", self.prefs_cb)
        prefs_action.set_enabled(True)
        self.add_action(prefs_action)
        self.set_accels_for_action("app.preferences", ["<primary>comma"])
        self.prefs = preferences.Preferences(self.window)
        self.prefs.connect("updated", self.prefs_updated)

        self.set_overlay_timeout()

        self.add_equation(None, record=False)

        self.window.set_default_size(1280, 720)

        css = '''
.formula_box {
        background-color: @theme_base_color;
        border-bottom-color: @borders;
        border-bottom-width: 1px;
        border-bottom-style: solid;
}
.zoom-box {
        background-color: rgba(0, 0, 0, 0);
}
.zoom-button {
        padding: 4px;
}
'''
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(css, len(css))
        context = self.window.get_style_context()
        display = self.window.get_display()
        context.add_provider_for_display(display, css_provider,
                                         Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        motion_ctl = Gtk.EventControllerMotion()
        motion_ctl.connect("motion", self.motion_cb)
        self._old_motion = None
        self.gl_area.add_controller(motion_ctl)
        overlay_motion_ctl = Gtk.EventControllerMotion()
        overlay_motion_ctl.connect("enter", self.enter_overlay_cb)
        self.osd_box.add_controller(overlay_motion_ctl)
        self.refresh_history_buttons()
        self.window.show()

    def clear_overlay_timeout(self):
        if self.overlay_source is not None:
            GLib.source_remove(self.overlay_source)
            self.overlay_source = None

    def set_overlay_timeout(self):
        self.clear_overlay_timeout()
        self.overlay_source = GLib.timeout_add(2000, self.overlay_timeout_cb)

    def overlay_timeout_cb(self):
        self.osd_revealer.set_reveal_child(False)
        self.overlay_source = None

    def motion_cb(self, ctl, x, y):
        if (x, y) == self._old_motion:
            return False
        if not self.osd_revealer.get_reveal_child():
            self.osd_revealer.set_reveal_child(True)
        self.set_overlay_timeout()
        self._old_motion = (x, y)
        return False

    def enter_overlay_cb(self, ctl, x, y):
        self.clear_overlay_timeout()
        return False

    def update_shader(self):
        good, bad, unknown = [], [], []
        self.slider_rows.clear()
        for r in self.rows:
            data = r.get_data()
            if r.row_status == formularow.RowStatus.GOOD:
                good.append(data)
            elif r.row_status == formularow.RowStatus.BAD:
                bad.append(data)
            elif r.row_status == formularow.RowStatus.UNKNOWN:
                unknown.append(data)
            if isinstance(data, formularow.Slider):
                self.slider_rows.append(r)

        def attempt(formulae):
            formulae.sort(key=lambda x: x.priority, reverse=True)
            self.gl_area.update_fragment_shader(formulae)
            for f in formulae:
                f.owner.row_status = formularow.RowStatus.GOOD

        try:
            attempt(good + bad + unknown)
        except RuntimeError:
            try:
                attempt(good + unknown)
            except RuntimeError:
                try:
                    attempt(good)
                except RuntimeError:
                    attempt([])

    def dependency_changed(self, row):
        for r in self.rows:
            r.row_status = formularow.RowStatus.UNKNOWN

    def add_equation(self, _, record=True):
        row = formularow.FormulaBox(self)
        row.connect("dependency_changed", self.dependency_changed)
        self.rows.append(row)
        self.formula_box.append(row)
        row.editor.grab_focus()
        if record:
            self.add_to_history(rowcommands.Add(row, self.rows))

    def insert_row(self, index, row):
        self.rows.insert(index, row)
        prev = self.rows[index-1] if index > 0 else None
        self.formula_box.insert_child_after(row, prev)
        row.editor.grab_focus()

    def about_cb(self, action, _param):
        builder = Gtk.Builder.new_from_string(
            utils.read_ui_file("about.ui"),
            -1
        )
        about_window = builder.get_object("about_window")
        about_window.set_transient_for(self.window)
        about_window.present()

    def quit_cb(self, action, param):
        self.quit()

    def close_cb(self, action, param):
        self.window.close()

    def prefs_cb(self, action, param):
        self.prefs.show()

    def help_cb(self, action, _):
        Gtk.show_uri(None, "help:plots", Gdk.CURRENT_TIME)

    def export_cb(self, action, parameter):
        self.export_dialog = Gtk.FileChooserNative.new(
            title=_("Export image"),
            parent=self.window,
            action=Gtk.FileChooserAction.SAVE,
            accept_label=_("_Export"),
            cancel_label=_("_Cancel")
        )
        self.export_dialog.set_current_name(_("Untitled plot") + ".png")
        self.export_dialog.connect("response", self.export_response)
        self.export_dialog.set_modal(True)
        self.export_dialog.show()

    def export_response(self, dialog, response):
        if response == Gtk.ResponseType.ACCEPT:
            self.gl_area.export_target = dialog.get_file().get_path()
            self.gl_area.queue_draw()
        elif response == Gtk.ResponseType.CANCEL:
            pass
        dialog.destroy()
        self.export_dialog = None

    def delete_cb(self, window):
        self.prefs.save_config()

    def add_to_history(self, command):
        if self.can_redo():
            del self.history[self.history_position:]
        self.history.append(command)
        self.history_position = len(self.history)
        self.refresh_history_buttons()

    def can_undo(self):
        return self.history_position > 0

    def can_redo(self):
        return self.history_position < len(self.history)

    def undo(self, _):
        if self.can_undo():
            self.history_position -= 1
            self.history[self.history_position].undo(self)
            self.refresh_history_buttons()

    def redo(self, _):
        if self.history_position < len(self.history):
            self.history[self.history_position].do(self)
            self.history_position += 1
            self.refresh_history_buttons()

    def refresh_history_buttons(self):
        self.undo_button.props.sensitive = self.can_undo()
        self.redo_button.props.sensitive = self.can_redo()

    def prefs_updated(self, prefs):
        self.gl_area.queue_draw()


if __name__ == '__main__':
    Plots().run(sys.argv)
