import os
import subprocess
import json
from datetime import datetime, timedelta

def get_duration(file_path):
    """Get the duration of a video file in seconds using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(result.stdout.strip())
    except Exception as e:
        print(f"Error getting duration for {file_path}: {e}")
        return 0.0

def parse_timestamp(filename):
    """Extract timestamp from filename like 树_20251220_000024.mkv"""
    # Assuming format: Name_YYYYMMDD_HHMMSS*.mkv
    try:
        base = os.path.splitext(filename)[0]
        parts = base.split('_')
        
        date_str = ""
        time_str = ""
        
        # Iterate backwards to find the time components
        for i in range(len(parts)-1, 0, -1):
            if len(parts[i]) == 6 and parts[i].isdigit(): # HHMMSS
                if len(parts[i-1]) == 8 and parts[i-1].isdigit(): # YYYYMMDD
                    date_str = parts[i-1]
                    time_str = parts[i]
                    break
        
        if date_str and time_str:
            return datetime.strptime(f"{date_str}{time_str}", "%Y%m%d%H%M%S")
            
    except Exception as e:
        print(f"Error parsing filename {filename}: {e}")
    return None

def merge_videos_smart(directory):
    # Filter for mkv files starting with 树_ and exclude any merged files
    files = [f for f in os.listdir(directory) if f.endswith('.mkv') and 'merged' not in f]
    
    if not files:
        print("No files found.")
        return

    video_segments = []
    
    print("Analyzing files...")
    for f in files:
        path = os.path.join(directory, f)
        start_time = parse_timestamp(f)
        if not start_time:
            print(f"Skipping {f} (cannot parse timestamp)")
            continue
            
        duration = get_duration(path)
        end_time = start_time + timedelta(seconds=duration)
        
        video_segments.append({
            'file': f,
            'path': path,
            'start': start_time,
            'duration': duration,
            'end': end_time
        })
    
    # Sort by start time
    video_segments.sort(key=lambda x: x['start'])
    
    if not video_segments:
        print("No valid segments found.")
        return

    # Generate concat list
    list_path = os.path.join(directory, "file_list_smart.txt")
    final_segments = []
    
    # Add first segment
    current_end = video_segments[0]['end']
    final_segments.append({
        'path': video_segments[0]['path'],
        'inpoint': 0.0
    })
    
    print(f"1. {video_segments[0]['file']} (Start: {video_segments[0]['start']}, Dur: {video_segments[0]['duration']:.2f}s)")

    for i in range(1, len(video_segments)):
        seg = video_segments[i]
        
        # Calculate overlap
        overlap_seconds = (current_end - seg['start']).total_seconds()
        
        if overlap_seconds > 0:
            if overlap_seconds >= seg['duration']:
                print(f"{i+1}. {seg['file']} - Completely overlapped (Skipping)")
                continue # Skip this file entirely
            
            # IMPORTANT: We cannot use 'inpoint' with '-c copy' because cutting at a non-keyframe 
            # corrupts the video stream (causes Invalid NAL unit size / missing picture errors).
            # We must accept the overlap to ensure the output file is valid.
            print(f"{i+1}. {seg['file']} - Overlap: {overlap_seconds:.2f}s (Keeping overlap to preserve stream integrity)")
            final_segments.append({
                'path': seg['path'],
                'inpoint': 0.0
            })
            current_end = seg['end']
        else:
            # Gap or perfect abutment
            gap = -overlap_seconds
            print(f"{i+1}. {seg['file']} - Gap: {gap:.2f}s")
            final_segments.append({
                'path': seg['path'],
                'inpoint': 0.0
            })
            current_end = seg['end']

    # Write to file
    with open(list_path, "w", encoding="utf-8") as f:
        for item in final_segments:
            # Use absolute path to avoid relative path issues with ffmpeg concat demuxer
            abs_path = os.path.abspath(item['path'])
            f.write(f"file '{abs_path}'\n")
            if item['inpoint'] > 0:
                f.write(f"inpoint {item['inpoint']:.6f}\n")
    
    output_file = os.path.join(directory, f"{os.path.basename(directory)}_20251220_smart_merged.mkv")
    
    cmd = [
        "ffmpeg",
        "-f", "concat",
        "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        "-y",
        output_file
    ]
    
    print(f"Running ffmpeg...")
    try:
        subprocess.run(cmd, check=True)
        print(f"Successfully merged to {output_file}")
        os.remove(list_path)
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    import sys
    args = sys.argv[1]


    merge_videos_smart(args)
