"""Camera node: person detection for workers without (or with a shadowed) tag.

Runs on the Raspberry Pi / Jetson next to the camera.  Detects people with a
lightweight YOLO model, maps each person's foot point (bottom-centre of the
box) to site-floor metres with a homography, and writes the list to
`<CSE>/camera_01/detect` (the camera's own AE).  The MEC app fuses these detections with the tag tracks.

    python devices/camera_node.py --source 0                # webcam
    python devices/camera_node.py --source clip.mp4
    python devices/camera_node.py --image bus.jpg --once    # single image, print only

Calibration: four or more (u, v, x, y) pairs - pixel -> floor metres - in
config `camera.calib_points`; mark tape crosses on the floor and click them once.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edgeguard import config                 # noqa: E402
from edgeguard.onem2m import now_ms          # noqa: E402

DEFAULT_WEIGHTS = os.environ.get("EDGEGUARD_YOLO", "yolov8n.pt")


def homography(points):
    import cv2
    pts = np.array(points, dtype=np.float64)
    H, _ = cv2.findHomography(pts[:, :2], pts[:, 2:], 0)
    return H


def to_floor(H, u, v):
    p = H @ np.array([u, v, 1.0])
    return float(p[0] / p[2]), float(p[1] / p[2])


class Detector:
    def __init__(self, weights=DEFAULT_WEIGHTS, conf=0.4, imgsz=640):
        from ultralytics import YOLO
        self.model = YOLO(weights)
        self.conf, self.imgsz = conf, imgsz

    def persons(self, frame):
        """Return [(u_foot, v_foot, conf, (x1, y1, x2, y2))] for class 'person'."""
        res = self.model.predict(frame, conf=self.conf, imgsz=self.imgsz, classes=[0], verbose=False)[0]
        out = []
        for b in res.boxes:
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
            out.append(((x1 + x2) / 2, y2, float(b.conf[0]), (x1, y1, x2, y2)))
        return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--source", default="0", help="camera index or video file")
    ap.add_argument("--image", help="single image instead of a video source")
    ap.add_argument("--once", action="store_true", help="process one frame, print, do not publish")
    ap.add_argument("--hz", type=float, default=5.0)
    ap.add_argument("--weights", default=DEFAULT_WEIGHTS)
    a = ap.parse_args()

    import cv2
    cfg = config.load(a.config)
    cam_cfg = cfg.get("camera", {})
    cam_id = next(iter(config.paths(cfg)["cameras"]))
    path = config.paths(cfg)["cameras"][cam_id]
    H = homography(cam_cfg["calib_points"])
    det = Detector(a.weights, cam_cfg.get("conf", 0.4))
    cse = None if a.once else config.device_client(cfg, cam_id)    # the camera writes as itself (its AE)

    cap = None if a.image else cv2.VideoCapture(int(a.source) if a.source.isdigit() else a.source)
    period = 1.0 / a.hz
    while True:
        t0 = time.time()
        frame = cv2.imread(a.image) if a.image else cap.read()[1]
        if frame is None:
            break
        ti = time.time()
        found = det.persons(frame)
        infer_ms = (time.time() - ti) * 1000
        persons = []
        for u, v, c, box in found:
            x, y = to_floor(H, u, v)
            persons.append({"x": round(x, 2), "y": round(y, 2), "conf": round(c, 2)})
        msg = {"id": cam_id, "kind": "camera", "ts": now_ms(), "persons": persons,
               "infer_ms": round(infer_ms, 1)}
        if a.once:
            print(f"{len(persons)} person(s), inference {infer_ms:.0f} ms")
            for p, (_, _, _, box) in zip(persons, found):
                print(f"  box {tuple(round(b) for b in box)} -> floor ({p['x']:.2f}, {p['y']:.2f}) m conf {p['conf']}")
            break
        try:
            cse.create_cin(path, msg)
        except Exception as e:
            print("publish failed:", e)
        time.sleep(max(0.0, period - (time.time() - t0)))


if __name__ == "__main__":
    main()
