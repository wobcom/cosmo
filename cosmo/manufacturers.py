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
    def getRoutingInstanceName():
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

    def spitVRFPathWith(self, v: VRFType | str, d: dict) -> dict:
        v = str(v)
        if v == self._cosmo_config.getGlobalVRFName():
            return self._spitDefaultVRFPathWith(d)
        else:
            return self._spitOtherVRFPathWith(v, d)

    @staticmethod
    @abstractmethod
    def hasMTUInheritance():
        pass


class JuniperManufacturer(AbstractManufacturer):
    VRF_KEY: Final[str] = "routing_instances"
    ROUTING_OPTIONS_KEY: Final[str] = "routing_options"
    _platform_re = re.compile(r"REPLACEME")

    @staticmethod
    def myManufacturerSlug():
        return "juniper"

    @classmethod
    def myPlatformRE(cls):
        return cls._platform_re

    @staticmethod
    def getRoutingInstanceName():
        return "mgmt_junos"

    def isManagementInterface(self, o: InterfaceType):
        return len(o["ip_addresses"]) >= 1 and o.getName().startswith("fxp0")

    @staticmethod
    def hasMTUInheritance():
        return True

    @classmethod
    def _spitDefaultVRFPathWith(cls, d: dict) -> dict:
        return {cls.ROUTING_OPTIONS_KEY: {**d}}

    @classmethod
    def _spitOtherVRFPathWith(cls, v: str, d: dict) -> dict:
        return {cls.VRF_KEY: {v: {**d}}}


class RtBrickManufacturer(AbstractManufacturer):
    VRF_KEY: Final[str] = "routing_instances"
    DEFAULT_VRF_KEY: Final[str] = "default"
    _platform_re = re.compile(r"REPLACEME")

    @staticmethod
    def myManufacturerSlug():
        return "rtbrick"

    @classmethod
    def myPlatformRE(cls):
        return cls._platform_re

    @staticmethod
    def getRoutingInstanceName():
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

    @classmethod
    def _spitOtherVRFPathWith(cls, v: str, d: dict) -> dict:
        return {cls.VRF_KEY: {v: {**d}}}


class CumulusNetworksManufacturer(AbstractManufacturer):
    _platform_re = re.compile(r"^cumulus-linux[a-zA-Z0-9-]*")

    @staticmethod
    def myManufacturerSlug():
        return "cumulus-networks"

    @classmethod
    def myPlatformRE(cls):
        return cls._platform_re

    @staticmethod
    def getRoutingInstanceName():
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
