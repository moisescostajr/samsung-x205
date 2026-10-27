#!/usr/bin/env python3
"""Session-bus stand-in for org.gnome.SettingsDaemon.Power.

Phosh 0.24's quick-settings brightness slider writes the Brightness
property (0–100) on org.gnome.SettingsDaemon.Power.Screen. Real
gsd-power will not start here: it needs systemd-logind, which this
BusyBox PID 1 session does not have. This stub maps that property onto
/sys/class/backlight/sprd_backlight and stamps a file so auto-brightness
does not immediately fight a manual QS change.
"""
import os
import sys
import time

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

BUS_NAME = "org.gnome.SettingsDaemon.Power"
OBJ_PATH = "/org/gnome/SettingsDaemon/Power"
IFACE = "org.gnome.SettingsDaemon.Power.Screen"
BL = "/sys/class/backlight/sprd_backlight/brightness"
BL_MAX = "/sys/class/backlight/sprd_backlight/max_brightness"
MANUAL = "/run/gta8-brightness-manual"

INTROSPECTION_XML = """
<node>
  <interface name="org.gnome.SettingsDaemon.Power.Screen">
    <method name="StepUp">
      <arg type="i" name="new_percentage" direction="out"/>
      <arg type="s" name="connector" direction="out"/>
    </method>
    <method name="StepDown">
      <arg type="i" name="new_percentage" direction="out"/>
      <arg type="s" name="connector" direction="out"/>
    </method>
    <property name="Brightness" type="i" access="readwrite"/>
  </interface>
</node>
"""


def _bl_max():
    try:
        return max(1, int(open(BL_MAX).read().strip()))
    except OSError:
        return 255


def get_pct():
    try:
        cur = int(open(BL).read().strip())
    except OSError:
        return 50
    return max(0, min(100, int(round(100.0 * cur / _bl_max()))))


def set_pct(pct):
    pct = max(0, min(100, int(pct)))
    raw = max(1, min(_bl_max(), int(round(pct * _bl_max() / 100.0))))
    try:
        open(BL, "w").write("%d\n" % raw)
        open(MANUAL, "w").write("%d\n" % int(time.time()))
    except OSError as exc:
        print("backlight write failed:", exc, file=sys.stderr)
        return get_pct()
    return pct


class PowerStub:
    def __init__(self):
        self.connection = None
        self.owner_id = Gio.bus_own_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameOwnerFlags.NONE,
            self.on_bus_acquired,
            self.on_name_acquired,
            self.on_name_lost,
        )

    def on_bus_acquired(self, connection, name):
        self.connection = connection
        node = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)
        connection.register_object(
            OBJ_PATH,
            node.interfaces[0],
            self.on_method,
            self.on_get,
            self.on_set,
        )

    def on_name_acquired(self, connection, name):
        print("acquired", name, "brightness", get_pct(), flush=True)
        self.emit_brightness()

    def on_name_lost(self, connection, name):
        print("lost", name, file=sys.stderr, flush=True)
        sys.exit(1)

    def emit_brightness(self):
        if self.connection is None:
            return
        self.connection.emit_signal(
            None,
            OBJ_PATH,
            "org.freedesktop.DBus.Properties",
            "PropertiesChanged",
            GLib.Variant(
                "(sa{sv}as)",
                (IFACE, {"Brightness": GLib.Variant("i", get_pct())}, []),
            ),
        )

    def on_method(
        self, connection, sender, path, iface, method, params, invocation
    ):
        pct = get_pct()
        if method == "StepUp":
            pct = set_pct(min(100, pct + 5))
        elif method == "StepDown":
            pct = set_pct(max(0, pct - 5))
        else:
            invocation.return_error_literal(
                Gio.dbus_error_quark(),
                Gio.DBusError.UNKNOWN_METHOD,
                "unknown method %s" % method,
            )
            return
        self.emit_brightness()
        invocation.return_value(GLib.Variant("(is)", (pct, "DSI-1")))

    def on_get(self, connection, sender, path, iface, prop):
        if prop == "Brightness":
            return GLib.Variant("i", get_pct())
        return None

    def on_set(self, connection, sender, path, iface, prop, value):
        if prop != "Brightness":
            return False
        set_pct(value.unpack())
        self.emit_brightness()
        return True


def main():
    os.environ.setdefault("XDG_RUNTIME_DIR", "/run/user/0")
    PowerStub()
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
