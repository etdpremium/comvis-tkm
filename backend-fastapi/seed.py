"""
backend-fastapi/seed.py — seed initial data: school, class, materials, admin user
PRD F1.2 setup data
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.db import SessionLocal
from app.models import (
    School, ClassRoom, User, UserRole, Material, Zone, Student, Camera,
)
from app.services.auth_service import auth_service


YOLO_8_DOMINAN = ["bantal", "lemari", "kursi", "tas ransel", "hp", "remote AC", "meja", "piring"]
ZONES_DEMO = [
    {"name": "Rak Material", "zone_type": "rak", "color": "#22c55e",
     "polygon": [[0.05, 0.10], [0.45, 0.10], [0.45, 0.55], [0.05, 0.55]]},
    {"name": "Meja Belajar", "zone_type": "meja", "color": "#3b82f6",
     "polygon": [[0.55, 0.15], [0.95, 0.15], [0.95, 0.60], [0.55, 0.60]]},
    {"name": "Area Circle", "zone_type": "circle", "color": "#eab308",
     "polygon": [[0.20, 0.65], [0.80, 0.65], [0.80, 0.95], [0.20, 0.95]]},
    {"name": "Pintu Masuk", "zone_type": "entrance", "color": "#ef4444",
     "polygon": [[0.40, 0.00], [0.60, 0.00], [0.60, 0.10], [0.40, 0.10]]},
]


async def main():
    async with SessionLocal() as session:
        # School + Class
        school = (await session.execute(
            __import__("sqlalchemy").select(School).where(School.name == "TK Montessori Tunas Bangsa")
        )).scalar_one_or_none()
        if school is None:
            school = School(name="TK Montessori Tunas Bangsa", address="Jl. Pendidikan No.1, Jakarta")
            session.add(school)
            await session.flush()

        cls = (await session.execute(
            __import__("sqlalchemy").select(ClassRoom).where(
                ClassRoom.school_id == school.id, ClassRoom.name == "TK A", ClassRoom.grade == "TK A"
            )
        )).scalar_one_or_none()
        if cls is None:
            cls = ClassRoom(name="TK A", grade="TK A", school_id=school.id)
            session.add(cls)
            await session.flush()

        # Admin user
        admin = (await session.execute(
            __import__("sqlalchemy").select(User).where(User.email == "admin@tkm.local")
        )).scalar_one_or_none()
        if admin is None:
            admin = User(
                email="admin@tkm.local",
                hashed_password=auth_service.hash_password("admin123"),
                full_name="Admin TK Montessori",
                role=UserRole.admin,
                is_active=True,
            )
            session.add(admin)

        # Teacher user
        teacher = (await session.execute(
            __import__("sqlalchemy").select(User).where(User.email == "guru@tkm.local")
        )).scalar_one_or_none()
        if teacher is None:
            teacher = User(
                email="guru@tkm.local",
                hashed_password=auth_service.hash_password("guru123"),
                full_name="Ibu Guru",
                role=UserRole.teacher,
                is_active=True,
            )
            session.add(teacher)

        # 8 Materials
        for i, name in enumerate(YOLO_8_DOMINAN):
            m = (await session.execute(
                __import__("sqlalchemy").select(Material).where(Material.name == name)
            )).scalar_one_or_none()
            if m is None:
                session.add(Material(name=name, yolo_class_id=i, category="montessori", description=f"Material {name}"))

        # 4 Zones (per class)
        for z in ZONES_DEMO:
            existing = (await session.execute(
                __import__("sqlalchemy").select(Zone).where(
                    Zone.name == z["name"], Zone.class_id == cls.id
                )
            )).scalar_one_or_none()
            if existing is None:
                session.add(Zone(class_id=cls.id, **z))

        # Students (5 anak TK A)
        student_names = ["Budi", "Ani", "Cici", "Dani", "Eko"]
        for i, name in enumerate(student_names):
            s = (await session.execute(
                __import__("sqlalchemy").select(Student).where(Student.name == name, Student.class_id == cls.id)
            )).scalar_one_or_none()
            if s is None:
                session.add(Student(name=name, nis=f"TK-A-{i+1:03d}", aruco_id=i*2, class_id=cls.id))

        # Camera
        cam = (await session.execute(
            __import__("sqlalchemy").select(Camera).where(Camera.name == "Cam-Kelas-A1", Camera.class_id == cls.id)
        )).scalar_one_or_none()
        if cam is None:
            session.add(Camera(
                name="Cam-Kelas-A1", class_id=cls.id,
                rtsp_url="rtsp://192.168.1.100:554/stream1",
                location="Sudut Timur Kelas A", fps=15, resolution_w=1280, resolution_h=720,
            ))

        await session.commit()
        print(f"OK seed: school={school.id} class={cls.id} users=2 materials=8 zones=4 students=5 camera=1")
        print("Login: admin@tkm.local / admin123   guru@tkm.local / guru123")


if __name__ == "__main__":
    asyncio.run(main())
