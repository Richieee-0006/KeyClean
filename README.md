# KeyClean

GTK4 / Libadwaita app for Linux (Wayland / Hyprland) that locks physical keyboards via `evdev` (`EVIOCGRAB`) so you can clean your keyboard without triggering keys or shortcuts. Mice and touchpads stay active.

## Features

- Exclusive `evdev` grab on physical keyboards (`AT Translated Set 2`, USB/BT/HID keyboards)
- Mouse-only unlock and `+30s` extend button
- Timer presets (`30s`, `1m`, `2m`, `5m`, `∞`) with circular progress ring and mechanical rolling digits
- Automatic unlock on timer expiration, window close, or process exit

## Requirements

- Python 3.10+
- `python-gobject`, `gtk4`, `libadwaita`, `python-evdev`
- User must be in the `input` group (`sudo usermod -aG input $USER`)

## Run

```bash
chmod +x keyclean.py
./keyclean.py
```
