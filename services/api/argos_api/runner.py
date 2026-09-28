"""What the API asks of the campaign engine in Temporal: start, signal and ask how it goes.

The API does not know Temporal: it knows this. The implementation over the Temporal client is
wired where the process starts, and the tests hand in one that keeps everything in memory.
"""

from typing import Any, Protocol


class AlreadyRunningError(Exception):
    """The workflow asked for is already running: launching or verifying twice is a conflict."""


class CampaignRunner(Protocol):
    async def start(self, campaign_id: str) -> str:
        """Start the campaign workflow; its id, or `AlreadyRunningError`."""
        ...

    async def signal(self, campaign_id: str, name: str, argument: str) -> None:
        """Send a signal to the running campaign (an approved gate, for instance)."""
        ...

    async def progress(self, campaign_id: str) -> dict[str, Any]:
        """The `progress` query of the workflow; LookupError when it is not running."""
        ...

    async def remediate(self, scope: dict[str, Any]) -> str:
        """Start the re-run of ARG-049 over `scope` (a finding or a campaign); its workflow id, or
        `AlreadyRunningError` while the same re-run is still going."""
        ...
