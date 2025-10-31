import json
from abc import ABCMeta, abstractmethod
from typing import Optional, Self, Never

from cosmo.common import AutoDescriptionError, CosmoOutputType, head
from cosmo.netbox_types import (
    InterfaceType,
    IAutoDescCompatibleConnectionTermination,
)


class AbstractComposableAutoDescription(metaclass=ABCMeta):
    NOT_MATCHED = 0
    FALLBACK_MATCHED = 10
    MATCHED = 100

    def __init__(
        self,
        interface: Optional[InterfaceType] = None,
        description: Optional["AbstractComposableAutoDescription"] = None,
    ):
        self.priority: int = self.NOT_MATCHED
        self._interface: Optional[InterfaceType] = interface
        self.children: list["AbstractComposableAutoDescription"] = []
        if interface:
            self.priority = self.accepts(interface)
        if description:
            self.children.extend(description.getChildren())

    def __lt__(self, other: Self):
        return self.priority < other.getPriority()

    def isMatched(self) -> bool:
        return self.priority > self.NOT_MATCHED

    @property
    def interface(self) -> InterfaceType:
        if not self.isMatched():
            raise AutoDescriptionError(
                "attempted to serialize mismatching auto description",
            )
        if self._interface is None:
            raise AutoDescriptionError(
                "attempted to access interface when it was not set"
            )
        return self._interface

    def getChildren(self) -> list["AbstractComposableAutoDescription"]:
        return self.children

    def add(self, o: Self) -> Self:
        self.children.append(o)
        return self

    @abstractmethod
    def accepts(self, o: InterfaceType) -> int:
        # heuristic matching implementation goes there
        pass

    def getPriority(self) -> int:
        return self.priority

    @staticmethod
    def suppressTenant() -> bool:
        return False

    def toDict(self) -> CosmoOutputType | Never:
        attached_tobago_line = self.interface.getAttachedTobagoLineWithTraversal()
        connected_endpoints: list[IAutoDescCompatibleConnectionTermination] = (
            self.interface.getConnectedEndpointsWithTraversal()
        )
        connected_endpoints_auto: list[CosmoOutputType] = list(
            map(lambda e: e.toDict(), connected_endpoints)
        )
        link_peers: list[IAutoDescCompatibleConnectionTermination] = (
            self.interface.getLinkPeersWithTraversal()
        )
        link_peers_auto: list[CosmoOutputType] = list(
            map(lambda e: e.toDict(), link_peers)
        )
        return (
            {}
            | (
                {"description": self.interface.getDescription()}
                if self.interface.hasDescription()
                else {}
            )
            | (  # directly attached line has priority
                {"line": attached_tobago_line.getName()}
                if attached_tobago_line and self.suppressTenant()
                else {}
            )
            | (
                {
                    "line": attached_tobago_line.getName(),
                    "tenant": attached_tobago_line.getTenantName(),
                }
                if attached_tobago_line and not self.suppressTenant()
                else {}
            )
            | (
                {
                    "connected_endpoints": connected_endpoints_auto,
                }
                if connected_endpoints
                else {}
            )
            | (
                {
                    "link_peers": link_peers_auto,
                }
                if link_peers and not connected_endpoints
                else {}
            )
        )

    def __str__(self) -> str:
        return json.dumps(self.toDict())


class PhysicalInterfaceContainerDescription(AbstractComposableAutoDescription):
    def isMatched(self) -> bool:
        return True  # override since container is not assigned by match

    def accepts(self, o: InterfaceType) -> int:
        return self.NOT_MATCHED  # always has to be initialized by children, if any

    def toDict(self) -> CosmoOutputType | Never:
        match self.children:
            case []:  # none, describe self
                return super().toDict()
            case [single]:  # transparent
                return single.toDict()
            case [first, second, *others]:
                return super().toDict() | {
                    "type": "multiservices",
                    "lines": list(
                        map(
                            lambda ad: str(ad.toDict().get("line")),
                            filter(
                                lambda ad: ad.toDict().get("line") is not None,
                                [first, second, *others],
                            ),
                        )
                    ),
                }
            case _:
                raise AutoDescriptionError("unsupported combination", on=self.interface)


class CoreSubInterfaceDescription(AbstractComposableAutoDescription):
    def accepts(self, o: InterfaceType) -> int:
        if o.isSubInterface() and "core" in o.getTags():
            return self.MATCHED
        return self.NOT_MATCHED

    @staticmethod
    def suppressTenant() -> bool:
        return True

    def toDict(self) -> dict | Never:
        return super().toDict() | {
            "type": "core",
        }


class CustomerSubInterfaceDescription(AbstractComposableAutoDescription):
    def accepts(self, o: InterfaceType) -> int:
        if o.isSubInterface() and "edge:customer" in o.getTags():
            return self.MATCHED
        return self.NOT_MATCHED

    def toDict(self) -> CosmoOutputType | Never:
        return super().toDict() | {"type": "customer"}


# access interface cannot be used as "container" type, whole physical interface is used
class AccessPhysicalInterfaceDescription(AbstractComposableAutoDescription):
    def accepts(self, o: InterfaceType) -> int:
        if not o.isSubInterface() and "access" in o.getTags():
            return self.MATCHED
        return self.NOT_MATCHED

    def toDict(self) -> CosmoOutputType | Never:
        return super().toDict() | {"type": "access"}


class PeeringSubInterfaceDescription(AbstractComposableAutoDescription):
    def accepts(self, o: InterfaceType) -> int:
        if o.isSubInterface() and (
            "edge:peering-pni" in o.getTags() or "edge:peering-ixp" in o.getTags()
        ):
            return self.MATCHED
        return self.NOT_MATCHED

    def toDict(self) -> CosmoOutputType | Never:
        return super().toDict() | {"type": "peering"}
