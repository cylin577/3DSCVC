import sys
import math
import struct
import socket
import threading
import time
import json
import cv2
import numpy as np
import pygame
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QFormLayout, QLineEdit, QPushButton, 
                             QCheckBox, QDialog, QComboBox, QLabel, QMessageBox,
                             QGroupBox, QTextEdit, QFileDialog)
from PyQt6.QtCore import (QTimer, QSettings, Qt, QPoint, QByteArray, 
                          QEvent, QObject, pyqtSignal)
from PyQt6.QtGui import QPainter, QPen, QColor, QMouseEvent, QCloseEvent
from PyQt6.QtNetwork import QUdpSocket, QHostAddress

# Constants
CPAD_BOUND = 0x5d0
CPP_BOUND = 0x7f
TOUCH_SCREEN_WIDTH = 320
TOUCH_SCREEN_HEIGHT = 240
TOP_TARGET = (400, 240) 
BOTTOM_TARGET = (320, 240)
TICK_RATE = 0.050 # 50ms = 20Hz

class GamepadButtons:
    ButtonA = 0
    ButtonB = 1
    ButtonX = 2
    ButtonY = 3
    ButtonL1 = 4
    ButtonR1 = 5
    ButtonL2 = 6
    ButtonR2 = 7
    ButtonSelect = 8
    ButtonStart = 9
    ButtonL3 = 10
    ButtonR3 = 11
    ButtonUp = 12
    ButtonDown = 13
    ButtonLeft = 14
    ButtonRight = 15
    ButtonCenter = 16
    ButtonGuide = 17
    ButtonInvalid = -1

class GlobalState:
    lx = 0.0
    ly = 0.0
    rx = 0.0
    ry = 0.0
    buttons = 0 
    interfaceButtons = 0
    ipAddress = ""
    yAxisMultiplier = 1
    abInverse = False
    xyInverse = False
    
    touchScreenPressed = False
    touchScreenPosition = QPoint(0, 0)
    settings = None
    
    # TAS state
    is_recording = False
    is_playing = False
    tas_frames = [] 
    current_play_idx = 0
    
    udp_socket = None
    heartbeat_running = False

state = GlobalState()

def variant_to_button(val):
    if val is None: return GamepadButtons.ButtonInvalid
    try:
        return int(val)
    except:
        return GamepadButtons.ButtonInvalid

def get_packet_data():
    if not state.settings: return None
    
    def get_btn(name, default):
        return variant_to_button(state.settings.value(name, default))

    hidButtonsAB = [get_btn("ButtonA", GamepadButtons.ButtonA), get_btn("ButtonB", GamepadButtons.ButtonB)]
    hidButtonsMiddle = [
        get_btn("ButtonSelect", GamepadButtons.ButtonSelect),
        get_btn("ButtonStart", GamepadButtons.ButtonStart),
        get_btn("ButtonRight", GamepadButtons.ButtonRight),
        get_btn("ButtonLeft", GamepadButtons.ButtonLeft),
        get_btn("ButtonUp", GamepadButtons.ButtonUp),
        get_btn("ButtonDown", GamepadButtons.ButtonDown),
        get_btn("ButtonR", GamepadButtons.ButtonR1),
        get_btn("ButtonL", GamepadButtons.ButtonL1)
    ]
    hidButtonsXY = [get_btn("ButtonX", GamepadButtons.ButtonX), get_btn("ButtonY", GamepadButtons.ButtonY)]
    irButtons = [get_btn("ButtonZR", GamepadButtons.ButtonR2), get_btn("ButtonZL", GamepadButtons.ButtonL2)]

    hidPad = 0xfff
    if not state.abInverse:
        for i in range(2):
            if state.buttons & (1 << hidButtonsAB[i]): hidPad &= ~(1 << i)
    else:
        for i in range(2):
            if state.buttons & (1 << hidButtonsAB[1-i]): hidPad &= ~(1 << i)

    for i in range(2, 10):
        if state.buttons & (1 << hidButtonsMiddle[i-2]): hidPad &= ~(1 << i)

    if not state.xyInverse:
        for i in range(10, 12):
            if state.buttons & (1 << hidButtonsXY[i-10]): hidPad &= ~(1 << i)
    else:
        for i in range(10, 12):
            if state.buttons & (1 << hidButtonsXY[1-(i-10)]): hidPad &= ~(1 << i)

    irButtonsState = 0
    for i in range(2):
        if state.buttons & (1 << irButtons[i]): irButtonsState |= 1 << (i + 1)

    touchScreenState = 0x2000000 
    circlePadState = 0x7ff7ff
    cppState = 0x80800081

    if state.lx != 0.0 or state.ly != 0.0:
        x = int(state.lx * CPAD_BOUND + 0x800)
        y = int(state.ly * CPAD_BOUND + 0x800)
        x = max(0, min(0xfff, x))
        y = max(0, min(0xfff, y))
        circlePadState = (y << 12) | x

    if state.rx != 0.0 or state.ry != 0.0 or irButtonsState != 0:
        x_val = math.sqrt(0.5) * (state.rx + state.ry) * CPP_BOUND + 0x80
        y_val = math.sqrt(0.5) * (state.ry - state.rx) * CPP_BOUND + 0x80
        x, y = int(x_val), int(y_val)
        x = max(0, min(0xff, x))
        y = max(0, min(0xff, y))
        cppState = (y << 24) | (x << 16) | (irButtonsState << 8) | 0x81

    if state.touchScreenPressed:
        tx = max(0, min(state.touchScreenPosition.x(), TOUCH_SCREEN_WIDTH))
        ty = max(0, min(state.touchScreenPosition.y(), TOUCH_SCREEN_HEIGHT))
        x = int(0xfff * tx / TOUCH_SCREEN_WIDTH)
        y = int(0xfff * ty / TOUCH_SCREEN_HEIGHT)
        touchScreenState = (1 << 24) | (y << 12) | x

    return struct.pack('<IIIII', hidPad, touchScreenState, circlePadState, cppState, state.interfaceButtons)

def get_release_packet():
    return struct.pack('<IIIII', 0xfff, 0x2000000, 0x7ff7ff, 0x80800081, 0)

def send_packet(ba):
    if state.ipAddress:
        if state.udp_socket is None:
            state.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            state.udp_socket.sendto(ba, (state.ipAddress, 4950))
        except:
            pass

class GamepadMonitor(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        pygame.init()
        pygame.joystick.init()
        self.joysticks = []
        self.rescan_joysticks()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_gamepad)
        self.timer.start(16)

    def rescan_joysticks(self):
        self.joysticks = [pygame.joystick.Joystick(i) for i in range(pygame.joystick.get_count())]
        for joy in self.joysticks: joy.init()

    def poll_gamepad(self):
        pygame.event.pump()
        if not self.joysticks:
            if pygame.joystick.get_count() > 0: self.rescan_joysticks()
            else: return
        joy = self.joysticks[0]
        try:
            state.lx = joy.get_axis(0)
            state.ly = joy.get_axis(1)
            if abs(state.lx) < 0.1: state.lx = 0
            if abs(state.ly) < 0.1: state.ly = 0
            state.ly = state.yAxisMultiplier * -state.ly
            
            if joy.get_numaxes() >= 4:
                rx_axis = 3 if joy.get_numaxes() > 3 else 2
                ry_axis = 4 if joy.get_numaxes() > 4 else 3
                state.rx = joy.get_axis(rx_axis)
                state.ry = joy.get_axis(ry_axis)
                if abs(state.rx) < 0.1: state.rx = 0
                if abs(state.ry) < 0.1: state.ry = 0
                state.ry = state.yAxisMultiplier * -state.ry

            mapping = {0: GamepadButtons.ButtonA, 1: GamepadButtons.ButtonB, 2: GamepadButtons.ButtonX, 
                       3: GamepadButtons.ButtonY, 4: GamepadButtons.ButtonL1, 5: GamepadButtons.ButtonR1, 
                       6: GamepadButtons.ButtonSelect, 7: GamepadButtons.ButtonStart, 8: GamepadButtons.ButtonGuide, 
                       9: GamepadButtons.ButtonL3, 10: GamepadButtons.ButtonR3}
            current_buttons = 0
            for py_btn, qt_btn in mapping.items():
                if py_btn < joy.get_numbuttons() and joy.get_button(py_btn):
                    current_buttons |= (1 << qt_btn)
            state.buttons = current_buttons
            
            if joy.get_numaxes() > 2 and joy.get_axis(2) > 0.5: state.buttons |= (1 << GamepadButtons.ButtonL2)
            if joy.get_numaxes() > 5 and joy.get_axis(5) > 0.5: state.buttons |= (1 << GamepadButtons.ButtonR2)
            
            if joy.get_numhats() > 0:
                hat = joy.get_hat(0)
                if hat[0] == -1: state.buttons |= (1 << GamepadButtons.ButtonLeft)
                if hat[0] == 1: state.buttons |= (1 << GamepadButtons.ButtonRight)
                if hat[1] == 1: state.buttons |= (1 << GamepadButtons.ButtonUp)
                if hat[1] == -1: state.buttons |= (1 << GamepadButtons.ButtonDown)

            def is_pressed(btn):
                if btn == GamepadButtons.ButtonInvalid: return False
                return (state.buttons & (1 << btn)) != 0

            home_btn = variant_to_button(state.settings.value("ButtonHome", GamepadButtons.ButtonInvalid))
            if is_pressed(home_btn): state.interfaceButtons |= 1
            else: state.interfaceButtons &= ~1
            power_btn = variant_to_button(state.settings.value("ButtonPower", GamepadButtons.ButtonInvalid))
            if is_pressed(power_btn): state.interfaceButtons |= 2
            else: state.interfaceButtons &= ~2
            power_long_btn = variant_to_button(state.settings.value("ButtonPowerLong", GamepadButtons.ButtonInvalid))
            if is_pressed(power_long_btn): state.interfaceButtons |= 4
            else: state.interfaceButtons &= ~4

            t1_btn = variant_to_button(state.settings.value("ButtonT1", GamepadButtons.ButtonInvalid))
            t2_btn = variant_to_button(state.settings.value("ButtonT2", GamepadButtons.ButtonInvalid))
            if is_pressed(t1_btn):
                state.touchScreenPressed = True
                state.touchScreenPosition = QPoint(int(state.settings.value("touchButton1X", 0)), int(state.settings.value("touchButton1Y", 0)))
            elif is_pressed(t2_btn):
                state.touchScreenPressed = True
                state.touchScreenPosition = QPoint(int(state.settings.value("touchButton2X", 0)), int(state.settings.value("touchButton2Y", 0)))
        except pygame.error: pass

class CameraSignals(QObject):
    status_update = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

class RemapConfig(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Button Config")
        self.layout = QVBoxLayout(self)
        self.formLayout = QFormLayout()
        
        def create_combo(setting_key, default_val):
            cb = QComboBox()
            items = [("A (bottom)", GamepadButtons.ButtonA), ("B (right)", GamepadButtons.ButtonB),
                     ("X (left)", GamepadButtons.ButtonX), ("Y (top)", GamepadButtons.ButtonY),
                     ("Right", GamepadButtons.ButtonRight), ("Left", GamepadButtons.ButtonLeft),
                     ("Up", GamepadButtons.ButtonUp), ("Down", GamepadButtons.ButtonDown),
                     ("RB", GamepadButtons.ButtonR1), ("LB", GamepadButtons.ButtonL1),
                     ("Select", GamepadButtons.ButtonSelect), ("Start", GamepadButtons.ButtonStart),
                     ("RT", GamepadButtons.ButtonR2), ("LT", GamepadButtons.ButtonL2),
                     ("L3", GamepadButtons.ButtonL3), ("R3", GamepadButtons.ButtonR3),
                     ("Guide", GamepadButtons.ButtonGuide), ("None", GamepadButtons.ButtonInvalid)]
            for text, data in items: cb.addItem(text, data)
            idx = cb.findData(variant_to_button(state.settings.value(setting_key, default_val)))
            if idx >= 0: cb.setCurrentIndex(idx)
            return cb

        self.combos = {
            "ButtonA": create_combo("ButtonA", GamepadButtons.ButtonA),
            "ButtonB": create_combo("ButtonB", GamepadButtons.ButtonB),
            "ButtonX": create_combo("ButtonX", GamepadButtons.ButtonX),
            "ButtonY": create_combo("ButtonY", GamepadButtons.ButtonY),
            "ButtonUp": create_combo("ButtonUp", GamepadButtons.ButtonUp),
            "ButtonDown": create_combo("ButtonDown", GamepadButtons.ButtonDown),
            "ButtonLeft": create_combo("ButtonLeft", GamepadButtons.ButtonLeft),
            "ButtonRight": create_combo("ButtonRight", GamepadButtons.ButtonRight),
            "ButtonL": create_combo("ButtonL", GamepadButtons.ButtonL1),
            "ButtonR": create_combo("ButtonR", GamepadButtons.ButtonR1),
            "ButtonSelect": create_combo("ButtonSelect", GamepadButtons.ButtonSelect),
            "ButtonStart": create_combo("ButtonStart", GamepadButtons.ButtonStart),
            "ButtonZL": create_combo("ButtonZL", GamepadButtons.ButtonL2),
            "ButtonZR": create_combo("ButtonZR", GamepadButtons.ButtonR2),
            "ButtonHome": create_combo("ButtonHome", GamepadButtons.ButtonInvalid),
            "ButtonPower": create_combo("ButtonPower", GamepadButtons.ButtonInvalid),
            "ButtonPowerLong": create_combo("ButtonPowerLong", GamepadButtons.ButtonInvalid),
            "ButtonT1": create_combo("ButtonT1", GamepadButtons.ButtonInvalid),
            "ButtonT2": create_combo("ButtonT2", GamepadButtons.ButtonInvalid),
        }

        for label, combo in self.combos.items(): self.formLayout.addRow(label, combo)
        
        self.t1x = QLineEdit(str(state.settings.value("touchButton1X", 0)))
        self.t1y = QLineEdit(str(state.settings.value("touchButton1Y", 0)))
        self.t2x = QLineEdit(str(state.settings.value("touchButton2X", 0)))
        self.t2y = QLineEdit(str(state.settings.value("touchButton2Y", 0)))
        self.formLayout.addRow("T1 X", self.t1x); self.formLayout.addRow("T1 Y", self.t1y)
        self.formLayout.addRow("T2 X", self.t2x); self.formLayout.addRow("T2 Y", self.t2y)

        self.saveButton = QPushButton("SAVE")
        self.saveButton.clicked.connect(self.save_settings)
        self.layout.addLayout(self.formLayout)
        self.layout.addWidget(self.saveButton)

    def save_settings(self):
        for key, combo in self.combos.items(): state.settings.setValue(key, combo.currentData())
        state.settings.setValue("touchButton1X", self.t1x.text())
        state.settings.setValue("touchButton1Y", self.t1y.text())
        state.settings.setValue("touchButton2X", self.t2x.text())
        state.settings.setValue("touchButton2Y", self.t2y.text())
        self.hide()

class AppWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.signals = CameraSignals()
        state.settings = QSettings("cylin_TW", "3DSC2")
        self.setup_variables()
        self.setup_ui()
        self.setup_connections()
        self.gamepad_monitor = GamepadMonitor(self)
        
        state.heartbeat_running = True
        self.heartbeat_thread = threading.Thread(target=self.heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()

    def setup_variables(self):
        self.camera_index = 0
        self.frame_width = 2560
        self.frame_height = 1440
        self.top_target = TOP_TARGET
        self.bottom_target = BOTTOM_TARGET
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.running = False
        self.roi_points = []
        self.screens = []
        self.all_points = []
        self.cap = None
        self.camera_thread = None
        self.windows_created = False
        
        state.ipAddress = state.settings.value("ipAddress", "")
        state.yAxisMultiplier = -1 if state.settings.value("invertY", False, type=bool) else 1
        state.abInverse = state.settings.value("invertAB", False, type=bool)    
        state.xyInverse = state.settings.value("invertXY", False, type=bool)

    def setup_ui(self):
        self.setWindowTitle("3DSC2")
        self.setMinimumSize(600, 600)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        cam_group = QGroupBox("Camera & Network")
        cam_layout = QFormLayout(cam_group)
        self.camera_combo = QComboBox()
        self.camera_combo.addItems([f"Camera {i}" for i in range(8)])
        cam_layout.addRow("Camera:", self.camera_combo)
        self.ip_edit = QLineEdit(state.ipAddress)
        cam_layout.addRow("3DS IP:", self.ip_edit)
        layout.addWidget(cam_group)

        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Camera")
        self.stop_btn = QPushButton("Stop Camera")
        self.stop_btn.setEnabled(False)
        self.reset_btn = QPushButton("Reset ROIs")
        self.config_btn = QPushButton("Button Config")
        btn_layout.addWidget(self.start_btn); btn_layout.addWidget(self.stop_btn)
        btn_layout.addWidget(self.reset_btn); btn_layout.addWidget(self.config_btn)
        layout.addLayout(btn_layout)

        tas_group = QGroupBox("Event Replay")
        tas_layout = QHBoxLayout(tas_group)
        self.record_btn = QPushButton("Record")
        self.play_btn = QPushButton("Play")
        self.save_tas_btn = QPushButton("Save Event")
        self.load_tas_btn = QPushButton("Load Event")
        tas_layout.addWidget(self.record_btn); tas_layout.addWidget(self.play_btn)
        tas_layout.addWidget(self.save_tas_btn); tas_layout.addWidget(self.load_tas_btn)
        layout.addWidget(tas_group)

        inv_layout = QHBoxLayout()
        self.inv_y = QCheckBox("Invert Y"); self.inv_y.setChecked(state.yAxisMultiplier == -1)
        self.inv_ab = QCheckBox("Invert A-B"); self.inv_ab.setChecked(state.abInverse)
        self.inv_xy = QCheckBox("Invert X-Y"); self.inv_xy.setChecked(state.xyInverse)
        inv_layout.addWidget(self.inv_y); inv_layout.addWidget(self.inv_ab); inv_layout.addWidget(self.inv_xy)
        layout.addLayout(inv_layout)

        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)
        self.instr = QTextEdit("1. Set the IP of your 3DS. 2. Click the start camera. 3. select ROIs (4 pts each screen). 4. Enjoy!")
        self.instr.setReadOnly(True); self.instr.setMaximumHeight(80)
        layout.addWidget(self.instr)
        
        self.fps_label = QLabel("FPS: --")
        layout.addWidget(self.fps_label)

        self.remap_dlg = RemapConfig(self)

    def setup_connections(self):
        self.start_btn.clicked.connect(self.start_camera)
        self.stop_btn.clicked.connect(self.stop_camera)
        self.reset_btn.clicked.connect(self.reset_rois)
        self.config_btn.clicked.connect(self.remap_dlg.show)
        self.ip_edit.textChanged.connect(self.update_ip)
        self.inv_y.stateChanged.connect(self.update_settings)
        self.inv_ab.stateChanged.connect(self.update_settings)
        self.inv_xy.stateChanged.connect(self.update_settings)
        
        self.record_btn.clicked.connect(self.toggle_record)
        self.play_btn.clicked.connect(self.toggle_play)
        self.save_tas_btn.clicked.connect(self.save_tas)
        self.load_tas_btn.clicked.connect(self.load_tas)

        self.signals.status_update.connect(self.status_label.setText)
        self.signals.error_occurred.connect(lambda m: QMessageBox.critical(self, "Error", m))

    def update_ip(self, t): 
        state.ipAddress = t
        state.settings.setValue("ipAddress", t)
    
    def update_settings(self):
        state.yAxisMultiplier = -1 if self.inv_y.isChecked() else 1
        state.abInverse = self.inv_ab.isChecked()
        state.xyInverse = self.inv_xy.isChecked()
        state.settings.setValue("invertY", self.inv_y.isChecked())
        state.settings.setValue("invertAB", self.inv_ab.isChecked())
        state.settings.setValue("invertXY", self.inv_xy.isChecked())

    def toggle_record(self):
        if not state.is_recording:
            state.tas_frames = []
            state.is_recording = True
            self.record_btn.setText("Stop Recording")
            self.signals.status_update.emit("Recording...")
        else:
            state.is_recording = False
            release_hex = get_release_packet().hex()
            for _ in range(5): state.tas_frames.append(release_hex)
            self.record_btn.setText("Record")
            self.signals.status_update.emit(f"Recorded {len(state.tas_frames)} frames")

    def toggle_play(self):
        if not state.tas_frames:
            self.signals.error_occurred.emit("No TAS data loaded")
            return
        if not state.is_playing:
            state.current_play_idx = 0
            state.is_playing = True
            self.play_btn.setText("Stop Playback")
            self.signals.status_update.emit("Playing...")
        else:
            state.is_playing = False
            self.play_btn.setText("Play")
            send_packet(get_release_packet()) 
            self.signals.status_update.emit("Playback stopped")

    def heartbeat_loop(self):
        next_tick = time.perf_counter()
        while state.heartbeat_running:
            if state.is_playing:
                if state.current_play_idx < len(state.tas_frames):
                    frame_hex = state.tas_frames[state.current_play_idx]
                    ba = bytes.fromhex(frame_hex)
                    send_packet(ba)
                    state.current_play_idx += 1
                else:
                    state.is_playing = False
                    send_packet(get_release_packet())
            else:
                ba = get_packet_data()
                if ba:
                    send_packet(ba)
                    if state.is_recording:
                        state.tas_frames.append(ba.hex())
            
            next_tick += TICK_RATE
            sleep_time = next_tick - time.perf_counter()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                next_tick = time.perf_counter()

    def save_tas(self):
        if not state.tas_frames: return
        path, _ = QFileDialog.getSaveFileName(self, "Save TAS", "", "JSON Files (*.json)")
        if path:
            with open(path, 'w') as f: json.dump(state.tas_frames, f)

    def load_tas(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load TAS", "", "JSON Files (*.json)")
        if path:
            with open(path, 'r') as f: state.tas_frames = json.load(f)
            self.signals.status_update.emit(f"Loaded {len(state.tas_frames)} frames")

    def camera_worker(self):
        try: self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except: pass
        while self.running:
            ret, frame = self.cap.read()
            if not ret: time.sleep(0.01); continue
            with self.frame_lock: self.latest_frame = frame.copy()

    def create_opencv_windows(self):
        if not self.windows_created:
            cv2.namedWindow("ROI Selector", cv2.WINDOW_NORMAL)
            cv2.setMouseCallback("ROI Selector", self.mouse_roi_callback)
            
            # Create resizable windows
            cv2.namedWindow("Top Screen", cv2.WINDOW_NORMAL)
            cv2.namedWindow("Bottom Screen", cv2.WINDOW_NORMAL)
            cv2.setMouseCallback("Bottom Screen", self.mouse_touch_callback)
            
            # Set initial default sizes
            cv2.resizeWindow("Top Screen", *self.top_target)
            cv2.resizeWindow("Bottom Screen", *self.bottom_target)
            self.windows_created = True

    def mouse_roi_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self.roi_points.append([x, y])
            self.all_points.append((x, y))
            if len(self.roi_points) == 4:
                self.screens.append(np.array(self.roi_points, dtype=np.float32).reshape(4, 2))
                self.roi_points = []
                self.signals.status_update.emit(f"ROI {len(self.screens)} selected")

    def mouse_touch_callback(self, event, x, y, flags, param):
        # Dynamically scale window coordinates to 320x240 for 3DS packet
        try:
            rect = cv2.getWindowImageRect("Bottom Screen")
            if rect and rect[2] > 0 and rect[3] > 0:
                win_w, win_h = rect[2], rect[3]
                scaled_x = int(x * (TOUCH_SCREEN_WIDTH / win_w))
                scaled_y = int(y * (TOUCH_SCREEN_HEIGHT / win_h))
            else:
                scaled_x, scaled_y = x, y
        except:
            scaled_x, scaled_y = x, y

        if event == cv2.EVENT_LBUTTONDOWN:
            state.touchScreenPressed = True
            state.touchScreenPosition = QPoint(scaled_x, scaled_y)
        elif event == cv2.EVENT_MOUSEMOVE and (flags & cv2.EVENT_FLAG_LBUTTON):
            state.touchScreenPosition = QPoint(scaled_x, scaled_y)
        elif event == cv2.EVENT_LBUTTONUP:
            state.touchScreenPressed = False

    def start_camera(self):
        idx = self.camera_combo.currentIndex()
        self.cap = cv2.VideoCapture(idx)
        if not self.cap.isOpened():
            self.signals.error_occurred.emit("Cannot open camera")
            return
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
        self.running = True
        self.camera_thread = threading.Thread(target=self.camera_worker, daemon=True)
        self.camera_thread.start()
        self.create_opencv_windows()
        self.start_btn.setEnabled(False); self.stop_btn.setEnabled(True)
        self.display_timer = QTimer()
        self.display_timer.timeout.connect(self.update_display)
        self.display_timer.start(33)

    def stop_camera(self):
        self.running = False
        if hasattr(self, 'display_timer'): self.display_timer.stop()
        if self.camera_thread: self.camera_thread.join(timeout=1.0)
        if self.cap: self.cap.release()
        cv2.destroyAllWindows(); self.windows_created = False
        self.start_btn.setEnabled(True); self.stop_btn.setEnabled(False)

    def reset_rois(self):
        self.screens.clear(); self.all_points.clear(); self.roi_points.clear()

    def update_display(self):
        with self.frame_lock: frame = self.latest_frame.copy() if self.latest_frame is not None else None
        if frame is None: return
        
        display = frame.copy()
        for pt in self.all_points: cv2.circle(display, pt, 6, (0, 255, 0), -1)
        if len(self.roi_points) > 1:
            for i in range(1, len(self.roi_points)):
                cv2.line(display, tuple(self.roi_points[i-1]), tuple(self.roi_points[i]), (255, 255, 0), 2)

        if len(self.screens) >= 1:
            top = self.warp_to_target(frame, self.screens[0], self.top_target)
            cv2.imshow("Top Screen", top)

        if len(self.screens) >= 2:
            bottom = self.warp_to_target(frame, self.screens[1], self.bottom_target)
            cv2.imshow("Bottom Screen", bottom)

        self.fps_label.setText(f"FPS: {self.cap.get(cv2.CAP_PROP_FPS):.1f}")
        cv2.imshow("ROI Selector", display)
        cv2.waitKey(1)

    def warp_to_target(self, image, pts, target_size):
        rect = np.zeros((4, 2), dtype="float32")
        s = pts.sum(axis=1); rect[0] = pts[np.argmin(s)]; rect[2] = pts[np.argmax(s)]
        diff = np.diff(pts, axis=1); rect[1] = pts[np.argmin(diff)]; rect[3] = pts[np.argmax(diff)]
        w, h = target_size
        dst = np.array([[0, 0], [w-1, 0], [w-1, h-1], [0, h-1]], dtype=np.float32)
        M = cv2.getPerspectiveTransform(rect, dst)
        return cv2.warpPerspective(image, M, (w, h))

    def closeEvent(self, e): 
        state.is_playing = False
        state.heartbeat_running = False
        self.stop_camera(); 
        e.accept()

def main():
    app = QApplication(sys.argv)
    style = """
    QWidget { background-color: #1e1e1e; color: #e0e0e0; font-family: sans-serif; }
    QLineEdit, QComboBox, QTextEdit { background-color: #2d2d2d; border: 1px solid #3d3d3d; border-radius: 4px; color: #fff; padding: 4px; }
    QPushButton { background-color: #333; border: 1px solid #444; border-radius: 6px; padding: 8px; color: #fff; font-weight: bold; }
    QPushButton:hover { background-color: #444; }
    QGroupBox { border: 1px solid #444; margin-top: 15px; font-weight: bold; padding-top: 20px; }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #aaa; }
    """
    app.setStyleSheet(style)
    win = AppWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()