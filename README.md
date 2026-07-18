# LG AmbiSphere Controller

A Python/PyQt5 GUI for controlling the ambient lighting ("Sphere Lighting") on supported LG UltraGear monitors over USB HID — power, brightness, static colors, and a screen-driven ambient video-sync mode powered by [Prismatik](https://github.com/psieg/Lightpack).

## Supported monitors

- LG 27GN950
- LG 38GN950
- LG 38GL950G

Monitors are detected automatically over USB HID (vendor/product ID matching, see `lib38gn950.py`).

## Requirements

- Windows (a prebuilt `hidapi.dll` is bundled and loaded via `ctypes`; other platforms would need their own hidapi build)
- Python 3
- Python packages: `PyQt5`, `hid` ([pyhidapi](https://pypi.org/project/hid/)), `rich`
- [Prismatik](https://github.com/psieg/Lightpack) installed, for the ambient video-sync feature

## Setup

```
pip install PyQt5 hid rich
```

Run the GUI:

```
python gui.pyw
```


## GUI overview (`gui.pyw`)

- **Select monitors** — checkboxes for each detected monitor; commands are sent to whichever are checked.
- **Power** — animated on/off toggle switch.
- **Brightness** — slider from 1 (min) to 12 (max).
- **Lighting mode** — four static color swatches (click to select that slot, right-click to open a color picker and reassign it), plus Peaceful and Dynamic mode buttons.
- **LG Ambilight** — a Profile dropdown (auto-populated from the configured Prismatik profiles folder) and an Enable/Disable (Prismatic) button that starts/stops screen-driven ambient sync.

On startup the app turns the selected monitors' lights on; on exit it stops any active sync, closes Prismatik if this app launched it, and turns the lights back off.

## Configuration (`config.json`)

Created next to `gui.pyw` automatically and kept up to date as you use the GUI (profile selection and static colors are written back immediately). You can also edit it directly.

| Key | Description |
|---|---|
| `prismatik_exe` | Path to `Prismatik.exe`. |
| `prismatik_config_dir` | Folder passed to Prismatik via `--config-dir`. Relative paths resolve against `gui.pyw`'s directory. |
| `prismatik_profile` | Prismatik profile name, passed via `--set-profile`. Updated automatically when you pick a profile from the GUI. |
| `prismatik_no_gui` | Whether to launch Prismatik with `--nogui`. **Must stay `false`** — see [Known issues](#known-issues). |
| `static_colors` | Last-set hex color (no `#`) for each of the four static color slots. Updated automatically from the GUI. |

Prismatik profiles are discovered from `<prismatik_config_dir>/Profiles/*.ini`.

This project ships with a pre-configured profile, `prismatik-config/Profiles/LG-38GN950.ini`, set up for the 48 video-sync capture zones the LG monitors expect — no manual Prismatik setup is required to get ambient sync working out of the box. Drop additional `.ini` files into `prismatik-config/Profiles/` to have them picked up automatically by the GUI's Profile dropdown.

## How ambient video sync works

1. Clicking **Enable (Prismatic)** launches Prismatik with `--config-dir <prismatik_config_dir>` (skipped if an instance is already running), waits for it to come up, then tells it to switch to `prismatik_profile` via a second `--set-profile` invocation (Prismatik only accepts `--set-profile` against an already-running instance).
2. The selected monitor(s) are switched into video-sync mode.
3. A background `QThread` (`lightsync.py`) polls Prismatik's local TCP API (`127.0.0.1:3636`) for the current 48 LED capture-zone colors and streams them to the monitor, capped at roughly 100 fps.
4. Clicking **Disable (Prismatic)** stops the sync thread, closes Prismatik (only if this app launched it — an instance you started yourself is left alone), and restores whichever lighting mode (a specific static color slot, Peaceful, or Dynamic) was active before sync started.


## Project layout

- `gui.pyw` — PyQt5 GUI (entry point)
- `lib38gn950.py` — HID protocol implementation (command building, CRC, device discovery)
- `lightpack.py` — minimal TCP client for Prismatik's local API
- `lightsync.py` — `QThread` bridging Prismatik's grabbed colors into the monitor's video-sync mode
- `test_bridge.py` — standalone script exercising the Prismatik bridge without the GUI, useful for isolating sync issues
- `config.json` — user settings (generated on first use)
- `prismatik-config/` — Prismatik's `--config-dir`; ships with a pre-configured `LG-38GN950` profile in `prismatik-config/Profiles/`
- `Prismatik.ico` — icon shown on the sync button (color when enabled, greyed out when disabled)
- `hidapi.dll` / `LICENSE-hidapi.txt` — bundled native HID library used on Windows

## Known issues

- **`prismatik_no_gui` / `--nogui`**: launching Prismatik headless currently causes it to die silently shortly after sync starts, with no error output — the API connection just drops. This reproduces consistently and appears to be a bug/incompatibility in Prismatik 5.11.2.31 on Windows rather than anything fixable in this project. Keep `prismatik_no_gui: false` (the default) until it's resolved upstream.
