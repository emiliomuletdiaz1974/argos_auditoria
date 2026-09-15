"""S3-compatible backend: paginated listing and ranged reads of the first block (ARG-017)."""

from collections.abc import Iterator, Mapping
from typing import Any

import boto3
from botocore.config import Config

from . import FileEntry, normalise_prefix


class S3Backend:
    def __init__(self, credentials: Mapping[str, str]) -> None:
        self._bucket = credentials["bucket"]
        self._client = boto3.client(
            "s3",
            endpoint_url=credentials["endpoint_url"],
            aws_access_key_id=credentials["access_key"],
            aws_secret_access_key=credentials["secret_key"],
            region_name=credentials.get("region", "us-east-1"),
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 2},
            ),
        )

    def close(self) -> None:
        self._client.close()

    def walk(self, prefix: str, limit: int) -> Iterator[FileEntry]:
        count = 0
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=normalise_prefix(prefix)):
            for item in page.get("Contents", []):
                mtime = item["LastModified"].timestamp()
                yield FileEntry(str(item["Key"]), int(item["Size"]), mtime)
                count += 1
                if count >= limit:
                    return

    def read_head(self, path: str, nbytes: int) -> bytes:
        response = self._client.get_object(
            Bucket=self._bucket, Key=normalise_prefix(path), Range=f"bytes=0-{nbytes - 1}"
        )
        return bytes(response["Body"].read(nbytes))

    def get_acl(self, path: str) -> dict[str, Any]:
        acl = self._client.get_bucket_acl(Bucket=self._bucket)
        grants = [
            {"grantee_type": g.get("Grantee", {}).get("Type"), "permission": g.get("Permission")}
            for g in acl.get("Grants", [])
        ]
        return {"bucket_owner_present": bool(acl.get("Owner")), "grants": grants}
