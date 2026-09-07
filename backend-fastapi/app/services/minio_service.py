"""
app/services/minio_service.py — MinIO (S3-compatible) client + presigned URL
PRD F1.2. menggunakan boto3.
"""
from __future__ import annotations
import logging
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from pathlib import Path
from ..config import settings

log = logging.getLogger("tkm.minio")


class MinIOService:
    def __init__(self) -> None:
        self.endpoint = settings.minio_endpoint
        self.user = settings.minio_root_user
        self.password = settings.minio_root_password
        self._client = None
        self._ensure_buckets()

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=f"http{'s' if settings.minio_secure else ''}://{self.endpoint}",
                aws_access_key_id=self.user,
                aws_secret_access_key=self.password,
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
                region_name="us-east-1",
            )
        return self._client

    def _ensure_buckets(self) -> None:
        """Create buckets if missing. Tolerant of connection errors (VPS might be down)."""
        try:
            existing = {b["Name"] for b in self.client.list_buckets().get("Buckets", [])}
            for bucket in (settings.minio_bucket_raw, settings.minio_bucket_annotated, settings.minio_bucket_models, settings.minio_bucket_crops):
                if bucket not in existing:
                    self.client.create_bucket(Bucket=bucket)
                    log.info("Created MinIO bucket: %s", bucket)
        except Exception as e:
            log.warning("MinIO init failed (will retry on first use): %s", e)

    def upload_file(self, local_path: str | Path, bucket: str, key: str) -> str:
        self.client.upload_file(str(local_path), bucket, key)
        return key

    def upload_bytes(self, data: bytes, bucket: str, key: str, content_type: str = "application/octet-stream") -> str:
        self.client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
        return key

    def presigned_url(self, bucket: str, key: str, expires: int | None = None) -> str:
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expires or settings.minio_presign_expiry_sec,
            )
        except ClientError as e:
            log.error("presign failed: %s", e)
            return ""

    def list_objects(self, bucket: str, prefix: str = "", limit: int = 100) -> list[dict]:
        try:
            resp = self.client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=limit)
            return [
                {"key": o["Key"], "size": o.get("Size", 0), "modified": str(o.get("LastModified", ""))}
                for o in resp.get("Contents", [])
            ]
        except Exception as e:
            log.warning("list_objects failed: %s", e)
            return []

    def delete_object(self, bucket: str, key: str) -> bool:
        try:
            self.client.delete_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False


minio_service = MinIOService()
