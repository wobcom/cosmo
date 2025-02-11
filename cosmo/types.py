import abc
from collections.abc import Iterable
from .common import head, without_keys


class AbstractNetboxType(abc.ABC, Iterable, dict):
    __parent = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for k, v in without_keys(self, "__parent").items():
            self[k] = self.convert(v)

    def __iter__(self):
        yield self
        for k, v in without_keys(self, ["__parent", "__typename"]).items():
            if isinstance(v, dict):
                yield from iter(v)
            if isinstance(v, list):
                for e in v:
                    yield from e
            else:
                yield v

    def convert(self, item):
        if isinstance(item, dict):
            if "__typename" in item.keys():
                c = {k: v for k, v in [c.register() for c in AbstractNetboxType.__subclasses__()]}[item["__typename"]]
                #            self descending in tree
                return c({k: self.convert(v) for k, v in without_keys(item, "__parent").items()} | {"__parent": self})
            else:
                return item
        elif isinstance(item, list):
            replacement = []
            for i in item:
                #                  self descending in tree
                replacement.append(self.convert(i))
            return replacement
        else:
            return item

    @classmethod
    def _getNetboxType(cls):
        # classes should have the same name as the type name
        # if not, you can override in parent class
        return cls.__name__

    @classmethod
    def register(cls) -> tuple:
        return cls._getNetboxType(), cls

    def getParent(self, target_type=None):
        if not target_type:
            return self['__parent']
        else:
            instance = self
            while type(instance) != target_type:
                instance = instance['__parent']
            return instance

    def __repr__(self):
        return self._getNetboxType()


class AbstractManufacturerStrategy(abc.ABC):
    def matches(self, manuf_slug):
        return True if manuf_slug == self.mySlug() else False
    @abc.abstractmethod
    def mySlug(self):
        pass
    @abc.abstractmethod
    def getRoutingInstanceName(self):
        pass
    @abc.abstractmethod
    def getManagementInterfaceName(self):
        pass
    @abc.abstractmethod
    def getBmcInterfaceName(self):
        pass

class JuniperManufacturerStrategy(AbstractManufacturerStrategy):
    def mySlug(self):
        return "juniper"
    def getRoutingInstanceName(self):
        return "mgmt_junos"
    def getManagementInterfaceName(self):
        return "fxp0"
    def getBmcInterfaceName(self):
        return None

class RtBrickManufacturerStrategy(AbstractManufacturerStrategy):
    def mySlug(self):
        return "rtbrick"
    def getRoutingInstanceName(self):
        return "mgmt"
    def getManagementInterfaceName(self):
        return "ma1"
    def getBmcInterfaceName(self):
        return "bmc0"

# POJO style store
class DeviceType(AbstractNetboxType):
    manufacturer_strategy: AbstractManufacturerStrategy = None

    def getPlatformManufacturer(self):
        return self.getPlatform().getManufacturer().getSlug()

    # can't @cache, non-hashable
    def getManufacturerStrategy(self):
        if self.manufacturer_strategy:
            return self.manufacturer_strategy
        else:
            slug = self.getPlatformManufacturer()
            for c in AbstractManufacturerStrategy.__subclasses__():
                if c().matches(slug):
                    self.manufacturer_strategy = c(); break
            return self.manufacturer_strategy

    def getInterfaceByName(self, name):
        l = list(
            filter(
                lambda i: i.getInterfaceName() == name,
                self.getInterfaces()
            )
        )
        return l if l != [] else None

    def getRoutingInstance(self):
        return self.getManufacturerStrategy().getRoutingInstanceName()

    def getManagementInterface(self):
        return head(self.getInterfaceByName(
            self.getManufacturerStrategy().getManagementInterfaceName()
        ))

    def getBmcInterface(self):
        return head(self.getInterfaceByName(
            self.getManufacturerStrategy().getBmcInterfaceName()
        ))

    def getDeviceType(self):
        return self['device_type']

    def getPlatform(self):
        return self['platform']

    def getInterfaces(self):
        return self['interfaces']


class DeviceTypeType(AbstractNetboxType):
    pass


class PlatformType(AbstractNetboxType):
    def getManufacturer(self):
        return self['manufacturer']


class ManufacturerType(AbstractNetboxType):
    def getSlug(self):
        return self['slug']


class IPAddressType(AbstractNetboxType):
    pass


class InterfaceType(AbstractNetboxType):
    def __repr__(self):
        return super().__repr__() + f"({self.getName()})"

    def getName(self):
        return self['name']


class VRFType(AbstractNetboxType):
    pass


class TagType(AbstractNetboxType):
    _delimiter = ':'
    def getTagComponents(self):
        return self['name'].split(self._delimiter)
    def getTagName(self):
        return self.getTagComponents()[0]
    def getTagValue(self):
        return self.getTagComponents()[1]


class VLANType(AbstractNetboxType):
    pass
