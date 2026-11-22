"""Linux stand-in for face_box.swift (macOS Vision). Same output, one line per image:
"name x y w h" for the largest face in pixels (origin top-left), or "name -".

Uses OpenCV's YuNet face detector, the same ONNX model gaming-clip uses to find the facecam.
Usage: face_box.py [--model PATH] IMAGE...
"""
import os
import sys
from pathlib import Path

import cv2

MODEL = os.environ.get("YUNET_MODEL", "models/face_detection_yunet_2023mar.onnx")


def main(argv):
    model = MODEL
    if argv[:1] == ["--model"]:
        model, argv = argv[1], argv[2:]
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
        if faces is None or not len(faces):
            print(name, "-")
            continue
        x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])[:4]
        print(name, int(x), int(y), int(fw), int(fh))


if __name__ == "__main__":
    main(sys.argv[1:])
