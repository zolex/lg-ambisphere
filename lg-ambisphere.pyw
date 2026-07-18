#!/usr/bin/env python3

from dis import findlinestarts
import lib38gn950

import hid
# https://pypi.org/project/hid/
# https://github.com/apmorton/pyhidapi

import json
import os
import subprocess
import sys
import time

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from threading import Thread
from lightsync import LightsyncPrismatic

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRISMATIK_ICON = os.path.join(BASE_DIR, 'Prismatik.ico')
DEFAULT_STATIC_COLORS = {1: '27e5ff', 2: '27e5ff', 3: '27e5ff', 4: '27e5ff'}


def load_icon_pixmap(path, size=32, grayscale=False):
    pixmap = QPixmap(path)
    if pixmap.isNull():
        return pixmap
    pixmap = pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    if grayscale:
        image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
        for y in range(image.height()):
            for x in range(image.width()):
                color = image.pixelColor(x, y)
                gray = qGray(color.rgb())
                color.setRgb(gray, gray, gray, color.alpha())
                image.setPixelColor(x, y, color)
        pixmap = QPixmap.fromImage(image)
    return pixmap

CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')
DEFAULT_CONFIG = {
    # Path to the Prismatik executable.
    'prismatik_exe': r'C:\Program Files\Prismatik\Prismatik.exe',
    # Folder passed to Prismatik via --config-dir. Relative paths are
    # resolved against this script's directory.
    'prismatik_config_dir': './prismatik-config',
    # Profile name passed to Prismatik via --set-profile (no path, no extension).
    'prismatik_profile': 'LG-38GN950',
    # Launch Prismatik with --nogui. NOTE: currently broken - with --nogui,
    # Prismatik's LED grabber doesn't pick up the switched profile's LED
    # count correctly, causing send_video_sync_data to fail. Leave False
    # until that's resolved upstream.
    'prismatik_no_gui': False,
    # Last color set for each static color slot (1-4), as hex without '#'.
    'static_colors': {str(slot): hexcolor for slot, hexcolor in DEFAULT_STATIC_COLORS.items()},
    # Whether Prismatik lightsync was enabled last time the app ran. If True,
    # the GUI auto-starts Prismatik/lightsync on launch.
    'sync_enabled': False,
}


def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = {}
    config = {**DEFAULT_CONFIG, **saved}
    config['static_colors'] = {**DEFAULT_CONFIG['static_colors'], **saved.get('static_colors', {})}
    return config

class ToggleSwitch(QAbstractButton):
    def __init__(self, parent=None, width=56, height=28,
                 bg_color='#c0c0c0', active_color='#4cd137', handle_color='#ffffff'):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(width, height)

        self._track_radius = height // 2
        self._thumb_radius = self._track_radius - 3
        self._bg_color = QColor(bg_color)
        self._active_color = QColor(active_color)
        self._handle_color = QColor(handle_color)

        self._position = self._thumb_radius + 3
        self._animation = QPropertyAnimation(self, b'position', self)
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.InOutCubic)

        self.toggled.connect(self._animate)

    def _animate(self, checked):
        self._animation.stop()
        self._animation.setStartValue(self._position)
        end = self.width() - self._thumb_radius - 3 if checked else self._thumb_radius + 3
        self._animation.setEndValue(end)
        self._animation.start()

    def get_position(self):
        return self._position

    def set_position(self, pos):
        self._position = pos
        self.update()

    position = pyqtProperty(float, get_position, set_position)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)

        p.setBrush(self._active_color if self.isChecked() else self._bg_color)
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), self._track_radius, self._track_radius)

        p.setBrush(self._handle_color)
        p.drawEllipse(QPointF(self._position, self.height() / 2), self._thumb_radius, self._thumb_radius)

    def sizeHint(self):
        return QSize(self.width(), self.height())


class Gui(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()


    def init_ui(self):
        self.setWindowTitle('LG AmbiSphere')
        self.currentLightingMode = ('peaceful', None)
        self.config = load_config()
        self.prismatikProcess = None
        self.launchedPrismatik = False
        self.prismatikOutputLines = []
        self.prismatikCrashReported = False
        self.thread = None
        self.syncPausedByPowerOff = False

        mainLayout = QVBoxLayout(self)

        self.selectionbuttonslayout = QHBoxLayout(self)
        self.selectionbuttonslayout.addWidget(QLabel('<b>Select monitors: </b>'))
        mainLayout.addLayout(self.selectionbuttonslayout)

        mainLayout.addWidget(QLabel(''))

        powerbuttonslayout = QGridLayout(self)
        powerbuttonslayout.addWidget(QLabel('<b>Power</b>'), 0, 0, 1, 2)
        self.powerSwitch = ToggleSwitch()
        self.powerSwitch.setChecked(True)
        self.powerSwitch.toggled.connect(self.set_power)
        self.powerStatusLabel = QLabel('On')
        powerbuttonslayout.addWidget(self.powerSwitch, 1, 0)
        powerbuttonslayout.addWidget(self.powerStatusLabel, 1, 1)
        mainLayout.addLayout(powerbuttonslayout)

        mainLayout.addWidget(QLabel(''))

        brightnessbuttonslayout = QGridLayout(self)
        brightnessbuttonslayout.addWidget(QLabel('<b>Brightness</b>'), 0, 0, 1, 6)
        self.brightnessSlider = QSlider(Qt.Horizontal)
        self.brightnessSlider.setMinimum(1)
        self.brightnessSlider.setMaximum(12)
        self.brightnessSlider.setValue(12)
        self.brightnessSlider.setTickPosition(QSlider.TicksBelow)
        self.brightnessSlider.setTickInterval(1)
        self.brightnessSlider.setSingleStep(1)
        self.brightnessSlider.setPageStep(1)
        self.brightnessSlider.valueChanged.connect(self.set_brightness)
        self.brightnessValueLabel = QLabel('12')
        self.brightnessSlider.valueChanged.connect(lambda v: self.brightnessValueLabel.setText(str(v)))
        brightnessbuttonslayout.addWidget(self.brightnessSlider, 1, 0, 1, 5)
        brightnessbuttonslayout.addWidget(self.brightnessValueLabel, 1, 5)
        mainLayout.addLayout(brightnessbuttonslayout)

        mainLayout.addWidget(QLabel(''))

        configbuttonslayout = QGridLayout(self)
        configbuttonslayout.addWidget(QLabel('<b>Lighting mode</b>'), 0, 0, 1, 4)
        self.staticColorHex = self.load_static_colors()
        self.staticColorButtons = {}
        for i in range(4):
            x = QPushButton('')
            x.setFixedSize(48, 32)
            x.setCursor(Qt.PointingHandCursor)
            x.setToolTip(f'Color {i+1}\nClick: select   Right-click: change color')
            x.clicked.connect(lambda _, i =i: self.set_static_color(i+1))
            x.setContextMenuPolicy(Qt.CustomContextMenu)
            x.customContextMenuRequested.connect(lambda _, i=i: self.pick_slot_color(i+1))
            self.staticColorButtons[i+1] = x
            self.update_static_color_button(i+1)
            configbuttonslayout.addWidget(x, 1, i)
        x = QPushButton('Peaceful')
        x.clicked.connect(self.set_peaceful_color)
        configbuttonslayout.addWidget(x, 2, 0, 1, 2)
        x = QPushButton('Dynamic')
        x.clicked.connect(self.set_dynamic_color)
        configbuttonslayout.addWidget(x, 2, 2, 1, 2)
        mainLayout.addLayout(configbuttonslayout)

        mainLayout.addWidget(QLabel(''))

        ambilightlayout = QGridLayout(self)
        ambilightlayout.addWidget(QLabel('<b>LG Ambilight</b>'), 0, 0, 1, 4)
        ambilightlayout.addWidget(QLabel('Profile: '), 1, 0)
        self.prismatikProfileCombo = QComboBox()
        self.prismatikProfileCombo.addItems(self.list_prismatik_profiles())
        current_profile = self.config.get('prismatik_profile')
        if current_profile:
            index = self.prismatikProfileCombo.findText(current_profile)
            if index == -1:
                self.prismatikProfileCombo.addItem(current_profile)
                index = self.prismatikProfileCombo.findText(current_profile)
            self.prismatikProfileCombo.setCurrentIndex(index)
        self.prismatikProfileCombo.currentTextChanged.connect(self.set_prismatik_profile)
        ambilightlayout.addWidget(self.prismatikProfileCombo, 1, 1, 1, 3)
        self.syncIconOff = QIcon(load_icon_pixmap(PRISMATIK_ICON, 32, grayscale=True))
        self.syncIconOn = QIcon(load_icon_pixmap(PRISMATIK_ICON, 32, grayscale=False))
        self.syncButton = QPushButton(self)
        self.syncButton.setText(' Enable (Prismatic)')
        self.syncButton.setIcon(self.syncIconOff)
        self.syncButton.setIconSize(QSize(32, 32))
        self.syncButton.clicked.connect(self.run_lightsync_prismatic)
        ambilightlayout.addWidget(self.syncButton, 2, 0, 1, 4)
        mainLayout.addLayout(ambilightlayout)


    def init_monitors(self):
        monitors = lib38gn950.find_monitors()
        if not monitors:
            for item in self.layout().children():
                self.layout().removeItem(item)
            self.layout().addWidget(QLabel('No monitors found'))
            return

        self.thread = None
        self.devs = []
        for monitor in monitors:
            self.devs.append(hid.Device(path=monitor['path']))

        self.selection = list(range(len(self.devs)))

        for i in self.selection:
            x = QCheckBox(str(i+1))
            x.setCheckState(2)
            x.stateChanged.connect(lambda checked, i=i: self.update_selection(i, checked))
            self.selectionbuttonslayout.addWidget(x)

        self.turn_on()

        if self.config.get('sync_enabled'):
            self.run_lightsync_prismatic()


    def cleanup(self):
        if hasattr(self, 'devs'):
            try:
                self.stop_lightsync()
            except Exception as e:
                print(e)
            self.stop_prismatik()
            try:
                self.turn_off()
            except Exception as e:
                print(e)
            for dev in self.devs:
                dev.close()


    def pick_slot_color(self, slot):
        initial = QColor('#' + self.staticColorHex[slot])
        color = QColorDialog.getColor(initial, self, f'Pick color for slot {slot}')
        if not color.isValid():
            return
        hexcolor = color.name()[1:].lower()
        cmd = lib38gn950.get_set_color_command(slot, hexcolor)
        self.send_command(cmd)
        self.staticColorHex[slot] = hexcolor
        self.update_static_color_button(slot)
        self.save_static_colors()

    def load_static_colors(self):
        saved = self.config['static_colors']
        return {slot: saved.get(str(slot), hexcolor) for slot, hexcolor in DEFAULT_STATIC_COLORS.items()}

    def save_static_colors(self):
        self.config['static_colors'] = {str(slot): hexcolor for slot, hexcolor in self.staticColorHex.items()}
        self.save_config()

    def save_config(self):
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=4)
        except OSError as e:
            print(e)


    def update_selection(self, monitor_num, checked):
        if checked == 0:
            self.selection.remove(monitor_num)
        elif checked == 2:
            self.selection.append(monitor_num)


    def send_command(self, cmd, pause_only=False):
        was_syncing = self.is_sync_active()
        self.stop_lightsync()
        if was_syncing:
            self.stop_prismatik()
            if pause_only:
                self.syncPausedByPowerOff = True
            else:
                self.config['sync_enabled'] = False
                self.save_config()
        devs = []
        for i in self.selection:
            devs.append(self.devs[i])
        lib38gn950.send_command(cmd, devs)


    def turn_on(self):
        cmd = lib38gn950.control_commands['turn_on']
        self.send_command(cmd)
        if self.syncPausedByPowerOff:
            self.syncPausedByPowerOff = False
            self.run_lightsync_prismatic()
    def turn_off(self):
        cmd = lib38gn950.control_commands['turn_off']
        self.send_command(cmd, pause_only=True)

    def set_power(self, checked):
        if checked:
            self.turn_on()
            self.powerStatusLabel.setText('On')
        else:
            self.turn_off()
            self.powerStatusLabel.setText('Off')

    def set_static_color(self, color):
        cmd = lib38gn950.control_commands['color' + str(color)]
        self.send_command(cmd)
        self.currentLightingMode = ('static', color)
    def set_peaceful_color(self):
        cmd = lib38gn950.control_commands['color_peaceful']
        self.send_command(cmd)
        self.currentLightingMode = ('peaceful', None)
    def set_dynamic_color(self):
        cmd = lib38gn950.control_commands['color_dynamic']
        self.send_command(cmd)
        self.currentLightingMode = ('dynamic', None)

    def restore_lighting_mode(self, mode):
        kind, value = mode
        if kind == 'static':
            self.set_static_color(value)
        elif kind == 'dynamic':
            self.set_dynamic_color()
        else:
            self.set_peaceful_color()

    def set_brightness(self, brt):
        cmd = lib38gn950.brightness_commands[brt]
        self.send_command(cmd)

    def update_static_color_button(self, slot):
        hexcolor = self.staticColorHex[slot]
        self.staticColorButtons[slot].setStyleSheet(
            f'background-color: #{hexcolor}; border: 1px solid #888; border-radius: 4px;')
  
    def thread_finished(self):
        self.syncButton.setIcon(self.syncIconOff)
        self.syncButton.setText(' Enable (Prismatic)')
        print("Sync stopped")
        if self.launchedPrismatik and not self.is_prismatik_process_alive() and not self.prismatikCrashReported:
            self.prismatikCrashReported = True
            print("Prismatik process is no longer running - it must have exited or crashed.")
            output = self.read_prismatik_output()
            if output.strip():
                print("Prismatik output before it went away:")
                print(output)
        self.syncButton.clicked.disconnect()
        self.syncButton.clicked.connect(self.run_lightsync_prismatic)

    def is_sync_active(self):
        return isinstance(self.thread, LightsyncPrismatic) and self.thread.isRunning()

    def stop_lightsync(self):
        if isinstance(self.thread, LightsyncPrismatic):
            self.thread.stop()
            self.thread.wait()

    def disable_lightsync(self):
        self.stop_lightsync()
        self.stop_prismatik()
        self.syncPausedByPowerOff = False
        self.restore_lighting_mode(self.preSyncLightingMode)
        self.config['sync_enabled'] = False
        self.save_config()

    def is_prismatik_running(self):
        exe_name = os.path.basename(self.config['prismatik_exe'])
        try:
            out = subprocess.check_output(
                ['tasklist', '/FI', f'IMAGENAME eq {exe_name}'],
                creationflags=subprocess.CREATE_NO_WINDOW)
            return exe_name.encode() in out
        except Exception:
            return False

    def resolve_prismatik_config_dir(self):
        config_dir = self.config.get('prismatik_config_dir')
        if not config_dir:
            return None
        if not os.path.isabs(config_dir):
            config_dir = os.path.join(BASE_DIR, config_dir)
        return os.path.abspath(config_dir)

    def list_prismatik_profiles(self):
        config_dir = self.resolve_prismatik_config_dir()+"/Profiles"
        if not config_dir or not os.path.isdir(config_dir):
            return []
        return sorted(
            os.path.splitext(f)[0]
            for f in os.listdir(config_dir)
            if f.lower().endswith('.ini')
        )

    def set_prismatik_profile(self, profile):
        self.config['prismatik_profile'] = profile
        self.save_config()

    def is_prismatik_process_alive(self):
        return self.prismatikProcess is not None and self.prismatikProcess.poll() is None

    def drain_prismatik_output(self, proc):
        try:
            for line in iter(proc.stdout.readline, b''):
                text = line.decode(errors='replace').rstrip()
                if text:
                    self.prismatikOutputLines.append(text)
                    del self.prismatikOutputLines[:-200]
        except Exception:
            pass

    def read_prismatik_output(self):
        return '\n'.join(self.prismatikOutputLines)

    def start_prismatik(self):
        self.launchedPrismatik = False
        if self.is_prismatik_running():
            self.set_prismatik_active_profile()
            return
        exe = self.config['prismatik_exe']
        if not os.path.exists(exe):
            print(f"Prismatik executable not found at {exe}")
            return
        args = [exe]
        config_dir = self.resolve_prismatik_config_dir()
        if config_dir:
            args += ['--config-dir', config_dir]
        if self.config.get('prismatik_no_gui', True):
            args.append('--nogui')
        print('Starting Prismatik:', subprocess.list2cmdline(args))
        self.prismatikOutputLines = []
        self.prismatikCrashReported = False
        try:
            self.prismatikProcess = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            Thread(target=self.drain_prismatik_output, args=(self.prismatikProcess,), daemon=True).start()
            self.launchedPrismatik = True
            # Wait for it to either show up as running or exit on its own.
            for _ in range(20):
                if not self.is_prismatik_process_alive():
                    break
                if self.is_prismatik_running():
                    break
                time.sleep(0.25)
            time.sleep(1)  # give Prismatik's API server a moment to come up
        except Exception as e:
            print(e)
            return
        if not self.is_prismatik_process_alive():
            print(f"Prismatik exited on its own right after starting "
                  f"(exit code {self.prismatikProcess.returncode}).")
            output = self.read_prismatik_output()
            if output.strip():
                print(output)
            self.launchedPrismatik = False
            self.prismatikProcess = None
            return
        self.set_prismatik_active_profile()

    def set_prismatik_active_profile(self):
        profile = self.config.get('prismatik_profile')
        if not profile:
            return
        exe = self.config['prismatik_exe']
        args = [exe, '--set-profile', profile]
        print('Setting Prismatik profile:', subprocess.list2cmdline(args))
        try:
            subprocess.run(args)
        except Exception as e:
            print(e)

    def stop_prismatik(self):
        if self.launchedPrismatik and self.prismatikProcess:
            try:
                self.prismatikProcess.terminate()
            except Exception as e:
                print(e)
        self.prismatikProcess = None
        self.launchedPrismatik = False

    def run_lightsync_prismatic(self):
        self.syncPausedByPowerOff = False
        self.preSyncLightingMode = self.currentLightingMode
        self.start_prismatik()
        connected = False
        for i in self.selection:
            try:
                self.thread = LightsyncPrismatic(config=dict(),dev=self.devs[i])
                self.thread.finished.connect(self.thread_finished)
                self.thread.start()
                if self.thread.connected:
                    connected = True
                self.syncButton.setIcon(self.syncIconOn)
                self.syncButton.setText(' Disable (Prismatic)')
                self.syncButton.clicked.disconnect()
                self.syncButton.clicked.connect(self.disable_lightsync)
            except Exception as e:
                print(e)
        # Only persist "enabled" if at least one device actually connected to
        # Prismatik's API - otherwise a failed attempt would get saved as
        # enabled and keep auto-retrying (and failing) on every launch.
        self.config['sync_enabled'] = connected
        self.save_config()

app = QApplication(sys.argv)
try:
    x = Gui()
    x.init_monitors()
    x.show()
    sys.exit(app.exec_())
finally:
    if 'x' in locals():
        x.cleanup()
