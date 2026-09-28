"""S3-compatible backend: paginated listing and ranged reads of the first block (ARG-017)."""

from collections.abc import Iterator, Mapping
from typing import Any

import boto3
from botocore.config import Config

from . import FileEntry, WalkIncomplete, normalise_prefix


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

    def walk(self, prefix: str, limit: int) -> Iterator[FileEntry | WalkIncomplete]:
        """Objects under the folder `prefix`: a prefix is a folder, so `pacientes` does not take
        in `pacientes_2019/`, and a folder marker (a key ending in `/`) is not a file (QA-021)."""
        count = 0
        folder = normalise_prefix(prefix)
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=f"{folder}/" if folder else ""):
            for item in page.get("Contents", []):
                key = str(item["Key"])
                if key.endswith("/"):
                    continue
                if count >= limit:
                    yield WalkIncomplete(f"more than {limit} objects")
                    return
                mtime = item["LastModified"].timestamp()
                yield FileEntry(key, int(item["Size"]), mtime)
                count += 1

    def read_head(self, path: str, nbytes: int) -> bytes:
        if path.endswith("/"):
            return b""
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
