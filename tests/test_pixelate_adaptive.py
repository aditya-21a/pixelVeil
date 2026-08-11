import os
import sys
import cv2
import numpy as np

# Ensure we can import core modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.redactor import redact_face

def main():
    test_image_path = "tests/assets/test_pixelate.png"
    if not os.path.exists(test_image_path):
        # Create a dummy test image if it doesn't exist
        print(f"Test image {test_image_path} not found. Creating a synthetic one.")
        os.makedirs(os.path.dirname(test_image_path), exist_ok=True)
        img = np.zeros((800, 800, 3), dtype=np.uint8)
        img[:] = (200, 200, 200) # light gray background
        cv2.imwrite(test_image_path, img)
    
    img = cv2.imread(test_image_path)
    
    face_sizes = [
        ("small_face", 20),
        ("medium_face", 60),
        ("large_face", 160),
        ("extra_large_face", 300)
    ]
    
    output_dir = "tests/assets/outputs"
    os.makedirs(output_dir, exist_ok=True)
    
    print("\n--- Adaptive Pixelation Sweep ---")
    
    for name, size in face_sizes:
        frame = img.copy()
        h, w = frame.shape[:2]
        
        # Draw a synthetic "face" in the center before redaction to see the effect
        cx, cy = w // 2, h // 2
        # face bounding box
        bbox = (cx - size // 2, cy - size // 2, size, size)
        
        # Just drawing some facial features so we can visually inspect
        cv2.circle(frame, (cx - size//4, cy - size//4), max(1, size//10), (0, 0, 0), -1) # left eye
        cv2.circle(frame, (cx + size//4, cy - size//4), max(1, size//10), (0, 0, 0), -1) # right eye
        cv2.ellipse(frame, (cx, cy + size//4), (size//4, size//8), 0, 0, 180, (0, 0, 255), -1) # mouth
        
        print(f"\nProcessing {name} (bbox size: {size}x{size})...")
        redact_face(frame, bbox, method="pixelate")
        
        out_path = os.path.join(output_dir, f"{name}.png")
        cv2.imwrite(out_path, frame)
        print(f"Saved to {out_path}")

if __name__ == "__main__":
    main()
