"""
cv-worker/worker.py — CV Worker inference
PRD F2.3. Single source: file .mp4, RTSP, atau S3 dari MinIO.
Per frame:
  1. YOLOv8 predict → 8 kelas
  2. ByteTrackTracker → track_id
  3. POST batch 15-frame / 1-detik ke FastAPI /api/v1/detections
  4. Setiap 60s: tulis annotated.mp4 + raw_segment.mp4 → upload MinIO
  5. PATCH /videos/{id}/annotate ke FastAPI
"""
from __future__ import annotations
import argparse
import logging
import time
import json
import sys
import os
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

import cv2
import httpx
import boto3
from botocore.client import Config
from ultralytics import YOLO

try:
    from trackers import ByteTrackTracker
    HAVE_TRACKERS = True
except ImportError:
    HAVE_TRACKERS = False
    print("WARN: trackers not available, falling back to simple centroid tracker")

# ByteTrack via supervision fallback
try:
    import supervision as sv
    HAVE_SV = True
except ImportError:
    HAVE_SV = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger("tkm.worker")

ROOT = Path(__file__).parent
DEFAULT_MODEL = ROOT / "models" / "best.pt"

# Benda yang BUKAN mainan (wadah/furnitur) — tidak diasosiasikan sebagai "dimainkan".
# Tetap terdeteksi + masuk inventaris, tapi tak pernah jadi MAIN APA.
FURNITURE = {"lemari", "kursi", "meja"}
ZONES = {
    1: [[0.05, 0.1], [0.45, 0.1], [0.45, 0.55], [0.05, 0.55]],   # Rak Material
    2: [[0.55, 0.15], [0.95, 0.15], [0.95, 0.6], [0.55, 0.6]],   # Meja Belajar
    3: [[0.2, 0.65], [0.8, 0.65], [0.8, 0.95], [0.2, 0.95]],     # Area Circle
    4: [[0.4, 0.0], [0.6, 0.0], [0.6, 0.1], [0.4, 0.1]],         # Pintu Masuk
}


class HoldSession:
    """
    Satu sesi "anak pegang barang" — opened saat person_track nempel ke sebuah
    benda (jarak < 250px), closed saat:
      - person_track tidak terlihat >5 detik (tidak ada near_object, atau
        person_track menghilang dari frame), ATAU
      - benda yang sama muncul di ZONA 1 (Rak Material) — dikembalikan ke rak.
    Durasi = close_ts - open_ts (detik). end_reason membantu audit.
    """
    __slots__ = ("person_tid", "object_class", "object_track_id",
                 "open_ts", "last_seen_ts", "end_reason")

    def __init__(self, person_tid: int, object_class: str, object_track_id: int, open_ts: float):
        self.person_tid = person_tid
        self.object_class = object_class
        self.object_track_id = object_track_id
        self.open_ts = open_ts
        self.last_seen_ts = open_ts
        self.end_reason = ""  # "timeout" | "returned_to_rak" | "segment_end"


class HoldSessionTracker:
    """Kelola banyak HoldSession concurrently, satu per (person_tid, object_class)."""

    def __init__(self, return_zone_id: int = 1, return_radius_px: float = 250.0,
                 timeout_sec: float = 5.0, merge_gap_sec: float = 3.0,
                 min_return_age_sec: float = 2.0):
        self.return_zone_id = return_zone_id
        self.return_radius_px = return_radius_px
        self.timeout_sec = timeout_sec
        # Anti-fragmentasi: sesi yang "tutup" tidak langsung di-emit, melainkan
        # ditahan di _pending selama merge_gap_sec. Kalau orang+barang nempel
        # lagi dalam gap itu → sesi DILANJUTKAN (tidak ada emisi ganda).
        # Baru kalau gap terlewati → di-emit sekali dengan close_ts final.
        self.merge_gap_sec = merge_gap_sec
        # Anti salah kaprah: ambil DARI rak terlihat sama dengan kembali KE rak
        # (barang di ZONA 1 + orang dekat). Rak-return hanya boleh tutup sesi
        # yang umurnya >= min_return_age_sec.
        self.min_return_age_sec = min_return_age_sec
        # key = (person_tid, object_class) → HoldSession
        self._open: dict[tuple[int, str], HoldSession] = {}
        self.closed: list[HoldSession] = []  # history untuk emit/log
        # key → (HoldSession, pending_since_ts): tutup-sementara, belum di-emit
        self._pending: dict[tuple[int, str], tuple[HoldSession, float]] = {}

    def update(self, person_rows: list[dict], tracked: list[dict], ts: float) -> list[HoldSession]:
        """
        Dipanggil tiap frame.
        person_rows: hasil deteksi orang (punya bbox, track_id >= 100000, near_objects)
        tracked    : hasil deteksi benda (punya bbox, track_id, class_name, zone_id)
        ts        : timestamp absolut (detik, monotonic) dari video_ts atau time.time()
        Kembalikan list session yang BARU ditutup pada frame ini.
        """
        newly_closed: list[HoldSession] = []
        # 1. Map person_tid → set of (object_class, distance) untuk frame ini
        person_to_near: dict[int, list[tuple[str, int, float]]] = {}
        for pr in person_rows:
            pid = int(pr.get("track_id", -1))
            if pid < 0: continue
            near = pr.get("extra", {}).get("near_objects", []) or []
            near_full: list[tuple[str, int, float]] = []
            for o in tracked:
                if o.get("class_name") in FURNITURE: continue
                if o.get("class_name") in near:
                    ox1, oy1, ox2, oy2 = o["bbox"]
                    pr_xyxy = pr["bbox"]
                    d = (((ox1 + ox2) / 2 - (pr_xyxy[0] + pr_xyxy[2]) / 2) ** 2
                         + ((oy1 + oy2) / 2 - (pr_xyxy[1] + pr_xyxy[3]) / 2) ** 2) ** 0.5
                    near_full.append((o["class_name"], int(o.get("track_id", -1)), d))
            person_to_near[pid] = near_full

        # 0. Pending: lanjutkan yang nempel lagi, emit yang gap-nya terlewati.
        # (active_keys sudah diisi di bawah — blok ini dieksekusi setelahnya.)
        def _settle_pending() -> None:
            for key in list(self._pending.keys()):
                sess, psince = self._pending[key]
                if key in active_keys:
                    sess.last_seen_ts = ts
                    self._open[key] = sess
                    del self._pending[key]
                elif ts - psince > self.merge_gap_sec:
                    newly_closed.append(sess)
                    self.closed.append(sess)
                    del self._pending[key]

        # 2. Update / buka sesi baru
        active_keys: set[tuple[int, str]] = set()
        for pid, near_list in person_to_near.items():
            # hanya 1 sesi per person — pilih benda dengan jarak terdekat
            if not near_list:
                continue
            near_list.sort(key=lambda t: t[2])
            obj_class, obj_tid, _d = near_list[0]
            key = (pid, obj_class)
            active_keys.add(key)
            if key in self._open:
                self._open[key].last_seen_ts = ts
            elif key not in self._pending:
                # key masih pending tapi tidak aktif frame ini → biarkan pending
                self._open[key] = HoldSession(pid, obj_class, obj_tid, ts)

        _settle_pending()

        # 3. Deteksi "returned to rack" — barang dari sesi terbuka muncul di ZONA 1.
        # Syarat umur sesi >= min_return_age_sec (ambil DARI rak bukan kembali).
        for key, sess in list(self._open.items()):
            if ts - sess.open_ts < self.min_return_age_sec:
                continue
            for o in tracked:
                if o.get("class_name") != sess.object_class: continue
                if o.get("zone_id") == self.return_zone_id:
                    # Pastikan ini yang sama orang (jarak < return_radius_px ke person)
                    pr = next((p for p in person_rows if int(p.get("track_id", -1)) == sess.person_tid), None)
                    if pr is not None:
                        d = self._obj_dist_to_person(o, pr)
                        if d <= self.return_radius_px:
                            sess.last_seen_ts = ts
                            sess.end_reason = "returned_to_rak"
                            # Tahan di pending (bukan emit) — bisa lanjut lagi
                            self._pending[key] = (sess, ts)
                            del self._open[key]
                            break
            else:
                continue
            # break out outer if we just closed
            if key not in self._open: continue

        # 4. Timeout — sesi yang tidak aktif di frame ini
        for key, sess in list(self._open.items()):
            if key in active_keys:
                continue
            if ts - sess.last_seen_ts > self.timeout_sec:
                sess.end_reason = "timeout"
                # Tahan di pending (bukan emit) — bisa lanjut lagi
                self._pending[key] = (sess, ts)
                del self._open[key]

        return newly_closed

    def _obj_dist_to_person(self, obj: dict, person: dict) -> float:
        ox1, oy1, ox2, oy2 = obj["bbox"]
        px1, py1, px2, py2 = person["bbox"]
        return (((ox1 + ox2) / 2 - (px1 + px2) / 2) ** 2
                + ((oy1 + oy2) / 2 - (py1 + py2) / 2) ** 2) ** 0.5

    def close_all(self, end_reason: str, ts: float) -> list[HoldSession]:
        """Tutup semua sesi yang masih terbuka/pending (mis. akhir segment).
        Pending di-flush dengan end_reason aslinya (bukan segment_end)."""
        newly_closed: list[HoldSession] = []
        for _key, (sess, _psince) in list(self._pending.items()):
            newly_closed.append(sess)
            self.closed.append(sess)
        self._pending.clear()
        for sess in self._open.values():
            sess.end_reason = end_reason
            newly_closed.append(sess)
            self.closed.append(sess)
        self._open.clear()
        return newly_closed


def zone_of_point(px: float, py: float) -> int | None:
    """Ray-casting point-in-polygon. Kembali id zona atau None."""
    for zid, poly in ZONES.items():
        inside = False
        n = len(poly)
        j = n - 1
        for i in range(n):
            xi, yi = poly[i]
            xj, yj = poly[j]
            if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi + 1e-9) + xi:
                inside = not inside
            j = i
        if inside:
            return zid
    return None


class SimpleCentroidTracker:
    """Fallback tracker jika ByteTrack tidak ada. ID stabil by centroid proximity."""
    def __init__(self, max_dist: float = 80.0):
        self.next_id = 0
        self.objects = {}  # id -> (cx, cy, age)
        self.max_dist = max_dist
        self.lost = {}

    def update(self, detections: list[dict]) -> list[dict]:
        results = []
        used = set()
        for det in detections:
            x1, y1, x2, y2 = det["bbox"]
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            best_id = None
            best_dist = self.max_dist
            for oid, (ox, oy, _) in self.objects.items():
                d = ((cx - ox) ** 2 + (cy - oy) ** 2) ** 0.5
                if d < best_dist and oid not in used:
                    best_dist = d
                    best_id = oid
            if best_id is None:
                best_id = self.next_id
                self.next_id += 1
            self.objects[best_id] = (cx, cy, 0)
            used.add(best_id)
            det2 = dict(det)
            det2["track_id"] = best_id
            results.append(det2)
        return results


class TKMWorker:
    def __init__(
        self,
        model_path: Path,
        api_url: str,
        service_key: str,
        minio_endpoint: str,
        minio_user: str,
        minio_password: str,
        bucket_raw: str,
        bucket_annotated: str,
        segment_sec: int = 60,
        fps_target: int = 15,
        conf: float = 0.25,
        imgsz: int = 640,
        class_id: int | None = None,
        camera_id: str = "1",
    ) -> None:
        self.model_path = Path(model_path)
        log.info(f"Loading YOLO model: {self.model_path}")
        self.model = YOLO(str(self.model_path))
        log.info(f"Classes: {self.model.names}")

        # Model kedua: person COCO (agar SIAPA = manusia beneran, bukan track benda).
        # yolov8n.pt COCO ada di folder proyek; bila hilang, worker tetap jalan objek saja.
        self.person_model = None
        coco = ROOT / "yolov8n.pt"
        try:
            if coco.exists():
                self.person_model = YOLO(str(coco))
                log.info("Person model OK (COCO yolov8n, class 0)")
            else:
                log.warning(f"Person model hilang: {coco} — mode objek saja")
        except Exception as e:
            log.warning(f"Person model gagal load ({e}) — mode objek saja")
        self.person_tracker = SimpleCentroidTracker(max_dist=300.0)

        # Tracker — pakai ByteTrack (supervision) yang lebih stabil dari SimpleCentroid.
        # ByteTrack tahan短暂遮挡 dan re-ID lebih baik lintas frame.
        # supervision 0.30.1: parameter yang valid = track_activation_threshold,
        # lost_track_buffer, minimum_matching_threshold, frame_rate, minimum_consecutive_frames.
        # minimum_iou_threshold TIDAK ada di versi ini.
        try:
            from supervision import ByteTrack as _SVByteTrack
            self.tracker = _SVByteTrack(
                track_activation_threshold=0.25,
                lost_track_buffer=30,
                minimum_matching_threshold=0.8,
                frame_rate=15,
                minimum_consecutive_frames=2,
            )
            self._use_bytetrack = True
            log.info("Using ByteTrack (supervision) — stabil re-ID lintas frame")
        except Exception as e:
            self.tracker = SimpleCentroidTracker()
            self._use_bytetrack = False
            log.warning(f"ByteTrack gagal init ({e}), fallback SimpleCentroidTracker")

        # Tracker untuk orang (COCO) — juga ByteTrack, track_id di-offset +100000 agar
        # tidak tabrakan dengan tracker barang (0..N).
        try:
            from supervision import ByteTrack as _SVByteTrack2
            self._person_bt = _SVByteTrack2(
                track_activation_threshold=0.4,
                lost_track_buffer=30,
                minimum_matching_threshold=0.7,
                frame_rate=15,
                minimum_consecutive_frames=2,
            )
        except Exception:
            self._person_bt = None

        # MinIO
        self.s3 = boto3.client(
            "s3",
            endpoint_url=f"http://{minio_endpoint}",
            aws_access_key_id=minio_user,
            aws_secret_access_key=minio_password,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            region_name="us-east-1",
        )
        self.bucket_raw = bucket_raw
        self.bucket_annotated = bucket_annotated

        self.api_url = api_url.rstrip("/")
        self.service_key = service_key
        self.segment_sec = segment_sec
        self.fps_target = fps_target
        self.conf = conf
        self.imgsz = imgsz
        self.class_id = class_id
        self.camera_id = camera_id

        # Hold-session tracker (PRD F2.3 lanjutan: "Durasi ambil → kembalikan")
        self.hold_tracker = HoldSessionTracker(
            return_zone_id=1,        # Rak Material
            return_radius_px=250.0,  # sama dengan near_object threshold
            timeout_sec=5.0,         # tidak terlihat > 5 detik = dikembalikan
        )
        # Akumulasi sesi yang ditutup selama 1 segment → dikirim ke API saat segment close
        self._segment_hold_sessions: list[dict] = []

    def _ensure_buckets(self) -> None:
        existing = {b["Name"] for b in self.s3.list_buckets().get("Buckets", [])}
        for b in (self.bucket_raw, self.bucket_annotated):
            if b not in existing:
                try:
                    self.s3.create_bucket(Bucket=b)
                    log.info(f"Created bucket: {b}")
                except Exception as e:
                    log.warning(f"create_bucket {b} failed: {e}")

    def _post_detections(self, batch: dict) -> dict:
        try:
            r = httpx.post(
                f"{self.api_url}/api/v1/detections",
                json=batch,
                headers={"X-Service-Key": self.service_key, "Content-Type": "application/json"},
                timeout=10.0,
            )
            return r.json()
        except Exception as e:
            log.error(f"post_detections failed: {e}")
            return {"ok": False, "error": str(e)}

    def _post_hold_sessions(self, video_id: int, sessions: list[dict]) -> str:
        """Kirim hold sessions ke backend. Best-effort: kalau endpoint belum ada,
        fallback ke log saja. Return: 'ok' | 'logged' | 'failed'."""
        if not sessions:
            return "ok"
        payload = {"video_id": video_id, "sessions": sessions}
        try:
            r = httpx.post(
                f"{self.api_url}/api/v1/hold-sessions",
                json=payload,
                headers={"X-Service-Key": self.service_key, "Content-Type": "application/json"},
                timeout=15.0,
            )
            if r.status_code in (200, 201):
                return "ok"
            # Endpoint belum ada (404) atau belum diimplementasi → log saja
            log.info(f"hold-sessions endpoint {r.status_code}, sessions logged only: {sessions[:3]}...")
            return "logged"
        except Exception as e:
            log.warning(f"post_hold_sessions failed: {e}")
            return "failed"

    def _register_annotated(self, video_id: int, key: str, dur: int, frames: int, dets: int) -> dict:
        # Look up by raw_s3_key (worker-generated) — backend auto-created with that key
        try:
            r = httpx.post(
                f"{self.api_url}/api/v1/videos/by-raw-key/annotate",
                params={
                    "raw_s3_key": f"auto/{video_id}",
                    "annotated_s3_key": key,
                    "duration_sec": dur,
                    "frames_total": frames,
                    "detections_count": dets,
                },
                headers={"X-Service-Key": self.service_key},
                timeout=10.0,
            )
            return r.json()
        except Exception as e:
            log.error(f"register_annotated failed: {e}")
            return {"ok": False, "error": str(e)}

    def _register_video(self) -> int | None:
        """Register raw video batch (just to get ID for annotation)."""
        # For PoC: skip register upfront, use timestamp-based ID. Annotate path will create on demand.
        return None

    def _open_source(self, source: str):
        if source.startswith("rtsp://") or source.startswith("http://") or source.startswith("https://"):
            log.info(f"Opening RTSP/HTTP stream: {source}")
            return cv2.VideoCapture(source), "stream"
        if source.startswith("s3://"):
            # Download then open
            bucket, key = source[5:].split("/", 1)
            local = Path(tempfile.gettempdir()) / Path(key).name
            log.info(f"Downloading s3://{bucket}/{key} → {local}")
            self.s3.download_file(bucket, key, str(local))
            return cv2.VideoCapture(str(local)), "file"
        # local file
        log.info(f"Opening local file: {source}")
        return cv2.VideoCapture(source), "file"

    def run(self, source: str, max_segments: int = 1) -> None:
        self._ensure_buckets()
        cap, kind = self._open_source(source)
        if not cap.isOpened():
            log.error(f"Cannot open source: {source}")
            return

        fps_in = cap.get(cv2.CAP_PROP_FPS) or self.fps_target
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        log.info(f"Source: {kind}, FPS_in={fps_in:.1f}, resolution={w}x{h}")

        # Segment state
        seg_idx = 0
        seg_start_frame = 0
        frame_idx = 0
        frames_per_segment = int(fps_in * self.segment_sec)
        # Annotation writer
        out_annot = None
        out_raw = None
        seg_id = int(time.time())

        # State for current segment
        seg_ts_start = datetime.now(timezone.utc)
        seg_annotated_path = Path(tempfile.gettempdir()) / f"tkm_annotated_{seg_id}.mp4"
        seg_raw_path = Path(tempfile.gettempdir()) / f"tkm_raw_{seg_id}.mp4"
        out_annot = cv2.VideoWriter(str(seg_annotated_path), cv2.VideoWriter_fourcc(*"mp4v"), fps_in, (w, h))
        out_raw = cv2.VideoWriter(str(seg_raw_path), cv2.VideoWriter_fourcc(*"mp4v"), fps_in, (w, h))

        # 1-second batch buffer
        batch_buffer: list[dict] = []
        last_send = time.time()
        fps_log: list[float] = []
        total_detections = 0

        try:
            while True:
                t0 = time.time()
                ok, frame = cap.read()
                if not ok:
                    log.info("End of stream")
                    break
                frame_idx += 1
                out_raw.write(frame)
                # WAKTU VIDEO (bukan wall-clock): detik ke-(frame dalam segmen)/fps.
                # Tanpa ini durasi dashboard = lama proses CPU, bukan lama video.
                from datetime import timedelta as _td
                video_ts = (seg_ts_start + _td(seconds=(frame_idx - seg_start_frame - 1) / max(1.0, fps_in))).isoformat()

                # YOLOv8 predict
                results = self.model.predict(
                    source=frame, imgsz=self.imgsz, conf=self.conf, verbose=False
                )
                detections: list[dict] = []
                annotated_frame = frame.copy()
                for r in results:
                    if r.boxes is None:
                        continue
                    for box in r.boxes:
                        cls_id = int(box.cls[0])
                        cls_name = self.model.names.get(cls_id, str(cls_id))
                        conf = float(box.conf[0])
                        xyxy = box.xyxy[0].tolist()
                        detections.append({
                            "track_id": -1,
                            "class_id": cls_id,
                            "class_name": cls_name,
                            "bbox": xyxy,
                            "confidence": conf,
                            "in_zone_main": False,
                            "in_rak": False,
                            "ts": video_ts,
                        })
                        # Draw on annotated
                        x1, y1, x2, y2 = map(int, xyxy)
                        cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        cv2.putText(annotated_frame, f"{cls_name} {conf:.2f}", (x1, max(0, y1-6)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

                # Tracker — ByteTrack (supervision) lebih stabil dari SimpleCentroid
                if self._use_bytetrack and detections:
                    try:
                        import numpy as np
                        xyxy = np.array([d["bbox"] for d in detections], dtype=np.float32)
                        conf = np.array([d["confidence"] for d in detections], dtype=np.float32)
                        cls_id = np.array([d["class_id"] for d in detections], dtype=int)
                        sv_dets = sv.Detections(xyxy=xyxy, confidence=conf, class_id=cls_id)
                        tracked_sv = self.tracker.update_with_tensors(
                            xyxy=xyxy, confidence=conf, class_id=cls_id
                        ) if hasattr(self.tracker, "update_with_tensors") else self.tracker.update(sv_dets)
                        if hasattr(tracked_sv, "tracker_id") and tracked_sv.tracker_id is not None and len(tracked_sv.tracker_id):
                            tracked = []
                            for i, (xyxy_i, tid) in enumerate(zip(tracked_sv.xyxy, tracked_sv.tracker_id)):
                                if i >= len(detections): break
                                d = dict(detections[i])
                                d["track_id"] = int(tid) if tid is not None else -1
                                d["bbox"] = list(map(float, xyxy_i))
                                tracked.append(d)
                            # Append detection yang tidak dapat track_id (tidak ter-track)
                            for i in range(len(tracked_sv.tracker_id), len(detections)):
                                d = dict(detections[i])
                                d["track_id"] = -1
                                tracked.append(d)
                        else:
                            tracked = detections
                    except Exception as e:
                        log.debug(f"ByteTrack failed, falling back: {e}")
                        tracked = SimpleCentroidTracker().update(detections)
                else:
                    tracked = SimpleCentroidTracker().update(detections) if detections else []
                total_detections += len(tracked)

                # Zona: titik tengah-bawah bbox (normalisasi) vs poligon seed DB.
                # Tanpa ini kolom DIMANA selalu kosong.
                for d in tracked:
                    x1, y1, x2, y2 = d["bbox"]
                    px = ((x1 + x2) / 2) / max(1, w)
                    py = y2 / max(1, h)
                    d["zone_id"] = zone_of_point(px, py)
                    d["in_zone_main"] = d["zone_id"] is not None
                    d["in_rak"] = d["zone_id"] == 1

                # --- Deteksi ORANG (model COCO) + asosiasi ke benda terdekat ---
                # Tanpa ini SIAPA = track benda. Orang = kotak BIRU di video.
                person_rows: list[dict] = []
                if self.person_model is not None:
                    try:
                        pr = self.person_model.predict(
                            source=frame, imgsz=self.imgsz, conf=0.4, classes=[0], verbose=False
                        )[0]
                        praw = []
                        if pr.boxes is not None:
                            for box in pr.boxes:
                                pconf = float(box.conf[0])
                                pxyxy = box.xyxy[0].tolist()
                                praw.append({
                                    "track_id": -1, "class_id": 0, "class_name": "person",
                                    "bbox": pxyxy, "confidence": pconf,
                                    "ts": video_ts,
                                })
                        # Track orang (ByteTrack) — track_id di-offset +100000 agar tak tabrakan dgn track benda
                        if praw and self._person_bt is not None:
                            try:
                                import numpy as np
                                pxyxy_arr = np.array([d["bbox"] for d in praw], dtype=np.float32)
                                pconf_arr = np.array([d["confidence"] for d in praw], dtype=np.float32)
                                ptr_sv = self._person_bt.update_with_tensors(
                                    xyxy=pxyxy_arr, confidence=pconf_arr, class_id=np.zeros(len(praw), dtype=int)
                                ) if hasattr(self._person_bt, "update_with_tensors") else self._person_bt.update(
                                    sv.Detections(xyxy=pxyxy_arr, confidence=pconf_arr, class_id=np.zeros(len(praw), dtype=int))
                                )
                                ptr = []
                                for i, (xyxy_i, tid) in enumerate(zip(ptr_sv.xyxy, ptr_sv.tracker_id)):
                                    d = dict(praw[i])
                                    d["track_id"] = int(tid) + 100000 if tid is not None else -1
                                    d["bbox"] = list(map(float, xyxy_i))
                                    ptr.append(d)
                            except Exception as e:
                                log.debug(f"person ByteTrack failed: {e}")
                                ptr = self.person_tracker.update([dict(d) for d in praw])
                                for d in ptr:
                                    d["track_id"] = d["track_id"] + 100000
                        elif praw:
                            ptr = self.person_tracker.update([dict(d) for d in praw])
                            for d in ptr:
                                d["track_id"] = d["track_id"] + 100000
                        else:
                            ptr = []
                        for d in (ptr or []):
                            x1, y1, x2, y2 = d["bbox"]
                            pcx, pcy = (x1 + x2) / 2, y2  # kaki orang
                            d["zone_id"] = zone_of_point(pcx / max(1, w), pcy / max(1, h))
                            # Benda terdekat < 250px dari pusat orang (furnitur dikecualikan)
                            near = []
                            for o in tracked:
                                if o["class_name"] in FURNITURE:
                                    continue
                                ox1, oy1, ox2, oy2 = o["bbox"]
                                dist = (((ox1 + ox2) / 2 - (x1 + x2) / 2) ** 2
                                        + ((oy1 + oy2) / 2 - (y1 + y2) / 2) ** 2) ** 0.5
                                if dist < 250:
                                    near.append(o["class_name"])
                            d["extra"] = {"near_objects": near}
                            person_rows.append(d)
                            tid = d["track_id"] - 100000
                            cv2.rectangle(annotated_frame, (int(x1), int(y1)), (int(x2), int(y2)), (255, 0, 0), 2)
                            cv2.putText(annotated_frame, f"orang {tid} {d['confidence']:.2f}",
                                        (int(x1), max(0, int(y1) - 6)),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
                    except Exception as e:
                        log.debug(f"Person infer gagal frame {frame_idx}: {e}")

                # Add to batch buffer
                # Hold-session update: emit saat ada sesi yang baru ditutup.
                # video_ts di sini adalah ISO string — HoldSessionTracker butuh float
                # (detik dari awal video). Pakai frame_idx / fps_in agar konsisten.
                _ts_float = (frame_idx - seg_start_frame) / max(1.0, fps_in)
                closed_now = self.hold_tracker.update(person_rows, tracked, _ts_float)
                for s in closed_now:
                    self._segment_hold_sessions.append({
                        "person_track_id": s.person_tid,
                        "object_class": s.object_class,
                        "object_track_id": s.object_track_id,
                        "open_ts": s.open_ts,
                        "close_ts": s.last_seen_ts,
                        "duration_sec": round(s.last_seen_ts - s.open_ts, 2),
                        "end_reason": s.end_reason,
                    })

                batch_buffer.append({
                    "frame": frame_idx,
                    "ts": video_ts,
                    "camera_id": self.camera_id,
                    "video_batch_id": seg_id,
                    "detections": tracked + person_rows,
                    "aruco_detections": [],  # ArUco skip dulu sesuai PRD fase ini
                })
                out_annot.write(annotated_frame)

                # Send batch every ~1 sec
                if time.time() - last_send >= 1.0 and batch_buffer:
                    # Take up to 15 frames from buffer
                    to_send = batch_buffer[:15]
                    batch_buffer = batch_buffer[15:]
                    payload = {
                        "frame": to_send[-1]["frame"],
                        "ts": to_send[-1]["ts"],
                        "camera_id": self.camera_id,
                        "video_batch_id": seg_id,
                        "detections": [d for batch in to_send for d in batch["detections"]],
                        "aruco_detections": [a for batch in to_send for a in batch["aruco_detections"]],
                    }
                    self._post_detections(payload)
                    last_send = time.time()

                # Segment complete?
                if frame_idx - seg_start_frame >= frames_per_segment:
                    _ts_float = (frame_idx - seg_start_frame) / max(1.0, fps_in)
                    # Tutup sesi yang masih terbuka (segment end) dengan last seen ts
                    for s in self.hold_tracker.close_all("segment_end", _ts_float):
                        self._segment_hold_sessions.append({
                            "person_track_id": s.person_tid,
                            "object_class": s.object_class,
                            "object_track_id": s.object_track_id,
                            "open_ts": s.open_ts,
                            "close_ts": s.last_seen_ts,
                            "duration_sec": round(s.last_seen_ts - s.open_ts, 2),
                            "end_reason": s.end_reason,
                        })
                    # Release DULU agar moov atom tertulis — tanpa ini file corrupt.
                    out_annot.release()
                    out_raw.release()
                    self._finalize_segment(
                        seg_id, seg_annotated_path, seg_raw_path,
                        frame_idx - seg_start_frame, total_detections,
                        seg_ts_start,
                    )
                    seg_idx += 1
                    if seg_idx >= max_segments:
                        log.info(f"Reached max_segments={max_segments}, stopping")
                        break
                    # Reset for next segment (writer lama sudah di-release + difinalize di atas)
                    seg_id = int(time.time())
                    seg_ts_start = datetime.now(timezone.utc)
                    seg_start_frame = frame_idx
                    seg_annotated_path = Path(tempfile.gettempdir()) / f"tkm_annotated_{seg_id}.mp4"
                    seg_raw_path = Path(tempfile.gettempdir()) / f"tkm_raw_{seg_id}.mp4"
                    out_annot = cv2.VideoWriter(str(seg_annotated_path), cv2.VideoWriter_fourcc(*"mp4v"), fps_in, (w, h))
                    out_raw = cv2.VideoWriter(str(seg_raw_path), cv2.VideoWriter_fourcc(*"mp4v"), fps_in, (w, h))
                    total_detections = 0

                # FPS log
                dt = time.time() - t0
                fps_log.append(1.0 / dt if dt > 0 else 0)
                if len(fps_log) > 30:
                    fps_log = fps_log[-30:]
                if frame_idx % 30 == 0:
                    avg_fps = sum(fps_log) / len(fps_log)
                    log.info(f"frame={frame_idx} avg_fps={avg_fps:.1f} dets_segment={total_detections}")

            # Finalize last segment if frames left (skip bila sudah difinalize di atas)
            if frame_idx - seg_start_frame > 5 and seg_annotated_path.exists():
                _ts_float = (frame_idx - seg_start_frame) / max(1.0, fps_in)
                # Tutup sesi yang masih terbuka (last segment) dengan last seen ts
                for s in self.hold_tracker.close_all("segment_end", _ts_float):
                    self._segment_hold_sessions.append({
                        "person_track_id": s.person_tid,
                        "object_class": s.object_class,
                        "object_track_id": s.object_track_id,
                        "open_ts": s.open_ts,
                        "close_ts": s.last_seen_ts,
                        "duration_sec": round(s.last_seen_ts - s.open_ts, 2),
                        "end_reason": s.end_reason,
                    })
                out_annot.release()
                out_raw.release()
                self._finalize_segment(
                    seg_id, seg_annotated_path, seg_raw_path,
                    frame_idx - seg_start_frame, total_detections,
                    seg_ts_start,
                )

        finally:
            cap.release()
            if out_annot: out_annot.release()
            if out_raw: out_raw.release()

    def _finalize_segment(self, seg_id: int, annotated_path: Path, raw_path: Path, frames: int, detections: int, ts_start: datetime) -> None:
        log.info(f"=== Finalize segment {seg_id}: {frames} frames, {detections} detections ===")
        if not annotated_path.exists() or annotated_path.stat().st_size < 100:
            log.warning(f"Annotated file too small: {annotated_path}")
            return
        ts_str = ts_start.strftime("%Y%m%d_%H%M%S")
        ann_key = f"annotated/{ts_str}_{seg_id}.mp4"
        raw_key = f"raw-videos/segments/{ts_str}_{seg_id}.mp4"
        # STANDAR INDUSTRI: OpenCV mp4v di Linux sering tidak tulis moov atom — Firefox tolak
        # dengan "Cannot parse metadata". Solusi: re-mux via ffmpeg ke H.264 + AAC + faststart
        # (movflags +faststart = moov atom di awal file, playable tanpa download seluruhnya).
        import subprocess as _sp
        ann_up, raw_up = annotated_path, raw_path
        try:
            ann_h264 = annotated_path.with_suffix(".h264.mp4")
            r = _sp.run(
                ["ffmpeg", "-y", "-v", "error",
                 "-i", str(annotated_path),
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                 "-pix_fmt", "yuv420p",                # kompatibilitas browser
                 "-movflags", "+faststart",             # moov di awal file
                 "-an",                                # tidak ada audio di annotated
                 str(ann_h264)],
                capture_output=True, timeout=300
            )
            if r.returncode == 0 and ann_h264.exists() and ann_h264.stat().st_size > 100:
                ann_up = ann_h264
                log.info(f"Annotated re-muxed to H.264 faststart: {ann_h264.stat().st_size} bytes")
            else:
                log.warning(f"ffmpeg annotated gagal (rc={r.returncode}): {r.stderr.decode()[-300:] if r.stderr else 'no stderr'}")
        except FileNotFoundError:
            log.warning("ffmpeg tidak ada di PATH, upload mp4v apa adanya")
        except Exception as e:
            log.warning(f"ffmpeg annotated skip: {e}")
        try:
            self.s3.upload_file(str(ann_up), self.bucket_annotated, ann_key)
            self.s3.upload_file(str(raw_up), self.bucket_raw, raw_key)
            log.info(f"Uploaded: {ann_key} + {raw_key}")
        except Exception as e:
            log.error(f"Upload failed: {e}")
            return
        dur = int(frames / self.fps_target)
        ack = self._register_annotated(seg_id, ann_key, dur, frames, detections)
        log.info(f"Backend ack: {ack}")
        # Kirim hold sessions yang ditutup selama segment ini (best-effort).
        # ack["id"] = VideoBatch.id sebenarnya (bisa beda dari seg_id lokal worker).
        if self._segment_hold_sessions:
            actual_video_id = int(ack.get("id") or seg_id)
            sent = self._post_hold_sessions(actual_video_id, self._segment_hold_sessions)
            log.info(f"Hold sessions: {len(self._segment_hold_sessions)} → API ({sent})")
            self._segment_hold_sessions = []
        # Cleanup local
        for p in (annotated_path, raw_path, annotated_path.with_suffix(".h264.mp4")):
            try: p.unlink()
            except OSError: pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help=".mp4 file, rtsp://, atau s3://bucket/key")
    ap.add_argument("--api", default="http://localhost:8000", help="FastAPI base URL")
    ap.add_argument("--model", default=str(DEFAULT_MODEL), help="YOLOv8 best.pt path")
    ap.add_argument("--service-key", default="tkm-service-key-local")
    ap.add_argument("--minio-endpoint", default="localhost:9000")
    ap.add_argument("--minio-user", default="minioadmin")
    ap.add_argument("--minio-password", default="minioadmin")
    ap.add_argument("--bucket-raw", default="raw-videos")
    ap.add_argument("--bucket-annotated", default="annotated")
    ap.add_argument("--segment-sec", type=int, default=60)
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--max-segments", type=int, default=1, help="stop after N segments (0=until EOF)")
    args = ap.parse_args()

    w = TKMWorker(
        model_path=Path(args.model),
        api_url=args.api,
        service_key=args.service_key,
        minio_endpoint=args.minio_endpoint,
        minio_user=args.minio_user,
        minio_password=args.minio_password,
        bucket_raw=args.bucket_raw,
        bucket_annotated=args.bucket_annotated,
        segment_sec=args.segment_sec,
        fps_target=args.fps,
        conf=args.conf,
        imgsz=args.imgsz,
    )
    w.run(args.source, max_segments=args.max_segments)


if __name__ == "__main__":
    main()
