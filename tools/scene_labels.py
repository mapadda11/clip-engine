"""Linux stand-in for scene_labels.swift (macOS Vision). Same output, one line per image:
"name label:conf label:conf ... | TEXT: line / line"

Scenes: zero-shot OpenCLIP (ViT-B-32, LAION-2B) over a fixed list of GTA scenes. The labels that matter
to the filter use the Mac's names (nightclub, swimwear, lingerie, ...); the rest are there so ordinary
gameplay has somewhere to go. Confidences are softmax shares, so they are calibrated separately from
Vision's (see SCENE_LIMITS in the glue); "nightclub" also needs a neon-lit frame. Text: RapidOCR
("<unread>" if it is missing).
Usage: scene_labels.py IMAGE...
"""
import sys
from pathlib import Path

LABELS = {
    "nightclub": ["a dark nightclub with neon lights and people dancing", "a strip club with a pole dancer",
                  "a club interior with coloured spotlights"],
    "swimwear": ["a woman in a bikini or swimsuit"],
    "lingerie": ["a woman in lingerie or underwear", "a topless dancer"],
    "street": ["a city street with cars in a video game", "a car driving on a road at night"],
    "car_interior": ["the inside of a car while driving"],
    "countryside": ["a forest or countryside road", "a swamp with trees"],
    "shop": ["a shop or warehouse interior", "a gas station"],
    "house": ["a house interior", "a bedroom with a person at a desk"],
    "bar": ["a quiet bar or restaurant"],
    "menu": ["a pause menu in a video game", "a weapon selection menu", "a map screen in a video game",
             "a black screen with large text"],
    "desktop": ["a computer screen with a streaming dashboard"],
    "people_talking": ["people talking outdoors in daylight", "a close-up of a man's face"],
    "action": ["a shootout or police chase", "a car crash"],
}
NEON_MIN = 0.10


def neon_share(path):
    """Share of strongly saturated magenta, blue or red pixels (club lighting)."""
    import cv2
    import numpy as np
    hsv = cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    neon = (s > 150) & (v > 60) & ((h > 100) | (h < 8))
    return float(np.mean(neon))


MODEL, PRETRAINED = "ViT-B-32", "laion2b_s34b_b79k"


_RAPID = None


def ocr(path):
    """On-screen text with RapidOCR (PaddleOCR models on ONNX, Apache-2.0). 22 Nov 2026 calibration:
    Tesseract read only noise from stream frames, so there is no fallback: without RapidOCR every frame
    reports "<unread>" and the glue skips the clip rather than calling it clean."""
    global _RAPID
    try:
        if _RAPID is None:
            from rapidocr_onnxruntime import RapidOCR
            _RAPID = RapidOCR()
        res, _ = _RAPID(path)
    except Exception:  # noqa: BLE001 - missing or broken reader: say so
        return "<unread>"
    return " / ".join(r[1] for r in (res or []) if r[2] >= 0.6 and len(r[1].strip()) >= 3)


def main(paths):
    import open_clip
    import torch
    from PIL import Image

    torch.set_num_threads(4)
    model, _, prep = open_clip.create_model_and_transforms(MODEL, pretrained=PRETRAINED)
    tok = open_clip.get_tokenizer(MODEL)
    names, prompts = [], []
    for label, texts in LABELS.items():
        for t in texts:
            names.append(label)
            prompts.append(t)
    with torch.no_grad():
        tf = model.encode_text(tok(prompts))
        tf /= tf.norm(dim=-1, keepdim=True)
        for path in paths:
            img = prep(Image.open(path).convert("RGB")).unsqueeze(0)
            f = model.encode_image(img)
            f /= f.norm(dim=-1, keepdim=True)
            p = (100.0 * f @ tf.T).softmax(dim=-1)[0].tolist()
            score = {}
            for label, v in zip(names, p):
                score[label] = score.get(label, 0.0) + v
            # CLIP alone called his LED-lit bedroom a nightclub (0.99); clubs are also full of saturated
            # neon. Count "nightclub" only when at least 10% of the frame is dark neon (22 Nov calibration:
            # 5 of 8 club frames kept, 0 of 13 other frames flagged).
            if neon_share(path) < NEON_MIN:
                score["nightclub"] = 0.0
            top = sorted(score.items(), key=lambda kv: -kv[1])
            labs = " ".join("%s:%.2f" % kv for kv in top if kv[1] > 0.1)
            print(Path(path).name, labs, "| TEXT:", ocr(path), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
