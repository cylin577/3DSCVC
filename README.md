

# 3DSCVC 
Capture your 3DS screen — no modding, no nonsense.

## Why?
I’ve got an O3DS LL, and I wanted to stream its screens to my computer —  
but that’s something only ~~Apple~~ the *New 3DS* can do.  
So I made this!  

3DSCVC lets you stream **any 3DS**, using just a camera.  
No capture card, no soldering, no modding.

## How to use
Here’s all you need to get started:

- A working Python environment (using `uv` is recommended)
- A webcam or camera
- A computer or Raspberry Pi
- A 3DS with InputRedirection enabled (e.g., via Luma3DS)
- A brain (optional)

This project uses **uv** for seamless dependency management.

1. Clone the repo  
   ```bash
   git clone https://github.com/cylin577/3DSCVC
   cd 3DSCVC
   ```

2. Run the application
   ```bash
   uv run 3dscvc.py
   ```
   *Note: `uv` will automatically handle all dependencies including OpenCV, PyQt6, and Pygame.*

3. Setup & Calibration
   - Enter your **3DS IP Address**.
   - Select your camera from the dropdown and click **Start Camera**.
   - **Calibrate ROIs:** In the "ROI Selector" window, click the 4 corners of your **Top Screen**, followed by the 4 corners of your **Bottom Screen**.
   - The Top and Bottom screens will appear in separate, **resizable windows**.

4. Interaction & TAS
   - **Touch Control:** Click or drag directly on the **Bottom Screen** window to control the 3DS touch screen. The input scales automatically with window size.
   - **Gamepad:** Connect a controller to use physical buttons/sticks.
   - **TAS (Tool-Assisted Speedrun):** Use the **Record**, **Play**, and **Save/Load TAS** buttons to automate or replay your gameplay with 20Hz precision.

That’s it !

## TODOs
 
 1. Make a homebrew app for automatic calibration
 2. Super-Resolution support? (But nothing can't be solved using a 4K camera)
 3. Stabilized tracking? (Captured screen won't shift around when you play rhythm games)

## Contribute
If you found this project useful, please star this repo, and if you can code, PLEASE help me do some TODOs, because I spend an entire night and still didn't figure out how to do auto calibration
