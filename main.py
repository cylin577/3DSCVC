import cv2
import numpy as np
import threading
import time
import sys
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QComboBox, QPushButton,
                             QGroupBox, QTextEdit, QMessageBox)
from PyQt6.QtCore import QTimer, pyqtSignal, QObject


# 3DSCVC


class CameraSignals(QObject):
    status_update = pyqtSignal(str)
    error_occurred = pyqtSignal(str)


class threeDSCVC(QMainWindow):
    def __init__(self):
        super().__init__()
        self.signals = CameraSignals()
        self.setup_variables()
        self.setup_ui()
        self.setup_connections()

    def setup_variables(self):
        # Configuration
        self.camera_index = 0
        self.frame_width = 1280
        self.frame_height = 720
        self.top_target = (400, 240)
        self.bottom_target = (320, 240)

        # State variables
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.running = False
        self.roi_points = []
        self.screens = []
        self.all_points = []
        self.fps = 0.0
        self.cap = None
        self.camera_thread = None

        # OpenCV windows
        self.windows_created = False

    def setup_ui(self):
        self.setWindowTitle("3DSCVC")
        self.setMinimumSize(500, 400)

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Camera control group
        camera_group = QGroupBox("Camera Configuration")
        camera_layout = QVBoxLayout(camera_group)

        # Camera selection
        cam_selection_layout = QHBoxLayout()
        cam_selection_layout.addWidget(QLabel("Camera:"))
        self.camera_combo = QComboBox()
        self.camera_combo.addItems(
            ["Camera 0", "Camera 1", "Camera 2", "Camera 3"])
        cam_selection_layout.addWidget(self.camera_combo)
        cam_selection_layout.addStretch()
        camera_layout.addLayout(cam_selection_layout)

        # Control buttons
        button_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Camera")
        self.stop_btn = QPushButton("Stop Camera")
        self.stop_btn.setEnabled(False)
        self.reset_btn = QPushButton("Reset ROIs")

        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.stop_btn)
        button_layout.addWidget(self.reset_btn)
        camera_layout.addLayout(button_layout)

        # Status
        self.status_label = QLabel("Ready to start camera")
        camera_layout.addWidget(self.status_label)

        layout.addWidget(camera_group)

        # Instructions group
        instr_group = QGroupBox("Instructions")
        instr_layout = QVBoxLayout(instr_group)
        instructions = QTextEdit()
        instructions.setPlainText(
            " 3DSCVC \n\n"
            "1. Click 'Start Camera' to begin\n"
            "2. click 4 corners for the top screen\n"
            "3. Click 4 corners for the bottom screen\n"
            "4. Two separate windows will show the warped screens\n"
            "5. Press 'r' in ROI window to reset points\n"
            "6. Press 'q' in ROI window to quit\n\n"
        )
        instructions.setReadOnly(True)
        instructions.setMaximumHeight(160)
        instr_layout.addWidget(instructions)
        layout.addWidget(instr_group)

        # FPS display
        self.fps_label = QLabel("FPS: --")
        layout.addWidget(self.fps_label)

        layout.addStretch()

    def setup_connections(self):
        self.start_btn.clicked.connect(self.start_camera)
        self.stop_btn.clicked.connect(self.stop_camera)
        self.reset_btn.clicked.connect(self.reset_rois)
        self.camera_combo.currentIndexChanged.connect(self.camera_changed)
        self.signals.status_update.connect(self.update_status)
        self.signals.error_occurred.connect(self.show_error)

    def camera_changed(self, index):
        self.camera_index = index

    def update_status(self, message):
        self.status_label.setText(message)

    def show_error(self, message):
        QMessageBox.critical(self, "Error", message)

    def camera_worker(self):
        try:
            # Try to reduce buffer for lower latency
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.01)
                continue
            with self.frame_lock:
                self.latest_frame = frame.copy()

    def create_opencv_windows(self):
        if not self.windows_created:
            cv2.namedWindow("ROI Selector - 3DSCVC", cv2.WINDOW_NORMAL)
            cv2.setMouseCallback("ROI Selector - 3DSCVC", self.mouse_callback)
            cv2.namedWindow("Top Screen", cv2.WINDOW_NORMAL)
            cv2.namedWindow("Bottom Screen", cv2.WINDOW_NORMAL)
            cv2.resizeWindow("Top Screen", *self.top_target)
            cv2.resizeWindow("Bottom Screen", *self.bottom_target)
            self.windows_created = True

    def close_opencv_windows(self):
        if self.windows_created:
            cv2.destroyAllWindows()
            self.windows_created = False

    def mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            with self.frame_lock:
                frame_copy = self.latest_frame.copy() if self.latest_frame is not None else None
            if frame_copy is None:
                self.signals.status_update.emit(
                    "No frame available for selection")
                return

            self.roi_points.append([x, y])
            self.all_points.append((x, y))

            if len(self.roi_points) == 4:
                roi_array = np.array(
                    self.roi_points, dtype=np.float32).reshape(4, 2)
                self.screens.append(roi_array)
                self.roi_points = []

                screen_num = len(self.screens)
                status_msg = f"Screen {screen_num} ROI selected"
                self.signals.status_update.emit(status_msg)

                if screen_num == 1:
                    self.signals.status_update.emit(
                        "Select 4 corners for bottom screen")
                elif screen_num == 2:
                    self.signals.status_update.emit("Ready!")

    def order_points(self, pts):
        rect = np.zeros((4, 2), dtype="float32")
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]   # top-left
        rect[2] = pts[np.argmax(s)]   # bottom-right
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]  # top-right
        rect[3] = pts[np.argmax(diff)]  # bottom-left
        return rect

    def warp_to_target(self, image, pts, target_size):
        rect = self.order_points(np.array(pts, dtype=np.float32))
        w, h = target_size
        dst = np.array([[0, 0], [w-1, 0], [w-1, h-1],
                       [0, h-1]], dtype=np.float32)
        M = cv2.getPerspectiveTransform(rect, dst)
        return cv2.warpPerspective(image, M, (w, h))

    def start_camera(self):
        try:
            # Try different backends for maximum compatibility
            backends = [self.camera_index]  # Default first
            if sys.platform.startswith('linux'):
                backends.append(self.camera_index + cv2.CAP_V4L2)
            elif sys.platform.startswith('win'):
                backends.append(self.camera_index + cv2.CAP_DSHOW)

            self.cap = None
            for backend in backends:
                try:
                    self.cap = cv2.VideoCapture(backend)
                    if self.cap.isOpened():
                        break
                except Exception:
                    continue

            if self.cap is None or not self.cap.isOpened():
                self.signals.error_occurred.emit(
                    "Cannot access camera. Please check camera index and permissions.")
                return

            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)

            # Test camera
            ret, test_frame = self.cap.read()
            if not ret:
                self.signals.error_occurred.emit(
                    "Camera found but cannot read frames. Check if another app is using it.")
                self.cap.release()
                return

            self.running = True
            self.camera_thread = threading.Thread(
                target=self.camera_worker, daemon=True)
            self.camera_thread.start()

            self.create_opencv_windows()

            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.signals.status_update.emit(
                "Camera started! Select ROIs in the preview window 🎯")

            # Start display timer
            self.display_timer = QTimer()
            self.display_timer.timeout.connect(self.update_display)
            self.display_timer.start(30)  # ~33 FPS

        except Exception as e:
            self.signals.error_occurred.emit(
                f"Failed to start camera: {str(e)}")

    def stop_camera(self):
        self.running = False

        if hasattr(self, 'display_timer'):
            self.display_timer.stop()

        if self.camera_thread and self.camera_thread.is_alive():
            self.camera_thread.join(timeout=1.0)

        if self.cap:
            self.cap.release()

        self.close_opencv_windows()

        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.signals.status_update.emit("Camera stopped")

    def reset_rois(self):
        self.screens.clear()
        self.all_points.clear()
        self.roi_points.clear()
        self.signals.status_update.emit(
            "ROIs reset - ready to select new regions")

    def update_display(self):
        if not self.running:
            return

        with self.frame_lock:
            frame = self.latest_frame.copy() if self.latest_frame is not None else None

        if frame is None:
            # Display waiting message
            blank = np.zeros((240, 320, 3), dtype=np.uint8)
            cv2.putText(blank, "Waiting for camera...", (10, 120),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
            cv2.imshow("ROI Selector - 3DSCVC", blank)
            return

        display = frame.copy()

        # Draw selected points
        for pt in self.all_points:
            cv2.circle(display, pt, 6, (0, 255, 0), -1)

        # Draw connecting lines for current ROI
        if len(self.roi_points) > 1:
            for i in range(1, len(self.roi_points)):
                cv2.line(display, tuple(
                    self.roi_points[i-1]), tuple(self.roi_points[i]), (255, 255, 0), 2)

        # Warp and display screens if ROIs are defined
        if len(self.screens) >= 1:
            try:
                top = self.warp_to_target(
                    frame, self.screens[0], self.top_target)
                cv2.imshow("Top Screen", top)
            except Exception as e:
                print("Top screen transformation error:", e)

        if len(self.screens) >= 2:
            try:
                bottom = self.warp_to_target(
                    frame, self.screens[1], self.bottom_target)
                cv2.imshow("Bottom Screen", bottom)
            except Exception as e:
                print("Bottom screen transformation error:", e)

        # Calculate FPS
        if self.cap:
            self.fps = self.cap.get(cv2.CAP_PROP_FPS)
            if self.fps <= 0:  # Fallback calculation
                self.fps = 30  # Reasonable default
        else:
            self.fps = 0

        self.fps_label.setText(f"FPS: {self.fps:.1f}")

        cv2.putText(display, f"FPS: {self.fps:.1f}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        cv2.putText(display, "Click 4 points per screen", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        cv2.imshow("ROI Selector - 3DSCVC", display)

        # Handle key presses
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            self.stop_camera()
        elif key == ord('r'):
            self.reset_rois()

    def closeEvent(self, event):
        self.stop_camera()
        event.accept()


def main():
    app = QApplication(sys.argv)

    # Set application properties
    app.setApplicationName("3DSCVC")
    app.setApplicationVersion("1.0")
    app.setOrganizationName("cylin_TW")

    window = threeDSCVC()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
