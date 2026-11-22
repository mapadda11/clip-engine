"""Linux stand-in for face_box.swift (macOS Vision). Same output, one line per image:
"name x y w h" for the largest face in pixels (origin top-left), or "name -".

Uses OpenCV's YuNet face detector, the same ONNX model gaming-clip uses to find the facecam.
Usage: face_box.py [--model PATH] [--within x,y,w,h] IMAGE...
--within keeps only faces whose centre is inside that box (the facecam), so a bigger in-game face
can't win; the best-scoring face left is printed.
"""
import os
import sys
from pathlib import Path

import cv2

MODEL = os.environ.get("YUNET_MODEL", "models/face_detection_yunet_2023mar.onnx")


def main(argv):
    model, within = MODEL, None
    while argv[:1] and argv[0] in ("--model", "--within"):
        if argv[0] == "--model":
            model = argv[1]
        else:
            within = [float(v) for v in argv[1].split(",")]
        argv = argv[2:]
    det = None
    for path in argv:
        name = Path(path).name
        img = cv2.imread(path)
        if img is None:
            print(name, "-")
            continue
        h, w = img.shape[:2]
        if det is None:
            det = cv2.FaceDetectorYN.create(model, "", (w, h), 0.6, 0.3, 5000)
        det.setInputSize((w, h))
        _, faces = det.detect(img)
        faces = [] if faces is None else list(faces)
        if within:
            bx, by, bw, bh = within
            faces = [f for f in faces if bx <= f[0] + f[2] / 2 <= bx + bw and by <= f[1] + f[3] / 2 <= by + bh]
        if not faces:
            print(name, "-")
            continue
        x, y, fw, fh = (max(faces, key=lambda f: f[-1]) if within else max(faces, key=lambda f: f[2] * f[3]))[:4]
        # YuNet's box is taller than wide (brow to chin); Vision's is a square. A square of the mean side
        # on the same centre matched Vision within a few pixels on 13 facecam frames (22 Nov 2026).
        side = (fw + fh) / 2
        print(name, int(x + fw / 2 - side / 2), int(y + fh / 2 - side / 2), int(side), int(side))


if __name__ == "__main__":
    main(sys.argv[1:])
