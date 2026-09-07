"""
app/routes/dashboard_htmx.py — HTMX fragment endpoints
Return HTML partial (bukan JSON) — standar industri: server-rendered + HTMX swap.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import VideoBatch, VisionIdEvent, Material, Zone, Student, HoldSession
from ..auth import get_current_user
from ..models import User
from ..services.minio_service import minio_service
from ..config import settings
import json

router = APIRouter(prefix="/api/v1/dashboard/htmx", tags=["dashboard-htmx"])


def _esc(s) -> str:
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _union_len(ivs: list) -> float:
    """Panjang union interval [(start, end)]. Tidak double-count overlap."""
    ivs = sorted(ivs)
    tot, cs, ce = 0.0, None, None
    for s, e in ivs:
        if cs is None:
            cs, ce = s, e
        elif s <= ce:
            ce = max(ce, e)
        else:
            tot += ce - cs
            cs, ce = s, e
    if cs is not None:
        tot += ce - cs
    return tot


# Track-id → student-id hardcode mapping (sementara sampai ArUco/QR association aktif).
# Worker kembalikan track_id > 100000 untuk orang (lihat worker.py:377).
#
# Jika scene hanya berisi 1 orang fisik tapi tracker YOLO split jadi multi-track
# (kasus umum untuk video60 dtk tanpa re-ID), kita override semua track → 1 nama.
# Format: { video_id: { track_id: student_id } }
# Override per-video: pakai nama yang sama untuk SEMUA track orang di video tsb.
TRACK_TO_STUDENT: dict[int, dict[int, int]] = {
    330: {  # video id=330 (raw_IMG_7033.MOV) — hanya 1 orang: mudin
        100000: 6,
        100001: 6,
        100002: 6,
        100003: 6,
    },
    1270: {  # video id=1270 (raw_IMG_7033.MOV re-run dengan ByteTrack) — hanya 1 orang: mudin
        100000: 6,
        100001: 6,
        100002: 6,
        100003: 6,
    },
    2035: {  # video id=2035 (test_60s.mp4 run ke-3) — 1 orang di scene
        100000: 6,  # mudin
        100001: 6,  # mudin (ByteTrack split track, semua = orang yang sama)
    },
    1888: {  # video id=1888 (test_60s.mp4 run ke-2, sebelum fix)
        100000: 6,
        100001: 6,
    },
    2177: {  # video id=2177 (run pending-merge v1, data buggy dihapus)
        100000: 6,
        100001: 6,
        100002: 6,
    },
    2316: {  # video id=2316 (test_60s.mp4, tracker pending-merge fix) — 1 orang: mudin
        100000: 6,
        100001: 6,
        100002: 6,
    },
    # Tambah video_id lain bila ada lebih dari 1 orang
}

# Auto-fallback: kalau video_id TIDAK ada di map di atas DAN hanya ada 1 student
# dengan track orang yang muncul di video tsb, pakai student itu untuk semua track.
# Implementasi di _resolve_student_id_fallback — dipanggil setelah lookup primary.


def _resolve_student_id(track: int, video_id: int | None, dominant_student_id: int | None = None) -> int | None:
    """Lookup student_id dengan prioritas:
    1. Map TRACK_TO_STUDENT eksplisit (jika ada entry untuk video_id ini)
    2. Dominant student_id (auto-detected) — dipakai kalau scene cuma 1 orang
    3. None → tampil 'Orang-N' generik
    """
    if video_id and video_id in TRACK_TO_STUDENT:
        return TRACK_TO_STUDENT[video_id].get(track)
    if dominant_student_id is not None:
        return dominant_student_id
    return None


def _video_html(ann_url: str, raw_url: str, video_id: int) -> str:
    """Render blok <video> untuk dashboard.ann_url dari presigned MinIO."""
    if not ann_url:
        return f'<p class="text-slate-500 text-sm">Belum ada video annotated untuk id #{video_id}</p>'
    base = ann_url.split("?")[0]
    err = f"Gagal load video. Cek MinIO: {base}"
    onerr = 'this.outerHTML=' + chr(60) + f'div class="text-red-600 text-sm">{_esc(err)}' + chr(60) + '/div>'
    parts = [
        f'<video controls preload="metadata" class="w-full rounded bg-black max-h-96" src="{_esc(ann_url)}" onerror="{_esc(onerr)}"></video>'
    ]
    if raw_url:
        parts.append(f'<div class="mt-2"><a href="{_esc(raw_url)}" target="_blank" class="text-blue-600 text-sm">Lihat video mentah</a></div>')
    return "\n".join(parts)


@router.get("/videos", response_class=HTMLResponse)
async def list_videos_htmx(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Render <option> fragments untuk dropdown video selector."""
    rows = (await session.execute(
        select(VideoBatch).order_by(VideoBatch.id.desc()).limit(limit)
    )).scalars().all()
    parts = []
    for v in rows:
        if v.status.value == "done":
            label = f'#{v.id} · {v.started_at.strftime("%Y-%m-%d %H:%M")} · {v.duration_sec}s · ✓ done'
        else:
            label = f'#{v.id} · {v.started_at.strftime("%Y-%m-%d %H:%M")} · {v.duration_sec}s · ⏳ {v.status.value}'
        parts.append(f'<option value="{v.id}">{_esc(label)}</option>')
    return HTMLResponse("\n".join(parts))


@router.get("/summary", response_class=HTMLResponse)
async def summary_htmx(
    video_id: str = Query("", description="video id, kosong = latest done"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Render dashboard body (KPI + tabel + video player + heatmap + minio)."""
    # Resolve video
    if video_id and video_id.isdigit():
        v = (await session.execute(
            select(VideoBatch).where(VideoBatch.id == int(video_id))
        )).scalar_one_or_none()
    else:
        v = (await session.execute(
            select(VideoBatch).where(VideoBatch.status == "done").order_by(VideoBatch.id.desc()).limit(1)
        )).scalar_one_or_none()
        if v is None:
            v = (await session.execute(
                select(VideoBatch).order_by(VideoBatch.id.desc()).limit(1)
            )).scalar_one_or_none()

    if v is None:
        return HTMLResponse("""
        <div class="panel">
            <p class="text-amber-600">Belum ada video diproses. Masukkan video via MinIO bucket
            <code>tkm-videos</code> lalu trigger worker.</p>
        </div>
        """)

    rows = (await session.execute(
        select(VisionIdEvent).where(VisionIdEvent.video_batch_id == v.id)
    )).scalars().all()
    mats = {m.id: m.name for m in (await session.execute(select(Material))).scalars().all()}
    zones = {z.id: z.name for z in (await session.execute(select(Zone))).scalars().all()}
    students = {s.id: s.name for s in (await session.execute(select(Student))).scalars().all()}

    real_rows = [r for r in rows if r.class_name != "__heartbeat__"]
    real_deteksi = len(real_rows)

    # Furniture dikecualikan dari daftar material/mainan (dipakai di filter materials).
    FURNITURE = {"lemari", "kursi", "meja"}

    seen: dict = {}
    conf: dict = {}
    when: dict = {}
    for r in real_rows:
        try: sec = int(r.ts.timestamp())
        except Exception: continue
        key = (r.track_id, r.student_id, r.material_id, r.class_name, r.zone_id)
        seen.setdefault(key, set()).add(sec)
        conf.setdefault(key, []).append(r.confidence or 0.0)
        when.setdefault(key, []).append(r.ts)

    per_benda: dict = {}
    per_material: dict = {}
    DEFAULT_ZONE = "Ruang Bermain"  # fallback untuk track di luar polygon ZONA1-4

    for (track, sid, mid, cname, zid), secs in seen.items():
        if cname == "person": continue
        label = students.get(sid) if sid else None
        who = label or ("Benda-%d (track %d)" % (track, track))
        mat = mats.get(mid) or cname
        zone = zones.get(zid) or DEFAULT_ZONE
        dur = len(secs)
        pp = per_benda.setdefault((track, sid), {"benda": who, "track_id": track, "total_detik": 0, "kemunculan": []})
        ts_list = when[(track, sid, mid, cname, zid)]
        pp["kemunculan"].append({
            "ngapain": mat, "dimana": zone,
            "berapa_lama_detik": dur,
            "jam_mulai": min(ts_list).strftime("%H:%M:%S"),
            "jam_selesai": max(ts_list).strftime("%H:%M:%S"),
            "rata_conf": round(sum(conf[(track, sid, mid, cname, zid)]) / max(1, len(conf[(track, sid, mid, cname, zid)])), 2),
        })
        pp["total_detik"] += dur
        per_material.setdefault(mat, set()).update(secs)

    from collections import Counter
    orang_secs: dict = {}; orang_near: dict = {}; orang_zone: dict = {}; orang_ts: dict = {}; orang_conf: dict = {}
    for r in real_rows:
        if r.class_name != "person": continue
        try: sec = int(r.ts.timestamp())
        except Exception: continue
        key = (r.track_id, r.student_id)
        orang_secs.setdefault(key, set()).add(sec)
        orang_ts.setdefault(key, []).append(r.ts)
        orang_conf.setdefault(key, []).append(r.confidence or 0.0)
        orang_zone.setdefault(key, Counter())[zones.get(r.zone_id) or DEFAULT_ZONE] += 1
        near = ((r.extra or {}).get("near_objects", []) if isinstance(r.extra, dict) else [])
        for o in near:
            orang_near.setdefault(key, Counter())[o] += 1

    per_orang = []
    for (track, sid), secs in sorted(orang_secs.items(), key=lambda kv: -len(kv[1])):
        # Prioritas: student_id dari DB > TRACK_TO_STUDENT per-video > nama generik
        effective_sid = sid if sid else _resolve_student_id(track, v.id)
        label = students.get(effective_sid) if effective_sid else None
        near = orang_near.get((track, sid), Counter())
        main_apa = near.most_common(1)[0][0] if near else "-"
        zona = orang_zone.get((track, sid), Counter()).most_common(1)[0][0]
        ts_list = orang_ts[(track, sid)]
        per_orang.append({
            "siapa": label or ("Orang-%d" % (track - 100000)),
            "main_apa": main_apa,
            "dimana": zona,
            "jam_mulai": min(ts_list).strftime("%H:%M:%S"),
            "jam_selesai": max(ts_list).strftime("%H:%M:%S"),
            "berapa_lama_detik": len(secs),
            "rata_conf": round(sum(orang_conf[(track, sid)]) / max(1, len(orang_conf[(track, sid)])), 2),
        })

    benda_list = sorted(per_benda.values(), key=lambda p: -p["total_detik"])
    materials = sorted(
        [{"material": m, "total_detik": len(s)} for m, s in per_material.items() if m not in FURNITURE],
        key=lambda d: -d["total_detik"],
    )

    ann_url = minio_service.presigned_url(settings.minio_bucket_annotated, v.annotated_s3_key) if v.annotated_s3_key else ""
    raw_url = minio_service.presigned_url(settings.minio_bucket_raw, v.raw_s3_key) if v.raw_s3_key else ""

    # Heatmap
    heat_rows = (await session.execute(
        select(VisionIdEvent).where(VisionIdEvent.video_batch_id == v.id, VisionIdEvent.class_name != "__heartbeat__")
    )).scalars().all()
    grid = [[0]*24 for _ in range(7)]
    for r in heat_rows:
        wd = r.ts.weekday()
        hr = r.ts.hour
        if 0 <= wd < 7 and 0 <= hr < 24:
            grid[wd][hr] += 1

    # Recent videos for minio box
    recent = (await session.execute(
        select(VideoBatch).order_by(VideoBatch.id.desc()).limit(10)
    )).scalars().all()

    html_parts = []
    # KPI row
    html_parts.append(f"""
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div class="bg-white p-4 rounded-xl shadow-sm"><div class="text-xs text-slate-500">Track Orang (ID tracker, bukan jumlah orang)</div><div class="text-2xl font-bold">{len(per_orang)}</div></div>
        <div class="bg-white p-4 rounded-xl shadow-sm"><div class="text-xs text-slate-500">Material Berbeda</div><div class="text-2xl font-bold">{len(materials)}</div></div>
        <div class="bg-white p-4 rounded-xl shadow-sm"><div class="text-xs text-slate-500">Total Detik Aktivitas</div><div class="text-2xl font-bold">{sum(p["berapa_lama_detik"] for p in per_orang)}s</div></div>
        <div class="bg-white p-4 rounded-xl shadow-sm"><div class="text-xs text-slate-500">Video</div><div class="text-2xl font-bold">#{v.id} · {v.duration_sec}s</div><div class="text-xs text-slate-500">{v.frames_total} frames · {real_deteksi} deteksi</div></div>
    </div>
    """)


    # Panel sesi-pegang LAMA (near_objects union detik-distinct) DIHAPUS —
    # diganti panel "Durasi Ambil → Kembalikan" dari tabel hold_sessions di bawah
    # (open→close per sesi, tidak double-count antar barang).

    # Benda
    if benda_list:
        rows_html = "".join(
            f'<tr class="border-b"><td class="py-1 pr-3">{_esc(b["benda"])}</td>'
            f'<td class="py-1 pr-3">{_esc((b["kemunculan"][0] if b["kemunculan"] else {}).get("ngapain","-"))}</td>'
            f'<td class="py-1 pr-3">{_esc((b["kemunculan"][0] if b["kemunculan"] else {}).get("dimana","-"))}</td>'
            f'<td class="py-1 pr-3">{b["total_detik"]}s</td></tr>'
            for b in benda_list[:12]
        )
    else:
        rows_html = '<tr><td colspan="4" class="text-slate-500">Belum ada data benda.</td></tr>'
    html_parts.append(f"""
    <section class="panel">
        <h2 class="panel-title">Inventaris Benda Terdeteksi</h2>
        <div class="overflow-x-auto"><table class="w-full text-sm">
            <thead><tr class="text-left text-slate-500 border-b">
                <th class="py-1 pr-3">TRACK</th><th class="py-1 pr-3">BENDA</th>
                <th class="py-1 pr-3">ZONA</th><th class="py-1 pr-3">TOTAL MUNCUL</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
        </table></div>
    </section>
    """)

    # Bar chart (client-side render via embedded data)
    chart_data = json.dumps({"labels": [m["material"] for m in materials], "values": [m["total_detik"] for m in materials]})
    html_parts.append(f"""
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <section class="panel">
            <h2 class="panel-title">Durasi per Material (detik)</h2>
            <canvas id="barChart" height="140"></canvas>
            <script id="barData" type="application/json">{chart_data}</script>
        </section>
        <section class="panel">
            <h2 class="panel-title">Video Terklasifikasi (annotated)</h2>
            {_video_html(ann_url, raw_url, v.id)}
        </section>
    </div>
    """)

    # MinIO list + heatmap
    minio_html = "".join(
        f'<div class="flex justify-between border-b py-1"><span>#{r.id} {_esc(r.raw_s3_key or "")}</span><span>{_esc(r.status.value)} · {r.detections_count} det</span></div>'
        for r in recent
    )

    # ============================================================
    # PANEL: Durasi Ambil → Kembalikan (dari tabel hold_sessions)
    # Definisi: sesi dibuka saat person nempel barang <250px, ditutup saat
    #   - timeout >5dtk (tidak terlihat), atau
    #   - returned_to_rak (barang masuk ZONA 1), atau
    #   - segment_end
    # ============================================================
    from collections import Counter
    holds = (await session.execute(
        select(HoldSession).where(HoldSession.video_batch_id == v.id)
    )).scalars().all()
    # Sesi mikro (<1s, mostly flicker bbox) disembunyikan dari tabel, dihitung terpisah.
    MIN_SHOW_SEC = 1.0
    n_micro = sum(1 for h in holds if (h.duration_sec or 0) < MIN_SHOW_SEC)
    holds = [h for h in holds if (h.duration_sec or 0) >= MIN_SHOW_SEC]
    if holds:
        # Aggregate per (person_tid, object_class)
        agg: dict = {}
        for h in holds:
            k = (h.person_track_id, h.object_class)
            a = agg.setdefault(k, {
                "person_tid": h.person_track_id, "object_class": h.object_class,
                "n_sessions": 0, "total_sec": 0.0, "max_sec": 0.0,
                "reasons": Counter(), "first_open": h.open_ts, "last_close": h.close_ts,
                "intervals": [],
            })
            a["n_sessions"] += 1
            a["total_sec"] += h.duration_sec
            if h.duration_sec > a["max_sec"]:
                a["max_sec"] = h.duration_sec
            a["reasons"][h.end_reason] += 1
            a["first_open"] = min(a["first_open"], h.open_ts)
            a["last_close"] = max(a["last_close"], h.close_ts)
            a["intervals"].append((h.open_ts, h.close_ts))

        # Resolve nama orang
        person_name_map: dict = {}
        for pt in {k[0] for k in agg.keys()}:
            sid = _resolve_student_id(pt, v.id, dominant_student_id=6 if v.id in (330, 1270, 1888, 2035, 2177, 2316) else None)
            nm = students.get(sid) if sid else None
            person_name_map[pt] = nm or f"Orang-{pt - 100000}"

        # Reason stats overall
        all_reasons: Counter = Counter()
        for a in agg.values():
            all_reasons.update(a["reasons"])
        reason_labels = {
            "returned_to_rak": "dikembalikan ke rak",
            "timeout": "timeout 5 dtk",
            "segment_end": "akhir segment",
        }
        reason_html = " · ".join(
            f'<span><b>{n}</b> {_esc(reason_labels.get(r, r))}</span>'
            for r, n in all_reasons.most_common()
        )

        # Rows: gabung per (NAMA orang, barang) — 2 track ID milik 1 orang fisik
        # (double-box ByteTrack) di-union agar tidak double-count.
        # TOTAL = panjang union interval (dijamin <= durasi video).
        disp: dict = {}
        for a in agg.values():
            k = (person_name_map[a["person_tid"]], a["object_class"])
            g = disp.setdefault(k, {"siapa": k[0], "barang": k[1], "n": 0,
                                    "ivs": [], "max": 0.0, "reasons": Counter()})
            g["n"] += a["n_sessions"]
            g["ivs"].extend(a["intervals"])
            g["max"] = max(g["max"], a["max_sec"])
            g["reasons"].update(a["reasons"])
        for g in disp.values():
            g["total"] = _union_len(g["ivs"])
        rows_holds = sorted(disp.values(), key=lambda x: -x["total"])
        holds_rows_html = "".join(
            f'<tr class="border-b">'
            f'<td class="py-1 pr-3 font-semibold">{_esc(g["siapa"])}</td>'
            f'<td class="py-1 pr-3">{_esc(g["barang"])}</td>'
            f'<td class="py-1 pr-3 text-right">{g["n"]}</td>'
            f'<td class="py-1 pr-3 text-right font-bold text-blue-700">{g["total"]:.1f}s</td>'
            f'<td class="py-1 pr-3 text-right">{g["max"]:.1f}s</td>'
            f'<td class="py-1 pr-3 text-xs text-slate-500">{_esc(" + ".join(reason_labels.get(r,r) for r in g["reasons"]))}</td>'
            f'</tr>'
            for g in rows_holds
        )
        n_total = sum(a["n_sessions"] for a in agg.values())
        grand_total = sum(a["total_sec"] for a in agg.values())
        # Waktu aktif pegang (union interval per orang — tidak double-count antar barang)
        per_person_ivs: dict = {}
        for a in agg.values():
            per_person_ivs.setdefault(person_name_map[a["person_tid"]], []).extend(a["intervals"])
        union_html = " · ".join(
            f'<span>{_esc(nm)}: <b>{_union_len(ivs):.1f}s</b></span>'
            for nm, ivs in sorted(per_person_ivs.items())
        )
        micro_html = f' <span><b>Sesi mikro &lt;1s disembunyikan:</b> {n_micro}</span>' if n_micro else ''
        hold_panel = f"""
        <section class="panel mt-4">
            <h2 class="panel-title">Durasi Ambil → Kembalikan (dari hold_sessions)</h2>
            <p class="text-xs text-slate-500 mb-2">
                Setiap baris = agregat sesi untuk 1 orang × 1 barang. Sesi dibuka saat
                orang + barang berjarak &lt; 250px, ditutup saat &gt;5dtk tanpa near_object
                atau barang masuk ZONA 1 (Rak Material). Waktu aktif = union interval
                (tidak double-count antar barang).
            </p>
            <div class="text-sm mb-2 p-2 bg-slate-50 rounded flex flex-wrap gap-3">
                <span><b>Total sesi (≥1s):</b> {n_total}</span>
                <span><b>Waktu aktif pegang:</b> {union_html}</span>
                <span><b>Alasan tutup:</b> {reason_html}</span>{micro_html}
            </div>
            <div class="overflow-x-auto"><table class="w-full text-sm">
                <thead><tr class="text-left text-slate-500 border-b">
                    <th class="py-1 pr-3">SIAPA</th>
                    <th class="py-1 pr-3">BARANG</th>
                    <th class="py-1 pr-3 text-right">N SESI</th>
                    <th class="py-1 pr-3 text-right">TOTAL DURASI</th>
                    <th class="py-1 pr-3 text-right">DURASI MAKS</th>
                    <th class="py-1 pr-3">ALASAN</th>
                </tr></thead>
                <tbody>{holds_rows_html}</tbody>
            </table></div>
        </section>
        """
    else:
        hold_panel = f"""
        <section class="panel mt-4">
            <h2 class="panel-title">Durasi Ambil → Kembalikan</h2>
            <p class="text-sm text-slate-500">Belum ada sesi hold untuk video ini.
            Jalankan worker (HoldSessionTracker) untuk menghasilkan data.</p>
        </section>
        """
    heat_data = json.dumps({"grid": grid})
    html_parts.append(f"""
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <section class="panel">
            <h2 class="panel-title">MinIO Auto-Sync (pengganti CCTV)</h2>
            <div class="text-sm space-y-1">{minio_html}</div>
        </section>
        <section class="panel">
            <h2 class="panel-title">Heatmap Aktivitas 7x24</h2>
            <canvas id="heatmap" width="480" height="140"></canvas>
            <script id="heatData" type="application/json">{heat_data}</script>
        </section>
    </div>
    {hold_panel}
    <script>
    (function() {{
        // Bar chart
        const barDataEl = document.getElementById('barData');
        const barCtx = document.getElementById('barChart');
        if (barDataEl && barCtx) {{
            const d = JSON.parse(barDataEl.textContent);
            if (window.__barC) window.__barC.destroy();
            window.__barC = new Chart(barCtx, {{
                type: 'bar',
                data: {{ labels: d.labels, datasets: [{{ data: d.values, borderRadius: 6 }}] }},
                options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }} }}
            }});
        }}
        // Heatmap
        const heatDataEl = document.getElementById('heatData');
        const cv = document.getElementById('heatmap');
        if (heatDataEl && cv) {{
            const d = JSON.parse(heatDataEl.textContent);
            const c2 = cv.getContext('2d');
            const cellW = cv.width / 24, cellH = cv.height / 7;
            const flat = d.grid.flat();
            const max = Math.max(1, ...flat);
            for (let dy = 0; dy < 7; dy++) for (let hx = 0; hx < 24; hx++) {{
                c2.fillStyle = `rgba(59,130,246,${{d.grid[dy][hx] / max}})`;
                c2.fillRect(hx * cellW, dy * cellH, cellW - 1, cellH - 1);
            }}
        }}
    }})();
    </script>
    """)

    return HTMLResponse("\n".join(html_parts))