import abc
import ipaddress
from collections.abc import Iterable
from ipaddress import IPv4Interface, IPv6Interface

from .common import without_keys
from typing import Self, Iterator, Any


class AbstractNetboxType(abc.ABC, Iterable, dict):
    __parent = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for k, v in without_keys(self, "__parent").items():
            self[k] = self.convert(v)

    def __iter__(self) -> Iterator[Self|str|int|bool|None]:
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

    def getParent(self, target_type=None) -> Self | None:
        if '__parent' not in self.keys():
            return None
        if not target_type:
            return self['__parent']
        else:
            instance = self['__parent']
            while type(instance) != target_type:
                if "__parent" not in instance.keys():
                    # up to the whole tree we went, and we found nothing
                    return None
                else:
                    instance = instance['__parent']
            return instance

    def __eq__(self, other):
        if "id" in self.keys():
            return self["id"] == other["id"]
        else:
            # cannot compare, id is missing
            return False

    def __repr__(self):
        return self._getNetboxType()


# POJO style store
class DeviceType(AbstractNetboxType):
    def getDeviceType(self):
        return self['device_type']

    def getPlatform(self):
        return self['platform']

    def getInterfaces(self):
        return self['interfaces']

    def getName(self):
        return self["name"]


class DeviceTypeType(AbstractNetboxType):
    pass


class PlatformType(AbstractNetboxType):
    def getManufacturer(self):
        return self['manufacturer']
    def getSlug(self):
        return self['slug']


class ManufacturerType(AbstractNetboxType):
    def getSlug(self):
        return self['slug']


class IPAddressType(AbstractNetboxType):
    def getIPAddress(self) -> str:
        return self["address"]

    def getIPInterfaceObject(self) -> IPv4Interface|IPv6Interface:
        return ipaddress.ip_interface(self.getIPAddress())

    def isGlobal(self) -> bool:
        return self.getIPInterfaceObject().is_global

    def getRole(self) -> str:
        if "role" in self:
            return self["role"]


class TagType(AbstractNetboxType):
    _delimiter = ':'
    def getTagComponents(self):
        return self['name'].split(self._delimiter)
    def getTagName(self):
        return self.getTagComponents()[0]
    def getTagValue(self):
        return self.getTagComponents()[1]

class VRFType(AbstractNetboxType):
    pass

class InterfaceType(AbstractNetboxType):
    def __repr__(self):
        return super().__repr__() + f"({self.getName()})"

    def getName(self) -> str:
        return self['name']

    def getUntaggedVLAN(self):
        if "untagged_vlan" in self.keys():
            return self["untagged_vlan"]

    def getTaggedVLANS(self):
        return self["tagged_vlans"]

    def enabled(self):
        if "enabled" in self.keys() and self["enabled"]:
            return True
        return False

    def isLagMember(self):
        if "lag" in self.keys() and self["lag"]:
            return True
        return False

    def isLagInterface(self):
        if "type" in self.keys() and str(self["type"]).lower() == "lag":
            return True
        return False

    def isSubInterface(self):
        if "." in self.getName():
            return True
        return False

    def getVRF(self) -> VRFType|None:
        if "vrf" in self:
            return self["vrf"]

    def spitInterfacePathWith(self, d: dict) -> dict:
        # does not check for config correctness! do your checks 1st O:-)
        # TODO: move me in manufacturer strategy?
        if self.isSubInterface():
            return {
                self.getName().split('.')[0]: {
                    "units": {
                        int(self.getName().split('.')[1]): {
                            **d
                        }
                    }
                }
            }
        else:
            return {
                self.getName(): {
                    **d
                }
            }

    def getMode(self) -> str|None:
        if "mode" in self:
            return self["mode"]

    def isInAccessMode(self):
        if self.getMode() and self.getMode().lower() == "access":
            return True
        return False

    def getMTU(self):
        if "mtu" in self.keys():
            return self["mtu"]

    def getTags(self) -> list[TagType]:
        return self["tags"]

    def getDescription(self):
        if "description" in self.keys():
            return self["description"]

    def hasDescription(self):
        return self.getDescription() != '' and self.getDescription() is not None

    def getRawType(self) -> str:
        return self.get("type", '')

    def getAssociatedType(self):
        # TODO: move me in manufacturer strategy?
        my_type = self.getRawType().lower()
        authorized_types = [ "lag", "loopback", "virtual", "access" ]
        if "base" in my_type:
            return "physical"
        elif (
            "lag" == my_type and
            any([tag.getTagName() == "access" for tag in self.getTags()])
        ):
            return "lag-access"
        elif my_type in authorized_types:
            return my_type

    def isLoopback(self):
        return self.getAssociatedType() == "loopback"

    def getAssociatedDevice(self) -> DeviceType | None:
        if "device" in self.keys():
            return self["device"]

    def getIPAddresses(self) -> list[IPAddressType]:
        if "ip_addresses" in self:
            return self["ip_addresses"]
        return []


class VLANType(AbstractNetboxType):
    def getVID(self):
        return self["vid"]

    def getInterfacesAsTagged(self) -> list[InterfaceType]:
        if "interfaces_as_tagged" in self.keys():
            return self["interfaces_as_tagged"]
        return []

    def getInterfacesAsUntagged(self) -> list[InterfaceType]:
        if "interfaces_as_untagged" in self.keys():
            return self["interfaces_as_untagged"]
        return []


class L2VPNTerminationType(AbstractNetboxType):
    def getAssignedObject(self) -> InterfaceType|VLANType:
        return self["assigned_object"]

    def getId(self):
        return self['id']


class L2VPNType(AbstractNetboxType):
    def getName(self) -> str:
        return self["name"]

    def getType(self) -> str:
        return self["type"]

    def getL2VPNTerminationTypeList(self) -> list[L2VPNTerminationType]:
        return self['terminations']

    def getTerminations(self) -> list[InterfaceType|VLANType]:
        return list(map(lambda t: t.getAssignedObject(), self.getL2VPNTerminationTypeList()))

class RouteTargetType(AbstractNetboxType):
    pass

class CosmoLoopbackType(AbstractNetboxType):
    # TODO: refactor me for greater code reuse! (see netbox_v4.py)
    # this is an artificial type that we create in cosmo
    # it does not exist in netbox
    def getIpv4(self) -> str | None:
        return self["ipv4"]

    def getIpv6(self) -> str | None:
        return self["ipv6"]
