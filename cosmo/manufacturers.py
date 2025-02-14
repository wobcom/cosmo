from abc import ABC, abstractmethod
from cosmo.types import DeviceType, InterfaceType


class AbstractManufacturer(ABC):
    @staticmethod
    def getManufacturerFor(device: DeviceType):
        for c in AbstractManufacturer.__subclasses__():
            if c.isCompatibleWith(device.getPlatform().getManufacturer().getSlug()):
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
