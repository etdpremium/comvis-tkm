"""Training YOLOv8n 8 dominan — CPU, RAM 32GB (batch 16, workers 4)."""
import time
from pathlib import Path
from ultralytics import YOLO

ROOT = Path("/home/ubuntu-no-25/tkm-new-fllstck")
DATA = ROOT / "datasets" / "tkm8" / "tkm_8.yaml"

model = YOLO("yolov8n.pt")
t0 = time.time()
model.train(
    data=str(DATA),
    epochs=25,
    imgsz=640,
    batch=32,
    patience=8,
    freeze=10,
    project=str(ROOT / "runs"),
    name="tkm8_v1",
    device="cpu",
    workers=1,
    augment=True,
    exist_ok=True,
    verbose=True,
    cache=False,
)
print("TRAIN_MINUTES=%.1f" % ((time.time() - t0) / 60))

src = ROOT / "runs" / "tkm8_v1" / "weights" / "best.pt"
if src.exists():
    dst = ROOT / "models" / "best.pt"
    dst.write_bytes(src.read_bytes())
    print("COPIED best.pt %.2f MB" % (dst.stat().st_size / 1024 / 1024))

print("=== Export ONNX ===")
model.export(format="onnx", imgsz=640, simplify=True)
onnx_src = ROOT / "runs" / "tkm8_v1" / "weights" / "best.onnx"
if onnx_src.exists():
    dst = ROOT / "models" / "best.onnx"
    dst.write_bytes(onnx_src.read_bytes())
    print("COPIED best.onnx %.2f MB" % (dst.stat().st_size / 1024 / 1024))
