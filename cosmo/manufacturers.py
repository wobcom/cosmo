import re
from abc import ABC, abstractmethod
from cosmo.types import DeviceType, InterfaceType


class AbstractManufacturer(ABC):
    @classmethod
    def getManufacturerFor(cls, device: DeviceType):
        for c in AbstractManufacturer.__subclasses__():
            if c.isCompatibleWith(device):
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
        return len(o['ip_addresses']) >= 1 and o.getName().startswith("fxp0")


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
