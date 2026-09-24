"""An inspector double, for the tests of the package and of the API (F09-11)."""

from collections.abc import Iterable, Mapping

from . import ServiceState


def service(
    name: str,
    image: str = "argos-example:dev",
    health: str = "healthy",
    health_output: str = "",
    env: Mapping[str, str] | None = None,
    mounts: tuple[str, ...] = (),
) -> ServiceState:
    return ServiceState(name, image, health, health_output, dict(env or {}), mounts)


class FakeInspector:
    """Fixed answers: the same inspector always gives the same package."""

    def __init__(
        self,
        states: Iterable[ServiceState],
        logs: Mapping[str, str] | None = None,
        events: Iterable[str] = (),
    ) -> None:
        self._states = {state.name: state for state in states}
        self._logs = dict(logs or {})
        self._events = list(events)
        self.log_requests: list[tuple[str, int]] = []

    def services(self) -> list[str]:
        return list(self._states)

    def state(self, service: str) -> ServiceState:
        return self._states[service]

    def logs(self, service: str, lines: int) -> str:
        self.log_requests.append((service, lines))
        return self._logs.get(service, "")

    def events(self) -> list[str]:
        return list(self._events)
