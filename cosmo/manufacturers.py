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
                if c.isCompatibleWith(device.getPlatform().getManufacturer().getSlug()):
                    cls._device_cache.associate(device, c)
                    return c()

    @classmethod
    def isCompatibleWith(cls, manuf_slug):
        return True if manuf_slug == cls.mySlug() else False
    @staticmethod
    @abstractmethod
    def mySlug():
        pass
    @staticmethod
    @abstractmethod
    def getRoutingInstanceName():
        pass
    @abstractmethod
    def isManagementInterface(self, o: InterfaceType):
        pass


class JuniperManufacturer(AbstractManufacturer):
    @staticmethod
    def mySlug():
        return "juniper"
    @staticmethod
    def getRoutingInstanceName():
        return "mgmt_junos"
    def isManagementInterface(self, o: InterfaceType):
        return True


class RtBrickManufacturer(AbstractManufacturer):
    @staticmethod
    def mySlug():
        return "rtbrick"
    @staticmethod
    def getRoutingInstanceName():
        return "mgmt"
    def isManagementInterface(self, o: InterfaceType):
        return True


class CumulusNetworksManufacturer(AbstractManufacturer):
    @staticmethod
    def mySlug():
        return "cumulus-networks"
    @staticmethod
    def getRoutingInstanceName():
        return "mgmt"
    def isManagementInterface(self, o: InterfaceType):
        return len(o['ip_addresses']) >= 1 and o.getName().startswith("eth")
