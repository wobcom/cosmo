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

    def __hash__(self):
        non_recursive_clone = without_keys(self, "__parent")
        return hash(
            (
                frozenset(non_recursive_clone),
                frozenset(self.tuplize(list(non_recursive_clone.values()))),
            )
        )

    def __repr__(self):
        return self._getNetboxType()

    def __eq__(self, other):
        if self.getID() and isinstance(other, AbstractNetboxType):
            return self.getID() == other.getID()
        else:
            # cannot compare, id is missing
            return False

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

    def getID(self):
        if "id" in self.keys():
            return self["id"]

    @classmethod
    def tuplize(cls, o):
        if isinstance(o, list) or isinstance(o, set):
            return tuple(cls.tuplize(i) for i in o)
        elif isinstance(o, dict):
            return tuple(cls.tuplize(v) for k, v in without_keys(o, "__parent").items())
        else:
            return o


# POJO style store
# why so many getters, you ask? the answer is simple:
# netbox developers like to change their data structure
# every quarter. so, instead of having a billion attribute
# names in the code to change each time it happens,
# you just have to change the attribute name in
# the getter method and voilà.
# that's also why you abstain from directly addressing
# attributes in the visitors.
# as a bonus, we can also have tiny bits of logic in
# the getters to deduplicate utility code
class DeviceType(AbstractNetboxType):
    def __repr__(self):
        return super().__repr__() + f"({self.getName()})"

    def getDeviceType(self):
        return self['device_type']

    def getPlatform(self):
        return self['platform']

    def getInterfaces(self) -> list["InterfaceType"]:
        if "interfaces" in self:
            return self['interfaces']
        return []

    def getName(self):
        return self["name"]

    def getSerial(self) -> str:
        if "serial" in self and self["serial"]:
            return self["serial"]
        return ""


class DeviceTypeType(AbstractNetboxType):
    def getSlug(self) -> str:
        return self["slug"]


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


class RouteTargetType(AbstractNetboxType):
    # RT is present in VRFs
    def getName(self):
        return self["name"]


class VRFType(AbstractNetboxType):
    def getName(self) -> str:
        return self["name"]

    def getDescription(self) -> str:
        return self["description"]

    def getExportTargets(self) -> list[RouteTargetType]:
        return self["export_targets"]

    def getImportTargets(self) -> list[RouteTargetType]:
        return self["import_targets"]

    def getRouteDistinguisher(self) -> str:
        return self["rd"]


class InterfaceType(AbstractNetboxType):
    def __repr__(self):
        return super().__repr__() + f"({self.getName()})"

    def getName(self) -> str:
        return self['name']

    def getMACAddress(self) -> str|None:
        if "mac_address" in self:
            return self['mac_address']

    def getUntaggedVLAN(self):
        cf = self.getCustomFields()
        if "untagged_vlan" in self.keys() and self["untagged_vlan"]:
            return self["untagged_vlan"]
        elif "outer_tag" in cf.keys() and cf["outer_tag"]:
            # outer_tag should not be used with untagged vlan
            # untagged_vlan has priority over outer_tag
            # we have to build the VLANType object in the case of
            # outer_tag usage, since there's no native type in netbox
            return VLANType({
                "vid": int(cf["outer_tag"]),
                "interfaces_as_untagged": [ self ]
            })

    def getTaggedVLANS(self) -> list:
        if "tagged_vlans" in self.keys():
            return self["tagged_vlans"]
        return []

    def enabled(self):
        if "enabled" in self.keys() and not self["enabled"]:
            return False
        return True

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

    def getUnitNumber(self) -> int|None:
        ret = None
        if self.isSubInterface():
            ret = int(self.getName().split('.')[1])
        return ret

    def getSubInterfaceParentInterfaceName(self) -> str|None:
        ret = None
        if self.isSubInterface():
            ret = self.getName().split('.')[0]
        return ret

    def getVRF(self) -> VRFType|None:
        if "vrf" in self:
            return self["vrf"]

    def spitInterfacePathWith(self, d: dict) -> dict:
        """
        Outputs the dictionary d within a dictionary representing
        the interface path (i.e directly the interface name if it's
        a normal interface, or the unit number within unit within
        the parent interface if it's a sub-interface).
        This is delegated to the InterfaceType object since it
        knows best what kind of interface it is, and it allows
        us to do code deduplication from the clients of InterfaceType.
        Config correctness checks (sub-interface authorized,
        correct property for interface etc) need to be handled by
        the caller. This is only a "formatting" function.
        """
        # TODO: move me in manufacturer strategy if we need to add
        #  router manufacturers with different sub-interface logic.
        #  given this is specific to juniper and rtbrick manufacturers.
        if self.isSubInterface():
            return {
                self.getSubInterfaceParentInterfaceName(): {
                    "units": {
                        self.getUnitNumber(): {
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
        if "tags" in self:
            return self["tags"]
        return []

    def getDescription(self):
        if "description" in self.keys():
            return self["description"]

    def hasDescription(self):
        return self.getDescription() != '' and self.getDescription() is not None

    def getRawType(self) -> str:
        return self.get("type", '')

    def getAssociatedType(self):
        # TODO: move me in manufacturer strategy?
        raw_type_l = self.getRawType().lower()
        authorized_types = [ "lag", "loopback", "virtual", "access" ]
        access = any([tag.getTagName() == "access" for tag in self.getTags()])
        if access and "lag" == raw_type_l:
            return "lag-access"
        elif access:
            return "access"
        elif "base" in raw_type_l:
            return "physical"
        elif raw_type_l in authorized_types:
            return raw_type_l

    def isLoopback(self):
        return self.getAssociatedType() == "loopback"

    def getAssociatedDevice(self) -> DeviceType | None:
        if "device" in self.keys():
            return self["device"]

    def getIPAddresses(self) -> list[IPAddressType]:
        if "ip_addresses" in self:
            return self["ip_addresses"]
        return []

    def hasParentInterface(self) -> bool:
        if "parent" in self and self["parent"]:
            return True
        return False

    def getConnectedEndpoints(self) -> list[DeviceType]:
        if "connected_endpoints" in self:
            return self["connected_endpoints"]
        return []

    def getCustomFields(self) -> dict:
        if "custom_fields" in self:
            return dict(self["custom_fields"])
        return {}


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
    def getIdentifier(self):
        return self["identifier"]

    def getName(self) -> str:
        return self["name"]

    def getType(self) -> str:
        return self["type"]

    def getL2VPNTerminationTypeList(self) -> list[L2VPNTerminationType]:
        return self['terminations']

    def getTerminations(self) -> list[InterfaceType|VLANType]:
        return list(map(lambda t: t.getAssignedObject(), self.getL2VPNTerminationTypeList()))


class CosmoStaticRouteType(AbstractNetboxType):
    # TODO: fixme
    # hacky! does not respect usual workflow
    def getNextHop(self) -> IPAddressType|None:
        if self["next_hop"]:
            return IPAddressType(self["next_hop"])

    def getInterface(self) -> InterfaceType|None:
        if self["interface"]:
            return InterfaceType(self["interface"])

    def getPrefixFamily(self) -> int:
        return self["prefix"]["family"]["value"]

    def getPrefix(self) -> str:
        return self["prefix"]["prefix"]

    def getMetric(self) -> int|None:
        return self["metric"]

    def getVRF(self) -> VRFType|None:
        if self["vrf"]:
            return VRFType(self["vrf"])


class CosmoLoopbackType(AbstractNetboxType):
    # TODO: refactor me for greater code reuse! (see netbox_v4.py)
    # this is an artificial type that we create in cosmo
    # it does not exist in netbox
    def getIpv4(self) -> str | None:
        return self["ipv4"]

    def getIpv6(self) -> str | None:
        return self["ipv6"]
