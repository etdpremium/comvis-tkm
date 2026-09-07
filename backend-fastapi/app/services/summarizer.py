"""
app/services/summarizer.py — gulir event VisionIdEvent jadi Activity + dashboard JSON
PRD F2.4 algoritma:
- focused_work: 1 orang + 1 material > 60s
- free_play: 1 orang + ganti material > 3x dalam 5 menit
- transition: bergerak antar zone tanpa material
- idle: di zone tanpa material > 30s
- social: 2+ orang + material sama dalam 2s
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Iterable
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from ..models import VisionIdEvent, Activity, Student, Material, Zone, BehaviorType, EventType

log = logging.getLogger("tkm.summarizer")


class Summarizer:
    """In-memory rolling state. Per-Activity via DB."""

    def __init__(self, focus_min_sec: int = 60, idle_min_sec: int = 30, freeplay_window_sec: int = 300, freeplay_changes: int = 3) -> None:
        self.focus_min_sec = focus_min_sec
        self.idle_min_sec = idle_min_sec
        self.freeplay_window_sec = freeplay_window_sec
        self.freeplay_changes = freeplay_changes

    async def _material_map(self, session: AsyncSession) -> dict[str, int]:
        rows = (await session.execute(select(Material))).scalars().all()
        return {r.name: r.id for r in rows}

    async def _zone_map(self, session: AsyncSession) -> dict[int, int]:
        rows = (await session.execute(select(Zone))).scalars().all()
        return {r.id: r.id for r in rows}  # identity for now (id is global)

    async def _aruco_to_student(self, session: AsyncSession) -> dict[int, int]:
        rows = (await session.execute(select(Student).where(Student.aruco_id.isnot(None)))).scalars().all()
        return {s.aruco_id: s.id for s in rows}

    async def summarize_window(
        self,
        session: AsyncSession,
        start: datetime,
        end: datetime,
        class_id: int | None = None,
    ) -> list[Activity]:
        """
        Build activities dari vision_id_events dalam [start, end].
        Returns list of NEW Activity (belum ada di DB).
        """
        stmt = select(VisionIdEvent).where(
            VisionIdEvent.ts >= start,
            VisionIdEvent.ts <= end,
        )
        if class_id is not None:
            stmt = stmt.where(VisionIdEvent.class_id == class_id)
        stmt = stmt.order_by(VisionIdEvent.ts)
        events: list[VisionIdEvent] = (await session.execute(stmt)).scalars().all()

        if not events:
            return []

        aruco2student = await self._aruco_to_student(session)
        mat_map = await self._material_map(session)

        # Bucket per (track_id, material_id)
        # state: {track_id: {material_id: [events]}}
        buckets: dict[int, dict[int | None, list[VisionIdEvent]]] = defaultdict(lambda: defaultdict(list))
        for ev in events:
            if ev.event_type == EventType.object_seen and ev.material_id:
                buckets[ev.track_id][ev.material_id].append(ev)
            elif ev.event_type == EventType.aruco_seen and ev.aruco_id in aruco2student:
                ev.student_id = aruco2student[ev.aruco_id]
                buckets[ev.track_id][None].append(ev)  # aruco-only

        activities: list[Activity] = []
        for track_id, mats in buckets.items():
            for mat_id, evs in mats.items():
                if not evs:
                    continue
                # Find student_id from aruco events
                student_id = next((e.student_id for e in evs if e.student_id), None)
                if student_id is None:
                    # fallback: no student, still log as unknown
                    continue
                started = evs[0].ts
                ended = evs[-1].ts
                duration = int((ended - started).total_seconds())
                if duration < 1:
                    continue
                # Heuristic behavior
                behavior = BehaviorType.focused_work if duration >= self.focus_min_sec else BehaviorType.transition
                # Zone (last seen)
                zone_id = next((e.zone_id for e in reversed(evs) if e.zone_id), None)
                # ArUco id
                aruco_id = next((e.aruco_id for e in evs if e.aruco_id), None)
                act = Activity(
                    student_id=student_id,
                    class_id=class_id or (evs[0].class_id or 0),
                    material_id=mat_id,
                    zone_id=zone_id,
                    started_at=started,
                    ended_at=ended,
                    duration_sec=duration,
                    behavior=behavior,
                    aruco_id=aruco_id,
                )
                activities.append(act)

        return activities

    async def compute_today_for_student(
        self, session: AsyncSession, student_id: int, day: datetime | None = None
    ) -> dict:
        day = day or datetime.now(timezone.utc)
        start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)

        stmt = select(Activity).where(
            Activity.student_id == student_id,
            Activity.started_at >= start,
            Activity.started_at < end,
        )
        rows = (await session.execute(stmt)).scalars().all()

        # Material names
        mat_ids = {a.material_id for a in rows if a.material_id}
        mat_names: dict[int, str] = {}
        if mat_ids:
            mats = (await session.execute(select(Material).where(Material.id.in_(mat_ids)))).scalars().all()
            mat_names = {m.id: m.name for m in mats}

        # Behavior minutes
        behavior_min: dict[str, float] = defaultdict(float)
        materials: dict[str, dict] = defaultdict(lambda: {"name": "", "duration_sec": 0, "count": 0})
        zones: dict[str, dict] = defaultdict(lambda: {"name": "", "duration_sec": 0})

        for a in rows:
            behavior_min[a.behavior.value] += a.duration_sec / 60.0
            if a.material_id:
                key = str(a.material_id)
                materials[key]["name"] = mat_names.get(a.material_id, "?")
                materials[key]["duration_sec"] += a.duration_sec
                materials[key]["count"] += 1

        return {
            "student_id": student_id,
            "date": start.date().isoformat(),
            "total_focus_min": round(behavior_min.get("focused_work", 0.0), 2),
            "total_freeplay_min": round(behavior_min.get("free_play", 0.0), 2),
            "total_idle_min": round(behavior_min.get("idle", 0.0), 2),
            "total_social_min": round(behavior_min.get("social", 0.0), 2),
            "total_transition_min": round(behavior_min.get("transition", 0.0), 2),
            "materials": list(materials.values()),
            "zones": list(zones.values()),
            "behavior_breakdown": {k: round(v, 2) for k, v in behavior_min.items()},
        }


summarizer = Summarizer()
