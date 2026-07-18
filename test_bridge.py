#!/usr/bin/env python3
"""Standalone test of the Prismatik -> LG monitor bridge, no Qt/GUI involved."""

import time
import lib38gn950 as lg
import lightpack

monitors = lg.find_monitors()
if not monitors:
    print("No monitors found")
    raise SystemExit(1)

print(f"Found {len(monitors)} monitor(s): {[m['model'] for m in monitors]}")

import hid
devs = [hid.Device(path=m['path']) for m in monitors]

lp = lightpack.lightpack('127.0.0.1', 3636, _apikey=None)
rc = lp.connect()
print(f"Prismatik connect() -> {rc}")
if rc != 0:
    raise SystemExit(1)

print(f"LED count reported by Prismatik: {lp.getCountLeds()}")

lg.send_command(lg.control_commands['color_video_sync'], devs)
print("Switched monitor to video-sync mode. Streaming for 15 seconds, try changing what's on screen...")

def rgb_to_hex_safe(r, g, b):
    r = r or 1
    g = g or 1
    b = b or 1
    return '%02x%02x%02x' % (r, g, b)

start = time.time()
frames = 0
while time.time() - start < 15:
    leds = lp.getColors()
    if leds is None:
        continue
    colors = [None] * 48
    for led in leds:
        idx, r, g, b = int(led[0]), int(led[1]), int(led[2]), int(led[3])
        colors[idx] = rgb_to_hex_safe(r, g, b)
    if any(c is None for c in colors):
        continue
    lg.send_video_sync_data(colors, devs)
    frames += 1
    time.sleep(0.01)

print(f"Sent {frames} frames in 15s (~{frames/15:.1f} fps)")

print("Reverting to peaceful mode")
lg.send_command(lg.control_commands['color_peaceful'], devs)
for d in devs:
    d.close()
lp.disconnect()
print("Done")
