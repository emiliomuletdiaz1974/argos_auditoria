"""Create or update the JetStream streams with the platform user, once at start (SEC-026, F09-06).

The services no longer do it on connect: their NATS users may not create or change a stream.
"""

import asyncio
import os
import sys

import nats

from argos_common.config import get_config
from argos_events import STREAMS, ensure_streams
from argos_tls import ReloadingTLS

USER = "platform"
DEV_PASSWORD = "dev-only-nats-platform"  # noqa: S105 - development password of deploy/dev/nats


async def run() -> None:
    cfg = get_config()
    folder = cfg.TLS_DIR or os.environ.get("ARGOS_TLS_DIR")
    tls = ReloadingTLS(server=False, cert_dir=folder).context() if folder else None
    password = os.environ.get("ARGOS_NATS_PLATFORM_PASSWORD", DEV_PASSWORD)
    nc = await nats.connect(cfg.NATS_URL, user=USER, password=password, tls=tls)
    try:
        await ensure_streams(nc.jetstream())
    finally:
        await nc.close()
    print(f"{len(STREAMS)} streams ready")


if __name__ == "__main__":
    asyncio.run(run())
    sys.exit(0)
