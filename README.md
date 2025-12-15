

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
- A good webcam or camera
- A brain (Optitional)
- A computer or Raspberry Pi

This example uses **uv** as the package manager.

1. Clone the repo  
   ```
   git clone https://github.com/cylin577/3DSCVC
   cd 3DSCVC
   ```

2. Create and activate a virtual environment  
   ```
   uv venv
   ```
   2. Activate the virtual environment  
	   ```
	   source .venv/bin/activate
	   ```
	   Or
	   ```
	    .venv/Scripts/activate
	   ```
	   if you're on Windows 
	   

3. Install dependencies  
   ```
   uv pip install -r requirements.txt
   ```

4. Run it  
   ```
   python main.py
   ```

That’s it !

## TODOs
 
 1. Make a homebrew app for automatic calibration
 2. Super-Resolution support? (But nothing can't be solved using a 4K camera)
 3. Stabilized tracking? (Captured screen won't shift around when you play rhythm games)

## Contribute
If you found this project useful, please star this repo, and if you can code, PLEASE help me do some TODOs, because I spend an entire night and still didn't figure out how to do auto calibration
