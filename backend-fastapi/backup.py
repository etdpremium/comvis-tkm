"""
backend-fastapi/backup.py — pg_dump + MinIO mirror (PRD F4.5)
Jalankan via cron harian.
"""
from __future__ import annotations
import os
import sys
import subprocess
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.services.minio_service import minio_service
from app.config import settings


def main():
    today = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(f"/tmp/tkm-backups/{today}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. pg_dump
    dump_path = out_dir / "tkm.sql"
    env = os.environ.copy()
    env["PGPASSWORD"] = settings.postgres_password
    cmd = [
        "pg_dump",
        "-h", settings.postgres_host,
        "-U", settings.postgres_user,
        "-d", settings.postgres_db,
        "-F", "c",
        "-f", str(dump_path),
    ]
    print(f"=== Backup run {today} ===")
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            print(f"  pg_dump OK: {dump_path} ({dump_path.stat().st_size/1024:.1f} KB)")
            # upload to MinIO
            key = f"backups/postgres/{today}/tkm.sql"
            minio_service.upload_file(dump_path, settings.minio_bucket_raw, key)
            print(f"  uploaded → {key}")
        else:
            print(f"  pg_dump FAIL: {r.stderr[:200]}")
    except FileNotFoundError:
        print("  pg_dump not installed — skip Postgres backup (install postgresql-client)")
    except Exception as e:
        print(f"  ERR: {e}")

    # 2. Cleanup local
    try:
        dump_path.unlink()
        out_dir.rmdir()
    except OSError:
        pass


if __name__ == "__main__":
    main()
