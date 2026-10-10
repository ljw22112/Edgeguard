# Third-party software

EdgeGuard's own code is MIT-licensed (`LICENSE`). It uses or builds on the following projects; their
licenses apply to them, not to EdgeGuard.

| Component | Used for | License | How it is used |
|---|---|---|---|
| [Mobius](https://github.com/IoTKETI/Mobius) (KETI) | oneM2M IN-CSE | BSD-3-Clause | Built into the `edgeguard-mobius` image at a pinned commit (`deploy/mobius/`) |
| [ACME oneM2M CSE](https://github.com/ankraft/ACME-oneM2M-CSE) | oneM2M CSE for local demo / interop tests | BSD-3-Clause | Downloaded by `scripts/run_local_demo.sh`; `docs/acme-content-type.patch` is our fix |
| [AdvantEDGE](https://github.com/InterDigitalInc/AdvantEDGE) (InterDigital) | Self-hosted ETSI MEC Sandbox | Apache-2.0 | Cloned and built by `deploy/sandbox-host/install-advantedge.sh`; not redistributed |
| [Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics) | Optional camera node (`devices/camera_node.py`) | **AGPL-3.0** | Optional dependency (`requirements-ml.txt`), not in the default images. Distributing a product that includes it requires AGPL compliance or an Ultralytics enterprise license |
| PyTorch, OpenCV | LSTM training / camera node | BSD-style / Apache-2.0 | Optional (`requirements-ml.txt`) |
| FastAPI, Uvicorn, NumPy, Requests, PyYAML | MEC app and tools | MIT / BSD / Apache-2.0 | `requirements.txt` |
| arduino-dw1000, ArduinoJson, ESP32 Arduino core | Firmware | Apache-2.0 / MIT / LGPL-2.1 | Build-time libraries of the sketches in `firmware/` |
| Prometheus, Grafana | Optional monitoring profile | Apache-2.0 / AGPL-3.0 | Official images pulled unmodified by `deploy/docker-compose.yml` |
