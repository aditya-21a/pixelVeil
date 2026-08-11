import os
import sys
import time
import json
import cv2

# Ensure we can import core modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import face_detector
from core.face_tracker import FaceTracker
from core import device_manager

TEST_VIDEOS_DIR = "tests/sample_videos"
OUTPUT_JSON = "tests/assets/face_detector_benchmark.json"

def get_video_files():
    if not os.path.isdir(TEST_VIDEOS_DIR):
        return []
    files = []
    for f in os.listdir(TEST_VIDEOS_DIR):
        if f.endswith('.mp4'):
            files.append(os.path.join(TEST_VIDEOS_DIR, f))
    return files

def load_frames(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None, 0, 0
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
    cap.release()
    return frames, fps, len(frames)

def run_benchmark_for_config(frames, device_config_str, backend_name):
    # Setup device
    try:
        req_device = "cuda" if "cuda" in device_config_str else "cpu"
        resolved_device = device_manager.get_compute_device(req_device)
        if resolved_device != req_device:
            return {"error": f"Requested {req_device} but got {resolved_device}"}
            
        face_detector.set_compute_device(device_config_str)
        # Force initialization and warm-up
        _ = face_detector.detect_faces(frames[0])
    except Exception as e:
        return {"error": str(e)}

    # We run it twice: once for raw latency, once with FaceTracker to measure privacy recall
    
    # Run 1: Raw detection (Latency + Raw Recall)
    total_latency_ms = 0.0
    raw_faces_detected = 0
    raw_frames_with_faces = 0
    raw_missed_frames = 0
    longest_miss_run = 0
    current_miss_run = 0
    
    raw_detections_per_frame = []

    for frame in frames:
        t0 = time.perf_counter()
        boxes = face_detector.detect_faces(frame)
        t1 = time.perf_counter()
        total_latency_ms += (t1 - t0) * 1000.0
        
        raw_detections_per_frame.append(boxes)
        count = len(boxes)
        raw_faces_detected += count
        if count > 0:
            raw_frames_with_faces += 1
            current_miss_run = 0
        else:
            raw_missed_frames += 1
            current_miss_run += 1
            if current_miss_run > longest_miss_run:
                longest_miss_run = current_miss_run

    avg_latency_ms = total_latency_ms / len(frames)
    fps = 1000.0 / avg_latency_ms if avg_latency_ms > 0 else 0

    # Run 2: With FaceTracker
    tracker = FaceTracker(max_missing_frames=15, velocity_damping=0.8, smoothing_alpha=1.0)
    tracker_faces_detected = 0
    tracker_frames_with_faces = 0
    tracker_unprotected_frames = 0 # Frames where tracker output is 0 but we know there should be a face
    
    for boxes, frame in zip(raw_detections_per_frame, frames):
        tracked_boxes = tracker.update(boxes, frame.shape)
        count = len(tracked_boxes)
        tracker_faces_detected += count
        if count > 0:
            tracker_frames_with_faces += 1
        else:
            tracker_unprotected_frames += 1

    provider = face_detector.get_active_provider()
    
    return {
        "backend": backend_name,
        "device": resolved_device,
        "provider": provider,
        "avg_latency_ms": round(avg_latency_ms, 2),
        "fps": round(fps, 1),
        "raw_faces_detected": raw_faces_detected,
        "raw_frames_with_faces": raw_frames_with_faces,
        "raw_missed_frames": raw_missed_frames,
        "longest_miss_run": longest_miss_run,
        "tracker_faces_detected": tracker_faces_detected,
        "tracker_frames_with_faces": tracker_frames_with_faces,
        "tracker_unprotected_frames": tracker_unprotected_frames,
    }

def main():
    videos = get_video_files()
    if not videos:
        print("No videos found in", TEST_VIDEOS_DIR)
        return

    # To be tested
    configs = [
        {"id": "mediapipe_cpu", "device": "cpu"},
        {"id": "yunet_cpu", "device": "yunet_cpu"},
        {"id": "yunet_cuda", "device": "yunet_cuda"},
        {"id": "scrfd_cpu", "device": "scrfd_cpu"},
        {"id": "scrfd_cuda", "device": "scrfd_cuda"},
    ]

    results = {}
    
    dev_info = device_manager.get_device_info()

    for v in videos:
        print(f"Loading {os.path.basename(v)}...", flush=True)
        frames, fps, total_frames = load_frames(v)
        if not frames:
            continue
            
        print(f"Benchmarking {os.path.basename(v)} ({total_frames} frames)...", flush=True)
        vid_results = []
        
        for cfg in configs:
            print(f"  Testing {cfg['id']}...", flush=True)
            res = run_benchmark_for_config(frames, cfg['device'], cfg['id'])
            vid_results.append(res)
            
        results[os.path.basename(v)] = {
            "total_frames": total_frames,
            "fps_original": fps,
            "detectors": vid_results
        }

    report = {
        "device_info": dev_info,
        "video_results": results
    }

    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, "w") as f:
        json.dump(report, f, indent=2)
        
    print(f"\nReport written to {OUTPUT_JSON}")

if __name__ == "__main__":
    main()
