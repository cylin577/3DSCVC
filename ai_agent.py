import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.utils.data import TensorDataset, DataLoader
import numpy as np
import cv2
import os
import threading
import sys
from PyQt6.QtCore import QObject, pyqtSignal

# Input image size for the model
IMG_W, IMG_H = 128, 96

DEBUG = "--debug" in sys.argv

def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

class BehaviorCloningModel(nn.Module):
    def __init__(self, num_buttons=32):
        super(BehaviorCloningModel, self).__init__()
        
        # CNN Feature Extractor
        self.conv1 = nn.Conv2d(1, 16, kernel_size=3, padding=1)
        self.conv2 = nn.Conv2d(16, 32, kernel_size=3, padding=1)
        self.conv3 = nn.Conv2d(32, 64, kernel_size=3, padding=1)
        self.pool = nn.MaxPool2d(2, 2)
        
        # Calculate flattened size
        # 128x96 -> 64x48 -> 32x24 -> 16x12
        self.flatten_size = 64 * 16 * 12
        
        # Fully Connected Layers
        self.fc1 = nn.Linear(self.flatten_size, 256)
        
        # Heads
        self.fc_axes = nn.Linear(256, 4) # LX, LY, RX, RY
        self.fc_buttons = nn.Linear(256, num_buttons) # Bitmask bits
        
    def forward(self, x):
        # x: (B, 1, H, W)
        x = self.pool(F.relu(self.conv1(x)))
        x = self.pool(F.relu(self.conv2(x)))
        x = self.pool(F.relu(self.conv3(x)))
        
        x = x.view(-1, self.flatten_size)
        x = F.relu(self.fc1(x))
        
        axes = torch.tanh(self.fc_axes(x)) # -1 to 1 for axes
        buttons = self.fc_buttons(x)       # Logits for BCE
        
        return axes, buttons

class AIManager(QObject):
    status_update = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = BehaviorCloningModel().to(self.device)
        self.optimizer = optim.Adam(self.model.parameters(), lr=0.001)
        
        self.data_frames = []
        self.data_axes = []
        self.data_buttons = []
        
        self.is_recording = False
        self.is_active = False
        self.model_path = "bc_model.pth"
        
        debug_print(f"AI Manager initialized on: {self.device}")

    def reset_data(self):
        self.data_frames = []
        self.data_axes = []
        self.data_buttons = []
        self.status_update.emit("Training data cleared")

    def toggle_recording(self):
        self.is_recording = not self.is_recording
        return self.is_recording

    def toggle_active(self):
        if not os.path.exists(self.model_path) and not self.data_frames:
            self.status_update.emit("No model found. Train first!")
            return False
        
        # Try loading if not loaded/trained recently
        if os.path.exists(self.model_path):
             self.load_model()

        self.is_active = not self.is_active
        return self.is_active

    def preprocess_frame(self, frame):
        # Grayscale + Resize
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, (IMG_W, IMG_H))
        # Normalize 0-1
        return resized.astype(np.float32) / 255.0

    def add_sample(self, frame, axes, buttons_int):
        if not self.is_recording: return
        
        processed = self.preprocess_frame(frame)
        self.data_frames.append(processed)
        self.data_axes.append(axes)
        
        # Convert integer bitmask to binary vector (32 bits)
        btn_vector = [(buttons_int >> i) & 1 for i in range(32)]
        self.data_buttons.append(btn_vector)
        
        if len(self.data_frames) % 100 == 0:
            self.status_update.emit(f"Collected {len(self.data_frames)} samples")

    def train(self):
        if not self.data_frames:
            self.status_update.emit("No data to train on!")
            return

        threading.Thread(target=self._train_loop, daemon=True).start()

    def _train_loop(self):
        self.status_update.emit("Preparing data...")
        
        X = torch.tensor(np.array(self.data_frames), dtype=torch.float32).unsqueeze(1).to(self.device) # (N, 1, H, W)
        y_axes = torch.tensor(np.array(self.data_axes), dtype=torch.float32).to(self.device)
        y_buttons = torch.tensor(np.array(self.data_buttons), dtype=torch.float32).to(self.device)
        
        dataset = TensorDataset(X, y_axes, y_buttons)
        loader = DataLoader(dataset, batch_size=32, shuffle=True)
        
        self.model.train()
        epochs = 10
        
        self.status_update.emit(f"Training on {self.device} for {epochs} epochs...")
        
        for epoch in range(epochs):
            total_loss = 0
            for batch_x, batch_ax, batch_btn in loader:
                self.optimizer.zero_grad()
                pred_ax, pred_btn = self.model(batch_x)
                
                loss_ax = F.mse_loss(pred_ax, batch_ax)
                loss_btn = F.binary_cross_entropy_with_logits(pred_btn, batch_btn)
                
                loss = loss_ax + loss_btn
                loss.backward()
                self.optimizer.step()
                
                total_loss += loss.item()
            
            avg_loss = total_loss / len(loader)
            self.status_update.emit(f"Epoch {epoch+1}/{epochs} - Loss: {avg_loss:.4f}")
        
        torch.save(self.model.state_dict(), self.model_path)
        self.status_update.emit("Training complete & saved!")
        
        # Optional: clear RAM
        # self.data_frames = []
        # self.data_axes = []
        # self.data_buttons = []

    def load_model(self):
        if os.path.exists(self.model_path):
            try:
                self.model.load_state_dict(torch.load(self.model_path, map_location=self.device))
                self.model.eval()
                # self.status_update.emit("Model loaded")
                return True
            except Exception as e:
                debug_print(f"Load error: {e}")
                self.status_update.emit("Failed to load model")
        return False

    def predict(self, frame):
        if not self.model: return None, 0
        
        processed = self.preprocess_frame(frame)
        tensor_x = torch.tensor(processed, dtype=torch.float32).unsqueeze(0).unsqueeze(0).to(self.device)
        
        with torch.no_grad():
            pred_ax, pred_btn = self.model(tensor_x)
        
        # Parse output
        axes = pred_ax.cpu().numpy()[0] # [lx, ly, rx, ry]
        
        # Convert logits to bitmask
        btn_probs = torch.sigmoid(pred_btn).cpu().numpy()[0]
        buttons_int = 0
        for i, prob in enumerate(btn_probs):
            if prob > 0.5:
                buttons_int |= (1 << i)
                
        return axes, buttons_int
