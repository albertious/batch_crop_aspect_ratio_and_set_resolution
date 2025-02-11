import os
import glob
import subprocess
import json

# -------------------
# Global Variables
# -------------------
ASPECT_RATIO_W = 4   # e.g. 4 for 4:3
ASPECT_RATIO_H = 3   # e.g. 3 for 4:3
TARGET_WIDTH   = 960 # final width after resizing
TARGET_HEIGHT  = 720 # final height after resizing

# Folder containing your source .mp4 files
SOURCE_DIR = r"C:\Path\To\Folder"

def get_video_resolution(filename):
    """
    Use ffprobe to extract (width, height) of the first video stream in a file.
    Returns (None, None) on error.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        filename
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if not streams:
            return (None, None)
        width = streams[0].get("width")
        height = streams[0].get("height")
        return (width, height)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return (None, None)

def build_filter_string(width, height):
    """
    Decide if we need to crop to 4:3, then scale to TARGET_WIDTH x TARGET_HEIGHT.
    Returns an FFmpeg -vf filter string, e.g. "crop=...,scale=960:720" or "scale=960:720"
    """
    input_ratio = float(width) / float(height)
    desired_ratio = float(ASPECT_RATIO_W) / float(ASPECT_RATIO_H)
    EPSILON = 1e-3

    if abs(input_ratio - desired_ratio) < EPSILON:
        # Already ~4:3, no crop needed
        filter_str = f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}"
    else:
        # Need to center-crop to 4:3
        if input_ratio > desired_ratio:
            # Too wide => crop width
            new_width = int(round(height * desired_ratio))
            crop_x = int((width - new_width) / 2)
            filter_str = (
                f"crop={new_width}:{height}:{crop_x}:0,"
                f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}"
            )
        else:
            # Too tall => crop height
            new_height = int(round(width / desired_ratio))
            crop_y = int((height - new_height) / 2)
            filter_str = (
                f"crop={width}:{new_height}:0:{crop_y},"
                f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}"
            )
    return filter_str

def process_file(input_path):
    """
    1) Determine if the video needs cropping.
    2) Resize to TARGET_WIDTH x TARGET_HEIGHT.
    3) Use GPU (h264_nvenc) for video encoding, copy audio.
    4) Overwrite the original by writing to a temp file, then renaming.
    """
    filename = os.path.basename(input_path)
    print(f"\nProcessing: {filename}")

    # 1) Get resolution
    w, h = get_video_resolution(input_path)
    if w is None or h is None:
        print(f"  [ERROR] Could not determine resolution. Skipping.")
        return

    # 2) Build filter string
    vf_string = build_filter_string(w, h)

    # 3) Construct a temporary file path in the same directory
    temp_path = input_path + ".temp.mp4"

    # 4) ffmpeg command
    cmd = [
        "ffmpeg",
        # Attempt GPU-based decoding
        "-hwaccel", "cuda",
        "-i", input_path,
        # Apply our crop+scale filter
        "-vf", vf_string,
        # Use NVENC for video
        "-c:v", "h264_nvenc",
        # Copy audio as is
        "-c:a", "copy",
        # Overwrite existing output if it exists
        "-y",
        temp_path
    ]

    # Run FFmpeg
    result = subprocess.run(cmd)

    # Check if FFmpeg was successful
    if result.returncode == 0:
        # Remove the original and rename the temp to original
        try:
            os.remove(input_path)
            os.rename(temp_path, input_path)
            print(f"  [OK] Overwrote {filename} with 4:3 {TARGET_WIDTH}x{TARGET_HEIGHT}.")
        except OSError as e:
            print(f"  [ERROR] Couldn't replace original file: {e}")
    else:
        print(f"  [ERROR] FFmpeg failed on {filename}. Return code: {result.returncode}")
        # Optionally remove temp file if FFmpeg failed
        if os.path.exists(temp_path):
            os.remove(temp_path)

def main():
    # Find all .mp4 files in SOURCE_DIR
    mp4_files = glob.glob(os.path.join(SOURCE_DIR, "*.mp4"))
    if not mp4_files:
        print(f"No .mp4 files found in {SOURCE_DIR}")
        return

    for mp4_file in mp4_files:
        process_file(mp4_file)

if __name__ == "__main__":
    main()
