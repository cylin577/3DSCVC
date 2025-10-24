
# 3DSCVC 
Capture your 3DS screen — no modding, no nonsense.

## Why?
I’ve got an O3DS LL, and I wanted to stream its screens to my computer —  
but that’s something only ~~Apple~~ the *New 3DS* can do.  
So I made this!  

3DSCVC lets you stream **any 3DS**, old or new, using just a camera.  
No capture card, no soldering.

## How to use
Here’s all you need to get started:

- A working Python environment (using `uv` is recommended)
- A good webcam or camera
- A brain 
- A computer or Raspberry Pi

This example uses **uv** as the package manager.

1. Clone the repo  
   ```bash/CMD
   git clone https://github.com/cylin577/3DSCVC
   cd 3DSCVC
   ```

2. Create and activate a virtual environment  
   ```bash/CMD
   uv venv
   ```
   2. Activate the virtual environment  
	   ```bash
	   source .venv/bin/activate
	   ```
	   Or
	   ```CMD
	    .venv/Scripts/activate
	   ```
	   

3. Install dependencies  
   ```bash/CMD
   uv pip install -r requirements.txt
   ```

4. Run it  
   ```bash/CMD
   python main.py
   ```

That’s it !

