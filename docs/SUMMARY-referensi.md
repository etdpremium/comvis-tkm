# Ringkasan Referensi GitHub (dibaca sebelum implementasi tkm-new-fllstck)

Sumber clone ada di /home/ubuntu-no-25/tkm-fullstack-build/references/ (tidak di-clone ulang hemat 200MB).

1. ultralytics/ultralytics (8.4.138 terinstall) — Reuse: API YOLO(model.train/predict/export),
   format dataset YOLO + data.yaml (train/val/test, nc, names), early stopping patience,
   augmentasi bawaan. Skip: logika tracker/plots bawaan, CLI cloud. Alasan: engine training utama.
2. roboflow/supervision (0.30.1) — Reuse: Detections, PolygonZone (BOTTOM_CENTER),
   InferenceSlicer opsional objek kecil, annotator BoxAnnotator untuk video terklasifikasi.
   Skip: sv.ByteTrack (deprecated) — diganti trackers. Alasan: wrapper CV standar.
3. roboflow/trackers (2.6.0) — Reuse: ByteTrackTracker.update(detections) untuk track_id stabil.
   Skip: tracker lain (OC-SORT dkk). Alasan: sesuai PRD + HOTA terbaik di POC.
4. tiangolo/fastapi (0.141.1) + starlette 1.6 — Reuse: router, Depends, HTMX templates,
   WebSocket. Catatan: TemplateResponse wajib (request, nama, ctx) — bug 5 Sep karena gaya lama.
   Skip: OAuth2 bawaan kompleks — pakai JWT python-jose sederhana. Alasan: 1 codebase backend+frontend.
5. opencv-contrib-python (5.0) — Reuse: VideoCapture/VideoWriter, cv2.aruco (fase QR nanti).
   Skip: modul CUDA. Alasan: CPU-only VPS/lokal.

Keputusan training dari referensi: yolov8n imgsz 640, batch 16 (RAM 32GB aman),
patience 15-20, augment=True, device cpu, workers 4. Validasi digabung valid+test
karena split Roboflow valid cuma 9 gambar (tidak representatif).
