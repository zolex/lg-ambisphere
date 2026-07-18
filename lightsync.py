
from unittest.util import _count_diff_all_purpose
import hid
from time import sleep
from lib38gn950 import *
import lightpack
import rich
from PyQt5 import QtCore

def rgb_to_hex_safe(rgb):
    r, g, b = rgb
    if r == 0 : r = 1
    if g == 0 : g = 1
    if b == 0 : b = 1
    return '%02x%02x%02x' % (r,g,b)

class LightsyncPrismatic(QtCore.QThread):
       
    def __init__(self, config = dict(), dev = None):
        super(LightsyncPrismatic, self).__init__()
        self._dev = dev
        self.runs = True
        if config == dict():
            config = dict()
            config['host'] = '127.0.0.1'
            config['port'] = 3636
            config['_apikey'] = None
        
        if self._dev == None:
            raise Exception('Screen was not choosen!')
        self.connected = False
        try:
            self.lpack = lightpack.lightpack(config['host'], config['port'], _apikey = config['_apikey'] )
            self.connected = self.lpack.connect() == 0
        except:
            print("Can't connect to Lightpack")
        if not self.connected:
            print("Can't connect to Prismatik's API - is it running with the API enabled (Settings > Dev tab)?")

    def run(self):
        try:
            if not self.connected:
                return
            send_command(control_commands['color_video_sync'], self._dev)
            i = 0
            fail = 0
            while self.runs:
                try:
                    leds = self.lpack.getColors()
                except OSError as e:
                    # Prismatik's API connection dropped - most likely the
                    # process itself exited or crashed. Stop cleanly instead
                    # of raising past the thread boundary.
                    print(f"Lost connection to Prismatik: {e}")
                    break
                if leds == None:
                    fail+=1
                    if fail > 5000:
                        break
                    sleep(0.01)
                    continue
                colors = []
                for led in leds:
                    rgb = (rgb_to_hex_safe((int(led[1]),int(led[2]),int(led[3]))))
                    colors.insert(0 + int(led[0]),rgb)
                sleep(0.01)
                try:
                    send_video_sync_data(colors, self._dev)
                except ValueError as e:
                    # Prismatik briefly reports the wrong LED count right after
                    # a profile switch (especially with --nogui); skip the
                    # frame instead of letting it kill the sync thread.
                    print(f"Skipping frame: {e}")
                    continue
                i+=1
        finally:
            self.finished.emit()
    
    def stop(self):
        self.runs = False