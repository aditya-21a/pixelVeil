import urllib.request
import zipfile
import os
import hashlib
import time

def main():
    urls = [
        'https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_s.zip',
        'https://ghproxy.net/https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_s.zip',
        'https://mirror.ghproxy.com/https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_s.zip',
        'https://gh-proxy.com/https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_s.zip'
    ]

    # Use project root assets directory
    this_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(this_dir)
    assets_dir = os.path.join(project_root, 'assets', 'models')
    
    zip_path = os.path.join(assets_dir, 'buffalo_s.zip')
    dest = os.path.join(assets_dir, 'det_500m.onnx')

    os.makedirs(assets_dir, exist_ok=True)
    success = False

    if os.path.exists(dest):
        print(f"Model already exists at {dest}")
        with open(dest, 'rb') as f:
            print('det_500m.onnx SHA256:', hashlib.sha256(f.read()).hexdigest())
        return

    print("Starting download of SCRFD-500M...")
    
    for url in urls:
        for attempt in range(3):
            print(f"Trying {url} (Attempt {attempt+1})")
            try:
                # Some proxies require a standard User-Agent
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                with urllib.request.urlopen(req, timeout=30) as response, open(zip_path, 'wb') as out_file:
                    import shutil
                    shutil.copyfileobj(response, out_file)
                print("Downloaded successfully!")
                success = True
                break
            except Exception as e:
                print(f"Error: {e}")
                time.sleep(2)
        if success:
            break

    if success:
        print("Extracting...")
        with zipfile.ZipFile(zip_path, 'r') as z:
            with z.open('det_500m.onnx') as zf, open(dest, 'wb') as f:
                f.write(zf.read())
        os.remove(zip_path)
        
        with open(dest, 'rb') as f:
            data = f.read()
            print("det_500m.onnx SHA256:", hashlib.sha256(data).hexdigest())
        print("Done!")
    else:
        print("Failed to download from all mirrors. You may need to download manually.")
        print("Manual instructions:")
        print("1. Download: https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_s.zip")
        print("2. Extract the zip file")
        print("3. Copy 'det_500m.onnx' into 'assets/models/'")

if __name__ == "__main__":
    main()
