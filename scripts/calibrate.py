"""Step 1 calibration: run the Linux face and scene options on frames at given times of one VOD.
Prints text only (labels, boxes, timings); frames stay on the runner.
Usage: calibrate.py VOD_URL "t1 t2 ..."
"""
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from feasibility import kick_source  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FR = Path("frames")


def club_look(path):
    """Option B for scenes: plain OpenCV. Share of dark, strongly saturated magenta/blue/red pixels."""
    import cv2
    import numpy as np
    hsv = cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    neon = (s > 150) & (v > 60) & (((h > 120) & (h < 175)) | (h < 8) | ((h > 100) & (h <= 120)))
    return float(np.mean(neon)), float(np.mean(v))


def mediapipe_faces(paths):
    try:
        import cv2
        import mediapipe as mp
    except ImportError as e:
        return {p: "mediapipe missing: %s" % e for p in paths}
    out = {}
    with mp.solutions.face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.5) as fd:
        for p in paths:
            img = cv2.imread(p)
            r = fd.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            if not r.detections:
                out[p] = "-"
                continue
            H, W = img.shape[:2]
            b = max(r.detections, key=lambda d: d.location_data.relative_bounding_box.width).location_data.relative_bounding_box
            out[p] = "%d %d %d %d" % (b.xmin * W, b.ymin * H, b.width * W, b.height * H)
    return out


def main(url, times):
    src, how = kick_source(url)
    print("source via", how)
    FR.mkdir(exist_ok=True)
    procs = [subprocess.Popen(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", t, "-i", src, "-frames:v", "1",
                               "-vf", "scale=1280:-2", str(FR / ("t%s.jpg" % t))]) for t in times.split()]
    for p in procs:
        p.wait()
    paths = sorted((str(p) for p in FR.glob("t*.jpg")), key=lambda s: int(Path(s).stem[1:]))
    print("frames", len(paths))

    t = time.time()
    print("\n## YuNet faces")
    subprocess.run([sys.executable, ROOT / "tools" / "face_box.py", "--model", "models/face_detection_yunet_2023mar.onnx", *paths])
    print("yunet seconds %.1f" % (time.time() - t))

    t = time.time()
    print("\n## MediaPipe faces")
    for p, v in mediapipe_faces(paths).items():
        print(Path(p).name, v)
    print("mediapipe seconds %.1f" % (time.time() - t))

    t = time.time()
    print("\n## OpenCLIP scenes + Tesseract text")
    subprocess.run([sys.executable, ROOT / "tools" / "scene_labels.py", *paths])
    print("clip+ocr seconds %.1f" % (time.time() - t))

    print("\n## OpenCV club look (neon share, mean brightness)")
    for p in paths:
        n, v = club_look(p)
        print(Path(p).name, "%.3f %.0f" % (n, v))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
