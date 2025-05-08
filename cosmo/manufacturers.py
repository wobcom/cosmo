import re
from abc import ABC, abstractmethod
from typing import NoReturn

from cosmo.common import DeviceSerializationError
from cosmo.netbox_types import DeviceType, InterfaceType, PlatformType


class AbstractManufacturer(ABC):
    @classmethod
    def isCompatibleWith(cls, device: DeviceType):
        # Note: If the platform cannot be parsed, getPlatform will be a string.
        if not isinstance(device.getPlatform(), PlatformType):
            return False
        
        if device.getPlatform().getManufacturer():
            return device.getPlatform().getManufacturer().getSlug() == cls.myManufacturerSlug()
        else:
            # fallback in case no manufacturer is filled in for the platform
            return re.match(cls.myPlatformRE(),device.getPlatform().getSlug())

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
    @staticmethod
    @abstractmethod
    def hasMTUInheritance():
        pass

class JuniperManufacturer(AbstractManufacturer):
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
        return len(o['ip_addresses']) >= 1 and o.getName().startswith("fxp0")
    @staticmethod
    def hasMTUInheritance():
        return True

class RtBrickManufacturer(AbstractManufacturer):
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
        return len(o['ip_addresses']) >= 1 and (
            o.getName().startswith("ma1") or
            o.getName().startswith("bmc0")
        )
    @staticmethod
    def hasMTUInheritance():
        return False

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
        return len(o['ip_addresses']) >= 1 and o.getName().startswith("eth")
    @staticmethod
    def hasMTUInheritance():
        return False

# This is needed in order to avoid accidentally initializing the ABC.
# Also enables us to extract type matching from the ABC.
class ManufacturerFactoryFromDevice:
    _all_manufacturers = (
        CumulusNetworksManufacturer,
        RtBrickManufacturer,
        JuniperManufacturer
    )

    def __init__(self, device: DeviceType):
        self._device = device

    def get(self) -> AbstractManufacturer | NoReturn:
        for c in self._all_manufacturers:
            if c.isCompatibleWith(self._device):
                return c()
        raise Exception(
            f"Cannot find suitable manufacturer for device {self._device}"
        )
