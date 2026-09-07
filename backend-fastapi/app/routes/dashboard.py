"""
app/routes/dashboard.py — Panel 1/4/5 endpoints
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Activity, Student, Material, VisionIdEvent, Zone
from ..auth import get_current_user
from ..models import User
from ..services.summarizer import summarizer

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/video-summary")
async def video_summary(
    video_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Ringkasan 1 video: SIAPA (track/siswa) + DIMANA (zona) + NGAPAIN (material) + BERAPA LAMA (detik).

    Durasi = jumlah detik-distinct tiap (track, material).
    Tanpa ArUco, SIAPA = 'Orang-N (track T)' anonim; setelah QR aktif, nama siswa terisi otomatis.
    """
    from ..models import VideoBatch
    from ..services.minio_service import minio_service
    from ..config import settings

    if video_id is None:
        v = (await session.execute(
            select(VideoBatch).where(VideoBatch.status == "done").order_by(VideoBatch.id.desc()).limit(1)
        )).scalar_one_or_none()
        if v is None:
            v = (await session.execute(
                select(VideoBatch).order_by(VideoBatch.id.desc()).limit(1)
            )).scalar_one_or_none()
    else:
        v = (await session.execute(select(VideoBatch).where(VideoBatch.id == video_id))).scalar_one_or_none()
    if v is None:
        return {"error": "belum ada video diproses"}

    rows = (await session.execute(
        select(VisionIdEvent).where(VisionIdEvent.video_batch_id == v.id)
    )).scalars().all()
    mats = {m.id: m.name for m in (await session.execute(select(Material))).scalars().all()}
    zones = {z.id: z.name for z in (await session.execute(select(Zone))).scalars().all()}
    students = {s.id: s.name for s in (await session.execute(select(Student))).scalars().all()}

    # Hitung deteksi real (exclude heartbeat) untuk KPI akurasi
    real_rows = [r for r in rows if r.class_name != "__heartbeat__"]
    real_deteksi = len(real_rows)

    # (track, material, zone) -> set(detikk)
    seen: dict[tuple, set[int]] = {}
    conf: dict[tuple, list[float]] = {}
    when: dict[tuple, list] = {}
    for r in rows:
        if r.class_name == "__heartbeat__":
            continue
        try:
            sec = int(r.ts.timestamp())
        except Exception:
            continue
        key = (r.track_id, r.student_id, r.material_id, r.class_name, r.zone_id)
        seen.setdefault(key, set()).add(sec)
        conf.setdefault(key, []).append(r.confidence or 0.0)
        when.setdefault(key, []).append(r.ts)

    per_benda: dict[tuple, dict] = {}
    per_material: dict[str, set[int]] = {}
    for (track, sid, mid, cname, zid), secs in seen.items():
        if cname == "person":
            continue  # orang dihitung terpisah di bawah
        label = students.get(sid) if sid else None
        who = label or ("Benda-%d (track %d)" % (track, track))
        mat = mats.get(mid) or cname
        zone = zones.get(zid) or "-"
        dur = len(secs)
        pp = per_benda.setdefault((track, sid), {"benda": who, "track_id": track, "total_detik": 0, "kemunculan": []})
        ts_list = when[(track, sid, mid, cname, zid)]
        t0 = min(ts_list)
        t1 = max(ts_list)
        pp["kemunculan"].append({
            "ngapain": mat, "dimana": zone,
            "berapa_lama_detik": dur,
            "jam_mulai": t0.strftime("%H:%M:%S"),
            "jam_selesai": t1.strftime("%H:%M:%S"),
            "rata_conf": round(sum(conf[(track, sid, mid, cname, zid)]) / max(1, len(conf[(track, sid, mid, cname, zid)])), 2),
        })
        pp["total_detik"] += dur
        per_material.setdefault(mat, set()).update(secs)

    # ORANG: track person + benda yang dimainkan (asosiasi <250px dari worker).
    from collections import Counter
    orang_secs: dict[tuple, set[int]] = {}
    orang_near: dict[tuple, Counter] = {}
    orang_zone: dict[tuple, Counter] = {}
    orang_ts: dict[tuple, list] = {}
    orang_conf: dict[tuple, list[float]] = {}
    for r in rows:
        if r.class_name != "person":
            continue
        try:
            sec = int(r.ts.timestamp())
        except Exception:
            continue
        key = (r.track_id, r.student_id)
        orang_secs.setdefault(key, set()).add(sec)
        orang_ts.setdefault(key, []).append(r.ts)
        orang_conf.setdefault(key, []).append(r.confidence or 0.0)
        zid = r.zone_id
        orang_zone.setdefault(key, Counter())[zones.get(zid) or "-"] += 1
        near = ((r.extra or {}).get("near_objects", []) if isinstance(r.extra, dict) else [])
        for o in near:
            orang_near.setdefault(key, Counter())[o] += 1

    per_orang = []
    for (track, sid), secs in sorted(orang_secs.items(), key=lambda kv: -len(kv[1])):
        label = students.get(sid) if sid else None
        near = orang_near.get((track, sid), Counter())
        main_apa = near.most_common(1)[0][0] if near else "-"
        zona = orang_zone.get((track, sid), Counter()).most_common(1)[0][0]
        ts_list = orang_ts[(track, sid)]
        per_orang.append({
            "siapa": label or ("Orang-%d" % (track - 100000)),
            "track_id": track,
            "main_apa": main_apa,
            "dimana": zona,
            "jam_mulai": min(ts_list).strftime("%H:%M:%S"),
            "jam_selesai": max(ts_list).strftime("%H:%M:%S"),
            "berapa_lama_detik": len(secs),
            "rata_conf": round(sum(orang_conf[(track, sid)]) / max(1, len(orang_conf[(track, sid)])), 2),
        })

    benda_list = sorted(per_benda.values(), key=lambda p: -p["total_detik"])
    materials = sorted(
        [{"material": m, "total_detik": len(s)} for m, s in per_material.items() if m not in ("lemari", "kursi", "meja")],
        key=lambda d: -d["total_detik"],
    )
    return {
        "video": {
            "id": v.id, "durasi_detik": v.duration_sec, "frames": v.frames_total,
            "total_deteksi": real_deteksi, "status": v.status.value,
            "annotated_url": minio_service.presigned_url(settings.minio_bucket_annotated, v.annotated_s3_key) if v.annotated_s3_key else "",
            "raw_url": minio_service.presigned_url(settings.minio_bucket_raw, v.raw_s3_key) if v.raw_s3_key else "",
        },
        "kpi": {
            "orang_terdeteksi": len(per_orang),
            "material_berbeda": len(materials),
            "total_detik_aktivitas": sum(p["berapa_lama_detik"] for p in per_orang),
        },
        "per_orang": per_orang,
        "per_benda": benda_list,
        "per_material": materials,
    }


@router.get("/today")
async def today_for_student(
    student_id: int = Query(...),
    day: datetime | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    s = (await session.execute(select(Student).where(Student.id == student_id))).scalar_one_or_none()
    if not s:
        return {"error": "student not found", "student_id": student_id}
    return await summarizer.compute_today_for_student(session, student_id, day)


@router.get("/week")
async def week_overview(
    class_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    days = [(today - timedelta(days=i)) for i in range(6, -1, -1)]
    out = []
    for d in days:
        end = d + timedelta(days=1)
        stmt = select(Activity).where(Activity.started_at >= d, Activity.started_at < end)
        if class_id is not None:
            stmt = stmt.where(Activity.class_id == class_id)
        rows = (await session.execute(stmt)).scalars().all()
        focus = sum(r.duration_sec for r in rows if r.behavior.value == "focused_work") / 60
        free = sum(r.duration_sec for r in rows if r.behavior.value == "free_play") / 60
        out.append({
            "date": d.date().isoformat(),
            "total_focus_min": round(focus, 2),
            "total_freeplay_min": round(free, 2),
            "students_count": len({r.student_id for r in rows}),
        })
    return {"class_id": class_id, "days": out}


@router.get("/heatmap")
async def heatmap_24x7(
    class_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """7×24 grid: rows=day_of_week, cols=hour, value=total activity seconds."""
    stmt = select(Activity)
    if class_id is not None:
        stmt = stmt.where(Activity.class_id == class_id)
    rows = (await session.execute(stmt)).scalars().all()
    grid = [[0] * 24 for _ in range(7)]
    for a in rows:
        dow = a.started_at.weekday()
        h = a.started_at.hour
        grid[dow][h] += a.duration_sec
    return {"class_id": class_id, "grid_seconds": grid}


@router.get("/videos")
async def recent_videos(
    class_id: int | None = None,
    limit: int = Query(10, le=50),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    from ..models import VideoBatch
    stmt = select(VideoBatch)
    if class_id is not None:
        stmt = stmt.where(VideoBatch.class_id == class_id)
    stmt = stmt.order_by(VideoBatch.started_at.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    from ..services.minio_service import minio_service
    from ..config import settings
    out = []
    for v in rows:
        ann_url = ""
        raw_url = ""
        if v.annotated_s3_key:
            ann_url = minio_service.presigned_url(settings.minio_bucket_annotated, v.annotated_s3_key)
        if v.raw_s3_key:
            raw_url = minio_service.presigned_url(settings.minio_bucket_raw, v.raw_s3_key)
        out.append({
            "id": v.id,
            "started_at": v.started_at.isoformat(),
            "duration_sec": v.duration_sec,
            "fps": v.fps,
            "frames_total": v.frames_total,
            "detections_count": v.detections_count,
            "status": v.status.value,
            "raw_s3_key": v.raw_s3_key,
            "annotated_s3_key": v.annotated_s3_key,
            "annotated_url": ann_url,
            "raw_url": raw_url,
        })
    return {"videos": out}
