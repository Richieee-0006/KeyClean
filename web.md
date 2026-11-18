# KeyClean

GTK4 and Libadwaita app for Linux (Wayland) that locks physical keyboards via `evdev` (`EVIOCGRAB`) for safe cleaning while keeping mice and touchpads active.

## Key Features
- **Exclusive Keyboard Grab:** Captures `AT Translated Set 2`, USB, Bluetooth, and HID keyboards via `evdev`.
- **Mouse-Only Unlock:** Unlock or add 30 seconds using pointer input only.
- **Timer Presets:** Countdown presets (`30s`, `1m`, `2m`, `5m`, `∞`) with a circular progress ring.
- **Safe Auto-Release:** Releases grabbed devices on timer expiration, window close, or process exit.

## Tech Stack
- **Language:** Python 3.10+
- **UI:** GTK4, Libadwaita (`PyGObject`)
- **Input:** `python-evdev`
