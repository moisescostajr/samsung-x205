#!/usr/bin/env python3
import sys

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, Gdk, GLib, WebKit2

url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1/"

win = Gtk.Window()
win.set_title("Dashboard")
win.set_decorated(False)
win.set_keep_above(True)
win.connect("destroy", Gtk.main_quit)

def on_key(_w, event):
    if event.keyval == Gdk.KEY_F11:
        if win.get_window() and (
            win.get_window().get_state() & Gdk.WindowState.FULLSCREEN
        ):
            win.unfullscreen()
        else:
            win.fullscreen()
        return True
    return False

win.connect("key-press-event", on_key)

settings = WebKit2.Settings()
settings.set_enable_javascript(True)
settings.set_enable_fullscreen(True)
settings.set_media_playback_requires_user_gesture(False)

wv = WebKit2.WebView()
wv.set_settings(settings)
wv.load_uri(url)
win.add(wv)

def go_full(*_a):
    win.present()
    win.maximize()
    win.fullscreen()
    return False

win.connect("realize", lambda *_: GLib.idle_add(go_full))
win.show_all()
GLib.timeout_add(250, go_full)
Gtk.main()
