import os
import glob
import subprocess
import json

# -------------------
# Global Variables
# -------------------
ASPECT_RATIO_W = 4      # 4:3 aspect ratio
ASPECT_RATIO_H = 3
TARGET_WIDTH   = 960    # final width after resize
TARGET_HEIGHT  = 720    # final height after resize

# Folder containing your source .mp4 files
SOURCE_DIR = r"C:\Path\To\Folder"

def get_video_resolution(filename):
    """
    Use ffprobe (JSON output) to get the width and height of the first video stream.
    Returns (width, height) as integers, or (None, None) on error.
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
    except subprocess.CalledProcessError:
        return (None, None)
    except json.JSONDecodeError:
        return (None, None)

def build_filter_string(width, height):
    """
    Given the input width/height, decide if we need to crop to 4:3.
    Then scale to (TARGET_WIDTH x TARGET_HEIGHT).
    
    Returns an FFmpeg -vf filter string, e.g.:
       "crop=...,scale=960:720"
    or if it's already 4:3, just 
       "scale=960:720"
    """
    # Convert to float for ratio comparison
    input_ratio = float(width) / float(height)
    desired_ratio = float(ASPECT_RATIO_W) / float(ASPECT_RATIO_H)

    # Small tolerance to consider floating inaccuracies
    EPSILON = 1e-3

    if abs(input_ratio - desired_ratio) < EPSILON:
        # Already 4:3, so no crop needed
        filter_str = f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}"
    else:
        # Need to center-crop to 4:3 first
        if input_ratio > desired_ratio:
            # Video is too wide: crop width
            new_width = int(round(height * desired_ratio))
            crop_x = int((width - new_width) / 2)
            # Example: crop=640:480:40:0 (meaning: crop WxH + x,y)
            filter_str = (
                f"crop={new_width}:{height}:{crop_x}:0,"
                f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}"
            )
        else:
            # Video is too tall: crop height
            new_height = int(round(width / desired_ratio))
            crop_y = int((height - new_height) / 2)
            filter_str = (
                f"crop={width}:{new_height}:0:{crop_y},"
                f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}"
            )

    return filter_str

def convert_video(input_path):
    """
    1) Get resolution
    2) Build the filter (crop if needed, then scale to 960x720)
    3) Run ffmpeg using GPU (h264_nvenc) and copy audio
    4) Output to new file with _4x3_960x720 in name
    """
    filename = os.path.basename(input_path)
    name, ext = os.path.splitext(filename)

    # 1) Get video resolution
    w, h = get_video_resolution(input_path)
    if w is None or h is None:
        print(f"Could not retrieve resolution for {filename}, skipping.")
        return

    # 2) Build the filter string
    vf_string = build_filter_string(w, h)

    # 3) Construct output file path
    output_path = os.path.join(
        SOURCE_DIR,
        f"{name}_4x3_{TARGET_WIDTH}x{TARGET_HEIGHT}{ext}"
    )

    # 4) FFmpeg command
    #    -hwaccel cuda               -> use GPU for decoding if possible
    #    -i input.mp4
    #    -vf "crop=...,scale=..., etc."  -> do the crop/scale on GPU filters if desired
    #    -c:v h264_nvenc             -> encode using NVIDIA GPU
    #    -c:a copy                   -> passthrough audio
    #
    # For GPU-based scaling/cropping, you could use scale_npp / crop_cuda filters,
    # but let's keep it simple with standard filters (they might run partially on CPU).
    #
    # If you want everything on GPU, you'd do something like:
    #   -vf "scale_npp=..., crop=..." 
    # but that requires custom parameters. The below approach uses normal filters,
    # which might not be 100% GPU pipeline. But it uses the GPU for encoding.
    #
    # If hardware decoding is not supported for your video codec, it may fall back to CPU decode.
    cmd = [
        "ffmpeg",
        "-hwaccel", "cuda",               # try to decode on GPU
        "-i", input_path,
        "-vf", vf_string,
        "-c:v", "h264_nvenc",            # GPU-based H.264 encoder
        "-c:a", "copy",                  # copy audio
        "-y",                             # overwrite output if it exists
        output_path
    ]

    print(f"\nProcessing {filename} -> {os.path.basename(output_path)}")
    subprocess.run(cmd)

def main():
    mp4_files = glob.glob(os.path.join(SOURCE_DIR, "*.mp4"))
    if not mp4_files:
        print(f"No .mp4 files found in {SOURCE_DIR}")
        return

    for video_file in mp4_files:
        convert_video(video_file)

if __name__ == "__main__":
    main()
