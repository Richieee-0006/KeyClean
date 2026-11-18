#!/usr/bin/env python3
"""KeyClean: Mouse-controlled keyboard locker with mechanical clock ring UI."""

from __future__ import annotations

import atexit
import math
import signal
import sys

import evdev
from evdev import ecodes
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

TIMER_PRESETS: list[tuple[str, int]] = [
    ("30s", 30),
    ("1m", 60),
    ("2m", 120),
    ("5m", 300),
    ("∞", 0),
]

CSS = """
window.keyclean-win {
    background-color: #121314;
    color: #f4f5f6;
}
headerbar {
    background-color: transparent;
    border-bottom: none;
    box-shadow: none;
}
headerbar windowcontrols button,
headerbar windowcontrols button:hover,
headerbar windowcontrols button:active,
headerbar windowcontrols button:backdrop {
    transition: background-color 150ms ease, color 150ms ease;
    background-image: none;
    background-color: transparent;
    border: none;
    box-shadow: none;
    border-radius: 9999px;
    min-width: 26px;
    min-height: 26px;
    padding: 0;
    margin: 0 3px;
}
headerbar windowcontrols button image {
    color: #b4b8be;
}
headerbar windowcontrols button:hover {
    background-color: rgba(255, 255, 255, 0.1);
}
headerbar windowcontrols button.close:hover {
    background-color: rgba(243, 139, 168, 0.22);
    color: #f38ba8;
}
headerbar windowcontrols button:active {
    background-color: rgba(255, 255, 255, 0.18);
}

.status-pill {
    background-color: #1c1e20;
    border-radius: 9999px;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 600;
    color: #9aa0a6;
}
.status-pill-locked {
    background-color: rgba(30, 232, 130, 0.14);
    color: #1ee882;
}

.ring-sub {
    font-size: 12px;
    font-weight: 500;
    color: #8b9198;
    font-variant-numeric: tabular-nums;
}
.clock-colon {
    font-size: 32px;
    font-weight: 700;
    color: #f4f5f6;
    opacity: 0.85;
    padding: 0 1px;
}
.clock-infinity {
    font-size: 40px;
    font-weight: 700;
    color: #f4f5f6;
}

.preset-btn {
    background-color: #1c1e20;
    background-image: none;
    color: #9aa0a6;
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 14px;
    min-width: 48px;
    min-height: 40px;
    padding: 0 12px;
    font-weight: 600;
    font-size: 13px;
    box-shadow: none;
    transition: background-color 150ms ease, color 150ms ease, border-color 150ms ease;
}
.preset-btn:hover {
    background-color: #25282b;
    color: #f4f5f6;
}
.preset-btn:checked {
    background-color: rgba(30, 232, 130, 0.16);
    border-color: rgba(30, 232, 130, 0.45);
    color: #1ee882;
}

.primary-squircle {
    background-color: #12b866;
    background-image: none;
    color: #08150e;
    border: none;
    border-radius: 20px;
    min-width: 140px;
    min-height: 56px;
    padding: 0 24px;
    font-weight: 700;
    font-size: 15px;
    box-shadow: none;
    transition: background-color 150ms ease, transform 100ms ease;
}
.primary-squircle:hover {
    background-color: #1ee882;
}
.primary-squircle-unlock {
    background-color: #e54858;
    color: #ffffff;
}
.primary-squircle-unlock:hover {
    background-color: #f25c6b;
}

.secondary-squircle {
    background-color: #1c1e20;
    background-image: none;
    color: #d0d4d9;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 18px;
    min-width: 56px;
    min-height: 56px;
    padding: 0 14px;
    font-weight: 600;
    font-size: 13px;
    box-shadow: none;
    transition: background-color 150ms ease;
}
.secondary-squircle:hover {
    background-color: #272a2e;
}

.devices-footer {
    font-size: 11px;
    color: #6b7178;
}
"""


def find_keyboards() -> list[evdev.InputDevice]:
    """Return physical keyboard input devices (excluding mice and virtual keyboards)."""
    keyboards: list[evdev.InputDevice] = []
    for path in sorted(evdev.list_devices()):
        try:
            dev = evdev.InputDevice(path)
            name_lower = (dev.name or "").lower()
            if "virtual" in name_lower:
                dev.close()
                continue
            caps = dev.capabilities()
            keys = set(caps.get(ecodes.EV_KEY, []))
            is_kbd = {ecodes.KEY_A, ecodes.KEY_SPACE, ecodes.KEY_ENTER}.issubset(keys)
            is_pointer = ecodes.BTN_LEFT in keys or ecodes.BTN_TOUCH in keys
            if is_kbd and not is_pointer:
                keyboards.append(dev)
            else:
                dev.close()
        except OSError:
            continue
    return keyboards


class DigitWheel(Gtk.DrawingArea):
    """Single mechanical drum digit with 3D cylinder roll animation."""

    DURATION_US = 280_000

    def __init__(self, initial: str = "0") -> None:
        super().__init__()
        self.set_content_width(28)
        self.set_content_height(48)
        self._curr = initial
        self._prev = initial
        self._progress = 1.0
        self._start_us = 0
        self._tick_id: int | None = None
        self._font = Pango.FontDescription.from_string("Monospace Bold 30")
        self.set_draw_func(self._on_draw)

    def set_char(self, ch: str, animate: bool = True) -> None:
        if ch == self._curr:
            return
        self._prev = self._curr
        self._curr = ch
        if not animate:
            self._progress = 1.0
            self.queue_draw()
            return
        self._start_us = GLib.get_monotonic_time()
        self._progress = 0.0
        if self._tick_id is None:
            self._tick_id = self.add_tick_callback(self._on_tick)
        self.queue_draw()

    def _on_tick(self, _widget: Gtk.Widget, _clock: Gdk.FrameClock) -> bool:
        elapsed = GLib.get_monotonic_time() - self._start_us
        t = min(1.0, elapsed / self.DURATION_US)
        self._progress = 1.0 - (1.0 - t) ** 3
        self.queue_draw()
        if t >= 1.0:
            self._tick_id = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _draw_digit(self, cr, w: int, h: int, text: str, angle: float) -> None:
        if abs(angle) >= math.pi / 2:
            return
        scale_y = max(0.05, math.cos(angle))
        alpha = scale_y**1.25
        y_offset = math.sin(angle) * (h * 0.56)

        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(self._font)
        layout.set_text(text, -1)
        lw, lh = layout.get_pixel_size()

        cr.save()
        cr.translate(w / 2.0, h / 2.0 + y_offset)
        cr.scale(1.0, scale_y)
        cr.set_source_rgba(0.96, 0.96, 0.97, alpha)
        cr.move_to(-lw / 2.0, -lh / 2.0)
        PangoCairo.show_layout(cr, layout)
        cr.restore()

    def _on_draw(self, _area: Gtk.DrawingArea, cr, w: int, h: int) -> None:
        p = self._progress
        if p >= 1.0:
            self._draw_digit(cr, w, h, self._curr, 0.0)
        else:
            self._draw_digit(cr, w, h, self._prev, p * (math.pi / 2))
            self._draw_digit(cr, w, h, self._curr, (p - 1.0) * (math.pi / 2))


class MechanicalClock(Gtk.Box):
    """MM:SS mechanical drum clock + infinity fallback."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.set_halign(Gtk.Align.CENTER)
        self._wheels = [DigitWheel("0"), DigitWheel("1"), DigitWheel("0"), DigitWheel("0")]
        self._colon = Gtk.Label(label=":")
        self._colon.add_css_class("clock-colon")
        self._infinity = Gtk.Label(label="∞")
        self._infinity.add_css_class("clock-infinity")
        self._infinity.set_visible(False)

        self.append(self._wheels[0])
        self.append(self._wheels[1])
        self.append(self._colon)
        self.append(self._wheels[2])
        self.append(self._wheels[3])
        self.append(self._infinity)

    def set_time(self, seconds: int, unlimited: bool = False, animate: bool = True) -> None:
        for w in self._wheels:
            w.set_visible(not unlimited)
        self._colon.set_visible(not unlimited)
        self._infinity.set_visible(unlimited)
        if unlimited:
            return
        mins, secs = divmod(max(0, seconds), 60)
        for wheel, ch in zip(self._wheels, f"{mins:02d}{secs:02d}"):
            wheel.set_char(ch, animate=animate)


class CircularRing(Gtk.DrawingArea):
    """Smooth circular progress ring inspired by minimalist workout timers."""

    def __init__(self, size: int = 232) -> None:
        super().__init__()
        self.set_content_width(size)
        self.set_content_height(size)
        self._fraction = 1.0
        self._active = False
        self.set_draw_func(self._on_draw)

    def set_state(self, fraction: float, active: bool) -> None:
        self._fraction = max(0.0, min(1.0, fraction))
        self._active = active
        self.queue_draw()

    def _on_draw(self, _area: Gtk.DrawingArea, cr, w: int, h: int) -> None:
        cx, cy = w / 2.0, h / 2.0
        stroke = 14.0
        radius = min(w, h) / 2.0 - stroke

        cr.set_line_width(stroke)
        cr.set_line_cap(1)  # CAIRO_LINE_CAP_ROUND

        # Track circle
        if self._active:
            cr.set_source_rgba(0.08, 0.22, 0.15, 1.0)
        else:
            cr.set_source_rgba(0.14, 0.15, 0.16, 1.0)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.stroke()

        # Progress arc
        if self._fraction > 0.001:
            start = -math.pi / 2.0
            end = start + (2.0 * math.pi * self._fraction)
            if self._active:
                cr.set_source_rgba(0.12, 0.91, 0.51, 1.0)  # #1ee882
            else:
                cr.set_source_rgba(0.12, 0.91, 0.51, 0.35)
            cr.arc(cx, cy, radius, start, end)
            cr.stroke()


class KeyCleanWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="KeyClean")
        self.add_css_class("keyclean-win")
        self.set_size_request(380, 480)
        self.set_default_size(380, 480)
        self.set_resizable(False)

        self._grabbed: list[tuple[evdev.InputDevice, int]] = []
        self._locked = False
        self._selected_seconds = 60
        self._total_seconds = 60
        self._remaining_seconds = 60
        self._timer_id: int | None = None
        self._blocked_presses = 0

        self._build_ui()
        self._refresh_devices_label()
        self._sync_preview()
        self.connect("close-request", self._on_close_request)

    def _build_ui(self) -> None:
        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label="KeyClean"))

        self._status_pill = Gtk.Label(label="Připraveno")
        self._status_pill.add_css_class("status-pill")
        header.pack_start(self._status_pill)
        toolbar_view.add_top_bar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        root.set_margin_top(12)
        root.set_margin_bottom(20)
        root.set_margin_start(24)
        root.set_margin_end(24)

        # Center circular ring + mechanical clock inside
        overlay = Gtk.Overlay()
        overlay.set_halign(Gtk.Align.CENTER)
        self._ring = CircularRing(232)
        overlay.set_child(self._ring)

        ring_center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        ring_center.set_valign(Gtk.Align.CENTER)
        ring_center.set_halign(Gtk.Align.CENTER)

        self._clock = MechanicalClock()
        ring_center.append(self._clock)

        self._ring_sub = Gtk.Label(label="Klikni pro zamčení")
        self._ring_sub.add_css_class("ring-sub")
        ring_center.append(self._ring_sub)

        overlay.add_overlay(ring_center)
        root.append(overlay)

        # Timer presets row (unlocked)
        self._presets_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._presets_box.set_halign(Gtk.Align.CENTER)
        first_btn: Gtk.ToggleButton | None = None
        for label, secs in TIMER_PRESETS:
            btn = Gtk.ToggleButton(label=label)
            btn.add_css_class("preset-btn")
            if first_btn is not None:
                btn.set_group(first_btn)
            else:
                first_btn = btn
            if secs == self._selected_seconds:
                btn.set_active(True)
            btn.connect("toggled", self._on_preset_toggled, secs)
            self._presets_box.append(btn)
        root.append(self._presets_box)

        # Controls row (squircle buttons like the reference)
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        controls.set_halign(Gtk.Align.CENTER)

        self._action_btn = Gtk.Button()
        self._action_btn.add_css_class("primary-squircle")
        self._set_action_content("changes-prevent-symbolic", "Zamknout")
        self._action_btn.connect("clicked", self._on_action_clicked)
        controls.append(self._action_btn)

        self._extend_btn = Gtk.Button(label="+30s")
        self._extend_btn.add_css_class("secondary-squircle")
        self._extend_btn.set_visible(False)
        self._extend_btn.connect("clicked", self._on_extend_clicked)
        controls.append(self._extend_btn)

        root.append(controls)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        root.append(spacer)

        self._devices_label = Gtk.Label()
        self._devices_label.add_css_class("devices-footer")
        self._devices_label.set_ellipsize(3)
        self._devices_label.set_max_width_chars(38)
        root.append(self._devices_label)

        toolbar_view.set_content(root)
        self.set_content(toolbar_view)

    def _set_action_content(self, icon_name: str, text: str) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_halign(Gtk.Align.CENTER)
        box.append(Gtk.Image.new_from_icon_name(icon_name))
        box.append(Gtk.Label(label=text))
        self._action_btn.set_child(box)

    def _refresh_devices_label(self) -> None:
        devs = find_keyboards()
        names = [d.name for d in devs]
        for d in devs:
            d.close()
        if names:
            self._devices_label.set_label(" • ".join(names))
        else:
            self._devices_label.set_label("Nenalezena fyzická klávesnice")

    def _sync_preview(self) -> None:
        unlimited = self._selected_seconds <= 0
        self._clock.set_time(self._selected_seconds, unlimited=unlimited, animate=True)
        self._ring.set_state(1.0, active=False)

    def _on_preset_toggled(self, btn: Gtk.ToggleButton, secs: int) -> None:
        if btn.get_active() and not self._locked:
            self._selected_seconds = secs
            self._sync_preview()

    def _on_extend_clicked(self, _btn: Gtk.Button) -> None:
        if not self._locked or self._selected_seconds <= 0:
            return
        self._remaining_seconds += 30
        self._total_seconds = max(self._total_seconds, self._remaining_seconds)
        self._update_timer_ui(animate=True)

    def _on_action_clicked(self, _btn: Gtk.Button) -> None:
        if self._locked:
            self.unlock()
        else:
            self.lock()

    def lock(self) -> None:
        if self._locked:
            return
        devices = find_keyboards()
        if not devices:
            self._ring_sub.set_label("Klávesnice nenalezena")
            return

        grabbed: list[tuple[evdev.InputDevice, int]] = []
        try:
            for dev in devices:
                dev.grab()
                watch_id = GLib.io_add_watch(dev.fd, GLib.IO_IN, self._on_kbd_event, dev)
                grabbed.append((dev, watch_id))
        except OSError as exc:
            for dev, watch_id in grabbed:
                GLib.source_remove(watch_id)
                try:
                    dev.ungrab()
                except OSError:
                    pass
                dev.close()
            for dev in devices:
                if all(dev is not g[0] for g in grabbed):
                    dev.close()
            self._ring_sub.set_label(f"Chyba: {exc}")
            return

        self._grabbed = grabbed
        self._locked = True
        self._blocked_presses = 0
        self._total_seconds = self._selected_seconds
        self._remaining_seconds = self._selected_seconds

        self._status_pill.set_label("Zamčeno")
        self._status_pill.add_css_class("status-pill-locked")
        self._ring_sub.set_label("Zachyceno: 0")

        self._presets_box.set_opacity(0.0)
        self._presets_box.set_sensitive(False)
        self._presets_box.set_can_target(False)
        self._extend_btn.set_visible(self._selected_seconds > 0)
        self._set_action_content("changes-allow-symbolic", "Odemknout")
        self._action_btn.add_css_class("primary-squircle-unlock")

        self._update_timer_ui(animate=False)
        if self._selected_seconds > 0:
            self._timer_id = GLib.timeout_add_seconds(1, self._on_tick)

    def unlock(self) -> None:
        if self._timer_id is not None:
            GLib.source_remove(self._timer_id)
            self._timer_id = None

        for dev, watch_id in self._grabbed:
            GLib.source_remove(watch_id)
            try:
                dev.ungrab()
            except OSError:
                pass
            try:
                dev.close()
            except OSError:
                pass
        self._grabbed.clear()
        self._locked = False

        self._status_pill.set_label("Připraveno")
        self._status_pill.remove_css_class("status-pill-locked")
        self._ring_sub.set_label("Klikni pro zamčení")

        self._presets_box.set_opacity(1.0)
        self._presets_box.set_sensitive(True)
        self._presets_box.set_can_target(True)
        self._extend_btn.set_visible(False)
        self._set_action_content("changes-prevent-symbolic", "Zamknout")
        self._action_btn.remove_css_class("primary-squircle-unlock")

        self._sync_preview()
        self._refresh_devices_label()

    def _on_kbd_event(self, _fd: int, _condition: GLib.IOCondition, dev: evdev.InputDevice) -> bool:
        try:
            for event in dev.read():
                if event.type == ecodes.EV_KEY and event.value == 1:
                    self._blocked_presses += 1
                    self._ring_sub.set_label(f"Zachyceno: {self._blocked_presses}")
        except BlockingIOError:
            pass
        except OSError:
            return False
        return True

    def _on_tick(self) -> bool:
        if not self._locked:
            self._timer_id = None
            return False
        self._remaining_seconds -= 1
        if self._remaining_seconds <= 0:
            self._timer_id = None
            self.unlock()
            return False
        self._update_timer_ui(animate=True)
        return True

    def _update_timer_ui(self, animate: bool = True) -> None:
        if self._selected_seconds <= 0:
            self._clock.set_time(0, unlimited=True, animate=False)
            self._ring.set_state(1.0, active=True)
            return
        self._clock.set_time(self._remaining_seconds, unlimited=False, animate=animate)
        frac = self._remaining_seconds / max(1, self._total_seconds)
        self._ring.set_state(frac, active=True)

    def _on_close_request(self, _win: Gtk.Window) -> bool:
        self.unlock()
        return False


class KeyCleanApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id="eu.rutterle.KeyClean")
        self._win: KeyCleanWindow | None = None

    def do_activate(self) -> None:
        css_provider = Gtk.CssProvider()
        css_provider.load_from_string(CSS)
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1
            )

        if self._win is None:
            self._win = KeyCleanWindow(self)
            atexit.register(self._win.unlock)
        self._win.present()


def main() -> int:
    app = KeyCleanApp()
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
