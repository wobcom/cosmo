import warnings
from abc import abstractmethod, ABCMeta
from functools import singledispatchmethod

from cosmo.common import head
from cosmo.types import InterfaceType, VLANType, AbstractNetboxType, DeviceType


# FIXME simplify this!
class AbstractEncapTrait(metaclass=ABCMeta):
    @singledispatchmethod
    def accept(self, o):
        warnings.warn(f"cannot find suitable encapsulation for type {type(o)}")


class EthernetCccEncapTrait(AbstractEncapTrait, metaclass=ABCMeta):
    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    @accept.register
    def _(self, o: InterfaceType):
        root_name = o.getSubInterfaceParentInterfaceName() if o.isSubInterface() else o.getName()
        sub_units = list(filter( # costlier check it is then
            lambda i: i.getName().startswith(root_name) and i.isSubInterface(),
            o.getParent(DeviceType).getInterfaces()
        ))
        if len(sub_units) == 1:
            return "ethernet-ccc"


class VlanCccEncapTrait(AbstractEncapTrait, metaclass=ABCMeta):
    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    @accept.register
    def _(self, o: VLANType):
        return "vlan-ccc"

    @accept.register
    def _(self, o: InterfaceType):
        if len(o.getTaggedVLANS()) or o.getUntaggedVLAN():
            return "vlan-ccc"


class VlanBridgeEncapTrait(AbstractEncapTrait, metaclass=ABCMeta):
    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    @accept.register
    def _(self, o: InterfaceType|VLANType):
        return "vlan-bridge"


class AbstractL2VpnType(metaclass=ABCMeta):
    @staticmethod
    @abstractmethod
    def getNetboxTypeName() -> str:
        pass

    @staticmethod
    @abstractmethod
    def getAcceptedTerminationTypes() -> (tuple[type[AbstractNetboxType], type[AbstractNetboxType]]
                                          | type[AbstractNetboxType]
                                          | None):
        pass

    @staticmethod
    @abstractmethod
    def getAssociatedEncapTraits() -> list[type[AbstractEncapTrait]]:
        pass

    @abstractmethod
    def isValidNumberOfTerminations(self, i: int):
        pass

    @classmethod
    def getInvalidNumberOfTerminationsErrorMessage(cls, i: int):
        return f"{cls.getNetboxTypeName().upper()}: {i} is not a valid number of terminations, ignoring..."


    def getAssociatedEncapType(self, o: type[AbstractNetboxType]) -> str|None:
        associated_encap = head(list(filter(
            lambda encap: encap is not None,
            [t().accept(o) for t in self.getAssociatedEncapTraits()]
        )))
        if associated_encap is None:
            warnings.warn(f"couldn't find an encapsulation type for {type(o)}")
        return associated_encap

    def processInterfaceTypeTermination(self, o: InterfaceType) -> dict | None:
        warnings.warn(f"{self.getNetboxTypeName()} L2VPN does not support {type(o)} terminations.")
        return

    def processVLANTypeTermination(self, o: VLANType) -> dict | None:
        warnings.warn(f"{self.getNetboxTypeName()} L2VPN does not support {type(o)} terminations.")
        return


class AbstractP2PL2VpnType(AbstractL2VpnType, metaclass=ABCMeta):
    _p2p_authorized_terminations_n = 2

    def isValidNumberOfTerminations(self, i: int):
        return i == self._p2p_authorized_terminations_n

    @classmethod
    def getInvalidNumberOfTerminationsErrorMessage(cls, i: int):
        return (f"{cls.getNetboxTypeName().upper()} circuits are only allowed to have "
                f"{cls._p2p_authorized_terminations_n} terminations. "
                f"{super().getInvalidNumberOfTerminationsErrorMessage(i)}")


class AbstractAnyToAnyL2VpnType(AbstractL2VpnType, metaclass=ABCMeta):
    _any_to_any_min_terminations_n = 2

    def isValidNumberOfTerminations(self, i: int):
        return i >= self._any_to_any_min_terminations_n

    @classmethod
    def getInvalidNumberOfTerminationsErrorMessage(cls, i: int):
        return (f"{cls.getNetboxTypeName().upper()} circuits should have at least "
                f"{cls._any_to_any_min_terminations_n} terminations. "
                f"{super().getInvalidNumberOfTerminationsErrorMessage(i)}")


class EPLL2VpnType(AbstractP2PL2VpnType):
    @staticmethod
    def getAssociatedEncapTraits() -> list[type[AbstractEncapTrait]]:
        return [ # order is important!
            VlanCccEncapTrait,
            EthernetCccEncapTrait,
        ]

    @staticmethod
    def getNetboxTypeName() -> str:
        return "epl"

    @staticmethod
    def getAcceptedTerminationTypes():
        return InterfaceType

    def processInterfaceTypeTermination(self, o: InterfaceType):
        pass


class EVPLL2VpnType(AbstractP2PL2VpnType):
    @staticmethod
    def getAssociatedEncapTraits() -> list[type[AbstractEncapTrait]]:
        return [
            VlanCccEncapTrait,
            EthernetCccEncapTrait,
        ]

    @staticmethod
    def getNetboxTypeName() -> str:
        return "evpl"

    @staticmethod
    def getAcceptedTerminationTypes() -> (tuple[type[AbstractNetboxType], type[AbstractNetboxType]]
                                          | type[AbstractNetboxType]
                                          | None):
        return InterfaceType

    def processInterfaceTypeTermination(self, o: InterfaceType) -> dict | None:
        pass


class VPWSL2VpnType(AbstractP2PL2VpnType):
    @staticmethod
    def getAssociatedEncapTraits() -> list[type[AbstractEncapTrait]]:
        return [
            VlanCccEncapTrait,
            EthernetCccEncapTrait,
        ]

    @staticmethod
    def getNetboxTypeName() -> str:
        return "vpws"

    @staticmethod
    def getAcceptedTerminationTypes() -> (tuple[type[AbstractNetboxType], type[AbstractNetboxType]]
                                          | type[AbstractNetboxType]
                                          | None):
        return InterfaceType

    def processInterfaceTypeTermination(self, o: InterfaceType) -> dict | None:
        pass


class VXLANEVPNL2VpnType(AbstractAnyToAnyL2VpnType):
    @staticmethod
    def getAssociatedEncapTraits() -> list[type[AbstractEncapTrait]]:
        return [ VlanBridgeEncapTrait ]

    @staticmethod
    def getNetboxTypeName() -> str:
        return "vxlan"

    @staticmethod
    def getAcceptedTerminationTypes() -> (tuple[type[AbstractNetboxType], type[AbstractNetboxType]]
                                          | type[AbstractNetboxType]
                                          | None):
        return VLANType

    def processVLANTypeTermination(self, o: VLANType) -> dict | None:
        pass


class MPLSEVPNL2VpnType(AbstractAnyToAnyL2VpnType):
    @staticmethod
    def getAssociatedEncapTraits() -> list[type[AbstractEncapTrait]]:
        return [ VlanBridgeEncapTrait ]

    @staticmethod
    def getNetboxTypeName() -> str:
        return "mpls-evpn" # no netbox3 retro-compatibility, sorry!

    @staticmethod
    def getAcceptedTerminationTypes() -> (tuple[type[AbstractNetboxType], type[AbstractNetboxType]]
                                          | type[AbstractNetboxType]
                                          | None):
        return InterfaceType, VLANType

    def processInterfaceTypeTermination(self, o: InterfaceType) -> dict | None:
        pass

    def processVLANTypeTermination(self, o: VLANType) -> dict | None:
        pass
