import re
from abc import ABC, abstractmethod
from cosmo.common import ObjCache
from cosmo.types import DeviceType, InterfaceType


class AbstractManufacturer(ABC):
    _device_cache = ObjCache()

    @classmethod
    def getManufacturerFor(cls, device: DeviceType):
        if cls._device_cache.get(device):
            manufacturer_class = cls._device_cache.get(device)
            return manufacturer_class()
        else:
            for c in AbstractManufacturer.__subclasses__():
                if c.isCompatibleWith(device):
                    cls._device_cache.associate(device, c)
                    return c()

    @classmethod
    def isCompatibleWith(cls, device: DeviceType):
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
        return len(o['ip_addresses']) >= 1 and o.getName() == "fxp0"


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
        return len(o['ip_addresses']) >= 1 and o.getName() == "ma1"


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
