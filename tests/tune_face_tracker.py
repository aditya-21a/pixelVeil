import sys
import time
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.video_pipeline import process_video

def main():
    input_video = "tests/sample_videos/multiple_people_complex.mp4"
    if not os.path.exists(input_video):
        print(f"Error: {input_video} not found.")
        return
        
    out_dir = "tests/assets"
    os.makedirs(out_dir, exist_ok=True)
    
    print("Starting parameter sweep on multiple_people_complex.mp4...\n")
    
    sweep_params = [
        {"max_missing": 0, "damping": 1.0}, # Baseline (no tracking)
        {"max_missing": 5, "damping": 0.8},
        {"max_missing": 10, "damping": 0.8},
        {"max_missing": 15, "damping": 0.8},
        {"max_missing": 20, "damping": 0.8},
        {"max_missing": 15, "damping": 0.5},
    ]
    
    for i, p in enumerate(sweep_params):
        mm = p["max_missing"]
        vd = p["damping"]
        out_video = os.path.join(out_dir, f"tuned_{mm}_{vd}.mp4")
        
        print(f"[{i+1}/{len(sweep_params)}] Testing max_missing_frames={mm}, velocity_damping={vd}")
        start_time = time.time()
        
        try:
            summary = process_video(
                input_path=input_video,
                output_path=out_video,
                tracker_max_missing_frames=mm,
                tracker_velocity_damping=vd,
                face_redaction_method="blur",
            )
            elapsed = time.time() - start_time
            
            metrics = summary.get("tracker_metrics", {})
            print(f"  -> Processed {summary['frames_processed']} frames in {elapsed:.2f}s")
            print(f"  -> Raw Detections: {metrics.get('raw_detections')}")
            print(f"  -> Zero-Detections Frames (Misses): {metrics.get('raw_misses')}")
            print(f"  -> Recovered Gaps (Coasting Frames): {metrics.get('coasting_frames')}")
            print(f"  -> Tracks Created: {metrics.get('tracks_created')}")
            print(f"  -> Track Fragmentations: {metrics.get('track_fragmentations')}")
            print(f"  -> Output saved to {out_video}\n")
        except Exception as e:
            print(f"  -> Error: {e}\n")
            
if __name__ == "__main__":
    main()
