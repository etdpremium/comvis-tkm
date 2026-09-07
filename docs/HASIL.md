# tkm-new-fllstck — Hasil Full-Stack 05 Sep 2026

## Alur (otomatis, tanpa upload manual)
MinIO `s3://raw-videos/test_60s.mp4` (dari IMG_7033.MOV VPS, 720p15, 60 dtk)
→ worker (YOLOv8n 8 dominan + COCO person + centroid track + zona point-in-polygon)
→ POST /detections per detik → 1 baris video_batches per segmen
→ upload annotated + raw segmen ke MinIO → dashboard `/` terisi.

## Hasil video #328 (latest done, setelah 3 perbaikan)
- 900 frames, status done, annotated H264 14.5 MB (bisa diputar browser).
- 3 track orang untuk 1 orang asli (fragmentasi centroid; batas jujur algoritma ringan).
  Terbanyak: Orang-1 main bantal 40 dtk (15:29:42-15:30:34), Orang-0 main bantal 24 dtk.
- Durasi kini waktu-VIDEO (maks ≤60 dtk), bukan wall-clock proses CPU.
- Visual terverifikasi: 1 orang, kotak BIRU "orang 1 0.86", kotak HIJAU + label
  (lemari, hp 0.75, bantal 0.41, tas ransel, meja 0.51, kursi 0.78, remote AC 0.30).

## Model
- datasets/tkm8 (280 train / 15 valid), yolov8n 25 epoch CPU: mAP50 0.798, P 0.882, R 0.725.
- models/best.pt (6 MB) + best.onnx (11.7 MB); best.pt juga di MinIO VPS models/tkm8_v1_best.pt.

## Cara lihat
1. http://localhost:8000/ → login guru@tkm.local / guru123 → dashboard 1 role.
2. Pilih video di dropdown → tabel ORANG + inventaris benda + grafik + player annotated.
3. File: http://localhost:9001 (minioadmin/minioadmin) bucket raw-videos / annotated.
4. VPS: hanya MinIO yang disentuh. Buckets: raw-videos, annotated, crops, datasets, models.

## Batasan jujur
- SIAPA = nomor track (nama siswa menunggu fase QR; skema siap).
- mAP50 0.798 sedikit di bawah target 0.80 (validasi kecil, 15 gambar).
- Tracker centroid (bukan ByteTrack); piring lemah (10 sampel train).
