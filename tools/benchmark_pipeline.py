import os
import sys
import argparse

# Ensure we can import core modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.video_pipeline import process_video

def main():
    parser = argparse.ArgumentParser(description="Benchmark PixelVeil Video Pipeline")
    parser.add_argument("--video", type=str, default="tests/sample_videos/instagram_multi_faces.mp4", help="Path to input video")
    parser.add_argument("--mode", type=str, default="blur", choices=["blur", "fake_data"], help="Redaction mode")
    parser.add_argument("--device", type=str, default="auto", choices=["auto", "cuda", "cpu"], help="Compute device")
    parser.add_argument("--ocr-rate", type=int, default=1, help="OCR sample rate")
    parser.add_argument("--face-redaction-method", type=str, default="blur", choices=["blur", "pixelate"], help="Face redaction method")
    args = parser.parse_args()

    input_path = args.video
    if not os.path.exists(input_path):
        print(f"Error: Input video not found at {input_path}")
        sys.exit(1)

    output_path = "tests/sample_videos/benchmark_output.mp4"
    
    print(f"Benchmarking {input_path} (mode={args.mode}, device={args.device}, ocr_rate={args.ocr_rate}, face_redaction_method={args.face_redaction_method})")
    
    try:
        summary = process_video(
            input_path=input_path,
            output_path=output_path,
            mode=args.mode,
            ocr_sample_rate=args.ocr_rate,
            compute_device=args.device,
            face_redaction_method=args.face_redaction_method
        )
    except Exception as e:
        print(f"Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
        
    frames = summary["frames_processed"]
    if frames == 0:
        print("No frames processed.")
        sys.exit(1)
        
    t = summary["timing"]
    total = t["total_runtime"]
    
    print("\n==================================================")
    print("PIXELVEIL BENCHMARK REPORT")
    print("==================================================")
    print(f"Input frames: {frames}")
    print(f"Total runtime: {total:.2f}s")
    print(f"Overall FPS: {frames / total:.2f} FPS")
    print("\nStage                  Total (s)   ms/frame      %")
    print("--------------------------------------------------")
    
    stages = [
        ("Decode", t["decode"]),
        ("Face Detect", t["face_detect"]),
        ("Face Track", t["face_track"]),
        ("OCR", t["ocr"]),
        ("PII Match", t["pii_match"]),
        ("Redact Faces", t["redact_faces"]),
        ("Redact PII", t["redact_pii"]),
        ("Redact Zones", t["redact_zones"]),
        ("Encode", t["encode"]),
        ("Audio Mux", t["audio_mux"]),
    ]
    
    accounted_time = sum(time for _, time in stages)
    other_time = total - accounted_time
    stages.append(("Other", max(0, other_time)))
    
    for name, stage_time in stages:
        ms_per_frame = (stage_time / frames) * 1000
        percent = (stage_time / total) * 100 if total > 0 else 0
        print(f"{name:<20} {stage_time:>7.2f}s    {ms_per_frame:>7.1f}ms   {percent:>5.1f}%")
        
    print("\nDevice Info:")
    print(f"Device: {summary['device']} ({summary['gpu_name']})")
    print(f"Face Provider: {summary['face_detector_provider']}")
    print(f"OCR Provider: {summary['ocr_provider']}")
    
    if os.path.exists(output_path):
        os.remove(output_path)

if __name__ == "__main__":
    main()
