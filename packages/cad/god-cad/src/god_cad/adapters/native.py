"""A hard boundary: no production write path exists in this scaffold."""

from typing import Protocol

from god_cad.models import Patch


class NativeExecutor(Protocol):
    def execute(self, patch: Patch) -> None:
        """Future implementation must recheck host identity, revision and write authorization."""
        ...


class UnavailableNativeExecutor:
    def execute(self, patch: Patch) -> None:
        raise NotImplementedError(
            "ZWCAD host/SDK integration is not implemented. "
            "Simulation never authorizes a DWG write."
        )
