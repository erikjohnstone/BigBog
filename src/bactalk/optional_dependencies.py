"""Lazy access to optional runtime dependencies.

BACTalk installs a small base dependency set so that ``make install`` always
produces an importable API. Capabilities that need heavier or
differently-licensed runtimes -- the Alfalfa client, BACnet stacks, pyfunnel,
the Cerebras SDK, Open-FDD -- live behind pip extras.

Importing those packages at module scope makes one missing extra break the
entire application, so every optional package is described here and imported
on first use. A caller that needs one either asks whether it is
:meth:`OptionalDependency.available` or calls :meth:`OptionalDependency.load`
and converts :class:`OptionalDependencyError` into an explicit
``503 capability unavailable`` response carrying the exact remediation
command. A missing extra therefore disables one capability instead of the
product.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module, metadata
from types import ModuleType
from typing import Any


class OptionalDependencyError(RuntimeError):
    """Raised when an optional capability is used without its package."""

    def __init__(self, dependency: OptionalDependency, cause: Exception | None = None):
        self.dependency = dependency
        self.capability = dependency.capability
        self.remediation = dependency.remediation
        message = (
            f"{dependency.capability} is unavailable because the optional package "
            f"'{dependency.distribution}' is not installed. {dependency.remediation}"
        )
        super().__init__(message)
        self.__cause__ = cause


@dataclass(frozen=True)
class OptionalDependency:
    """One optional package and the capability it unlocks."""

    distribution: str
    """Distribution name as pip installs it (``alfalfa-client``)."""

    module: str
    """Top-level import name (``alfalfa_client``)."""

    extra: str
    """The pyproject extra that provides this distribution."""

    capability: str
    """Human-readable capability this package enables."""

    @property
    def remediation(self) -> str:
        return f"Install it with: pip install -e '.[{self.extra}]'  (or run: make bootstrap-full)"

    def version(self) -> str | None:
        """Installed version, or ``None`` when the distribution is absent."""
        try:
            return metadata.version(self.distribution)
        except metadata.PackageNotFoundError:
            return None

    def available(self) -> bool:
        """True when the module can actually be imported.

        This deliberately imports rather than only reading distribution
        metadata, because a broken or partially installed package must be
        reported as unavailable instead of failing later inside a request.
        """
        try:
            self.load()
        except OptionalDependencyError:
            return False
        return True

    def load(self) -> ModuleType:
        """Import and return the module, or raise :class:`OptionalDependencyError`."""
        try:
            return import_module(self.module)
        except ImportError as exc:  # pragma: no cover - exercised via available()
            raise OptionalDependencyError(self, exc) from exc

    def attribute(self, name: str) -> Any:
        """Import the module and return one attribute from it."""
        module = self.load()
        try:
            return getattr(module, name)
        except AttributeError as exc:
            raise OptionalDependencyError(self, exc) from exc

    def require(self) -> None:
        """Raise :class:`OptionalDependencyError` unless the package is importable.

        Call this at the top of a function that is about to import the package
        lazily. It converts a bare ``ModuleNotFoundError`` -- which surfaces as
        an opaque 500 -- into the typed error the API renders as a 503 naming
        the capability and the exact install command.
        """
        self.load()

    def status(self) -> dict[str, Any]:
        """Machine-readable status for ``make doctor`` and the readiness ledger."""
        version = self.version()
        available = self.available()
        return {
            "distribution": self.distribution,
            "module": self.module,
            "extra": self.extra,
            "capability": self.capability,
            "installed": available,
            "version": version,
            "remediation": None if available else self.remediation,
        }


ALFALFA_CLIENT = OptionalDependency(
    distribution="alfalfa-client",
    module="alfalfa_client",
    extra="alfalfa",
    capability="Alfalfa whole-building FMU qualification",
)

BACPYPES3 = OptionalDependency(
    distribution="bacpypes3",
    module="bacpypes3",
    extra="bacnet-lab",
    capability="Loopback BACnet/IP virtual building runtime",
)

BAC0 = OptionalDependency(
    distribution="BAC0",
    module="BAC0",
    extra="bacnet-lab",
    capability="Independent BACnet client probing",
)

PYFUNNEL = OptionalDependency(
    distribution="pyfunnel",
    module="pyfunnel",
    extra="funnel",
    capability="Trajectory tolerance grading for simulation oracles",
)

CEREBRAS = OptionalDependency(
    distribution="cerebras_cloud_sdk",
    module="cerebras.cloud.sdk",
    extra="ai",
    capability="Cerebras AI conversation and coding roles",
)

OPEN_FDD = OptionalDependency(
    distribution="open-fdd",
    module="open_fdd",
    extra="fdd",
    capability="Open-FDD independent fault-rule verification",
)


OPTIONAL_DEPENDENCIES: tuple[OptionalDependency, ...] = (
    ALFALFA_CLIENT,
    BACPYPES3,
    BAC0,
    PYFUNNEL,
    CEREBRAS,
    OPEN_FDD,
)


def optional_dependency_status() -> list[dict[str, Any]]:
    """Status of every optional dependency, ordered as declared."""
    return [dependency.status() for dependency in OPTIONAL_DEPENDENCIES]
