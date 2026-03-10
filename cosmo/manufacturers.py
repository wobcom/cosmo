import re
from abc import ABC, abstractmethod
from typing import NoReturn, Final, TYPE_CHECKING

if TYPE_CHECKING:
    from cosmo.config.cosmo_config import CosmoConfig


from cosmo.common import DeviceSerializationError
from cosmo.netbox_types import DeviceType, InterfaceType, PlatformType, VRFType


class AbstractManufacturer(ABC):
    def __init__(self, cosmo_config: "CosmoConfig"):
        self._cosmo_config: "CosmoConfig" = cosmo_config

    @classmethod
    def isCompatibleWith(cls, device: DeviceType):
        # Note: If the platform cannot be parsed, getPlatform will be a string.
        if not isinstance(device.getPlatform(), PlatformType):
            return False

        if device.getPlatform().getManufacturer():
            return (
                device.getPlatform().getManufacturer().getSlug()
                == cls.myManufacturerSlug()
            )
        else:
            # fallback in case no manufacturer is filled in for the platform
            return re.match(cls.myPlatformRE(), device.getPlatform().getSlug())

    @staticmethod
    @abstractmethod
    def myManufacturerSlug():
        pass

    @classmethod
    @abstractmethod
    def myPlatformRE(cls):
        pass

    @staticmethod
    @abstractmethod
    def getManagementVRFName():
        pass

    @abstractmethod
    def isManagementInterface(self, o: InterfaceType):
        pass

    @classmethod
    @abstractmethod
    def _spitDefaultVRFPathWith(cls, d: dict) -> dict:
        pass

    @classmethod
    @abstractmethod
    def _spitOtherVRFPathWith(cls, v: str, d: dict) -> dict:
        pass

    def _isGlobalVRF(self, v: VRFType | str):
        return str(v) == self._cosmo_config.getGlobalVRFName()

    def spitVRFPathWith(self, v: VRFType | str, d: dict) -> dict:
        if self._isGlobalVRF(v):
            return self._spitDefaultVRFPathWith(d)
        else:
            return self._spitOtherVRFPathWith(str(v), d)

    @abstractmethod
    def spitRoutingOptionsPathWith(self, v: VRFType | str, d: dict) -> dict:
        pass

    @abstractmethod
    def getRibTableNameFor(self, v: VRFType, af: int) -> str:
        pass

    @staticmethod
    @abstractmethod
    def hasMTUInheritance():
        pass


class AbstractJuniperRtBrickManufacturerCommon(AbstractManufacturer, ABC):
    VRF_KEY: Final[str] = "routing_instances"
    ROUTING_OPTIONS_KEY: Final[str] = "routing_options"

    @classmethod
    def _spitOtherVRFPathWith(cls, v: str, d: dict) -> dict:
        return {cls.VRF_KEY: {v: {**d}}}

    def spitRoutingOptionsPathWith(self, v: VRFType | str, d: dict) -> dict:
        return self.spitVRFPathWith(v, {self.ROUTING_OPTIONS_KEY: d})

    def getRibTableNameFor(self, v: VRFType, af: int) -> str:
        match self._isGlobalVRF(v), af:
            case True, 4:
                return "inet.0"
            case True, 6:
                return "inet6.0"
            case False, 4:
                return f"{v.getName()}.inet.0"
            case False, 6:
                return f"{v.getName()}.inet6.0"
            case _:
                raise NotImplementedError


class JuniperManufacturer(AbstractJuniperRtBrickManufacturerCommon):
    _platform_re = re.compile(r"REPLACEME")

    @staticmethod
    def myManufacturerSlug():
        return "juniper"

    @classmethod
    def myPlatformRE(cls):
        return cls._platform_re

    @staticmethod
    def getManagementVRFName():
        return "mgmt_junos"

    def isManagementInterface(self, o: InterfaceType):
        return len(o["ip_addresses"]) >= 1 and o.getName().startswith("fxp0")

    @staticmethod
    def hasMTUInheritance():
        return True

    @classmethod
    def _spitDefaultVRFPathWith(cls, d: dict) -> dict:
        return {**d}


class RtBrickManufacturer(AbstractJuniperRtBrickManufacturerCommon):
    DEFAULT_VRF_KEY: Final[str] = "default"
    _platform_re = re.compile(r"REPLACEME")

    @staticmethod
    def myManufacturerSlug():
        return "rtbrick"

    @classmethod
    def myPlatformRE(cls):
        return cls._platform_re

    @staticmethod
    def getManagementVRFName():
        return "mgmt"

    def isManagementInterface(self, o: InterfaceType):
        return len(o["ip_addresses"]) >= 1 and (
            o.getName().startswith("ma1") or o.getName().startswith("bmc0")
        )

    @staticmethod
    def hasMTUInheritance():
        return False

    @classmethod
    def _spitDefaultVRFPathWith(cls, d: dict) -> dict:
        return {cls.VRF_KEY: {cls.DEFAULT_VRF_KEY: {**d}}}


class CumulusNetworksManufacturer(AbstractManufacturer):
    _platform_re = re.compile(r"^cumulus-linux[a-zA-Z0-9-]*")

    @staticmethod
    def myManufacturerSlug():
        return "cumulus-networks"

    @classmethod
    def myPlatformRE(cls):
        return cls._platform_re

    @staticmethod
    def getManagementVRFName():
        return "mgmt"

    def isManagementInterface(self, o: InterfaceType):
        return len(o["ip_addresses"]) >= 1 and o.getName().startswith("eth")

    @staticmethod
    def hasMTUInheritance():
        return False

    @classmethod
    def _spitDefaultVRFPathWith(cls, d: dict) -> dict:
        raise NotImplementedError

    @classmethod
    def _spitOtherVRFPathWith(cls, v, d: dict) -> dict:
        raise NotImplementedError

    def spitRoutingOptionsPathWith(self, v: VRFType | str, d: dict) -> dict:
        raise NotImplementedError

    def getRibTableNameFor(self, v: VRFType, af: int) -> str:
        raise NotImplementedError


# This is needed in order to avoid accidentally initializing the ABC.
# Also enables us to extract type matching from the ABC.
class ManufacturerFactoryFromDevice:
    _all_manufacturers = (
        CumulusNetworksManufacturer,
        RtBrickManufacturer,
        JuniperManufacturer,
    )

    #                                      v    dependency injection
    def __init__(self, device: DeviceType, cosmo_config: "CosmoConfig"):
        self._device = device
        self._cosmo_config = cosmo_config

    def get(self) -> AbstractManufacturer | NoReturn:
        for c in self._all_manufacturers:
            if c.isCompatibleWith(self._device):
                return c(self._cosmo_config)
        raise Exception(f"Cannot find suitable manufacturer for device {self._device}")
