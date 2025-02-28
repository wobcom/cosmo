import warnings
from abc import abstractmethod, ABCMeta

from cosmo.types import InterfaceType, VLANType, AbstractNetboxType


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

    @abstractmethod
    def isValidNumberOfTerminations(self, i: int):
        pass

    @classmethod
    def getInvalidNumberOfTerminationsErrorMessage(cls, i: int):
        return f"{cls.getNetboxTypeName().upper()}: {i} is not a valid number of terminations, ignoring..."

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
    def getNetboxTypeName() -> str:
        return "epl"

    @staticmethod
    def getAcceptedTerminationTypes():
        return InterfaceType

    def processInterfaceTypeTermination(self, o: InterfaceType):
        pass


class EVPLL2VpnType(AbstractP2PL2VpnType):
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
    def getNetboxTypeName() -> str:
        return "vpws"

    @staticmethod
    def getAcceptedTerminationTypes() -> (tuple[type[AbstractNetboxType], type[AbstractNetboxType]]
                                          | type[AbstractNetboxType]
                                          | None):
        return InterfaceType

    def processInterfaceTypeTermination(self, o: InterfaceType) -> dict | None:
        pass


class VXLANL2VpnType(AbstractAnyToAnyL2VpnType):
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


class EVPNL2VpnType(AbstractAnyToAnyL2VpnType):
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
