import abc
import ipaddress
import re
from enum import StrEnum
from urllib.parse import urljoin

from collections.abc import Iterable
from abc import abstractmethod, ABCMeta
from ipaddress import IPv4Interface, IPv6Interface

from .common import (
    without_keys,
    JsonOutputType,
    DeviceSerializationError,
    InterfaceSerializationError,
    head,
)
from typing import Self, Iterator, TypeVar, NoReturn, Never, Type, Any, Union

from .tobago_types import TobagoAbstractTerminationType

T = TypeVar("T", bound="AbstractNetboxType")
ConnectionTerminationType = TypeVar(
    "ConnectionTerminationType",
    bound="InterfaceType|FrontPortType|RearPortType|ConsolePortType|ConsoleServerPortType",
)


class AbstractNetboxType(abc.ABC, Iterable):
    def __init__(self, *args, **kwargs):
        self._store = dict()
        self._store.update(*args)
        self._store.update(**kwargs)
        for k, v in without_keys(self._store, "__parent").items():
            self[k] = self.convert(v)

    def __getitem__(self, key):
        return self._store[key]

    def __setitem__(self, key, item):
        self._store[key] = item

    def __delitem__(self, key):
        del self._store[key]

    def __len__(self):
        return len(self._store)

    # I have to write the union in quotes because of this Python bug:
    # https://bugs.python.org/issue45857
    def __iter__(self) -> Iterator["AbstractNetboxType|list[Any]|str|int|bool|None"]:
        yield self
        for k, v in without_keys(self._store, ["__parent", "__typename"]).items():
            if isinstance(v, dict):
                yield from iter(v)
            elif isinstance(v, list):
                yield v
                for e in v:
                    yield from e
            elif isinstance(v, AbstractNetboxType):
                yield from iter(v)
            # Note: We can omit the emit of scalars, because we do not use them.

    def __hash__(self):
        non_recursive_clone = without_keys(self._store, "__parent")
        return hash(
            (
                frozenset(non_recursive_clone),
                frozenset(self.tuplize(list(non_recursive_clone.values()))),
            )
        )

    def __repr__(self):
        return self.getNetboxType()

    def __eq__(self, other):
        if self.getID() and isinstance(other, AbstractNetboxType):
            return self.getID() == other.getID()
        else:
            # cannot compare, id is missing
            return False

    def items(self):
        return self._store.items()

    def keys(self):
        return self._store.keys()

    def values(self):
        return self._store.values()

    def get(self, *args, **kwargs):
        return self._store.get(*args, **kwargs)

    def convert(self, item):
        if isinstance(item, dict):
            if "__typename" in item.keys():
                c = {
                    k: v
                    for k, v in [
                        c.register() for c in AbstractNetboxType.__subclasses__()
                    ]
                }[item["__typename"]]
                o = c()
                o._store.update(
                    {k: o.convert(v) for k, v in without_keys(item, "__parent").items()}
                    | {"__parent": self}
                )
                return o
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
    def getNetboxType(cls):
        # classes should have the same name as the type name
        # if not, you can override in parent class
        return cls.__name__

    @classmethod
    def register(cls) -> tuple:
        return cls.getNetboxType(), cls

    def hasParentAboveWithType(self, target_type: type[T]) -> bool:
        instance = self["__parent"]
        return type(instance) == target_type

    def getParent(self, target_type: type[T]) -> T | NoReturn:
        ke = KeyError(
            f"Cannot find any object above {type(self).__name__} which is of type {target_type.__name__}. "
            f"It is likely you made wrong assumptions regarding the shape of the Netbox input data, or "
            f"forgot to use hasParentAboveWithType()."
        )
        if "__parent" not in self.keys():
            raise ke
        else:
            instance = self["__parent"]
            while type(instance) != target_type:
                if "__parent" not in instance.keys():
                    raise ke
                else:
                    instance = instance["__parent"]
            return instance

    def isUnderKeyNameForParentAboveWithType(
        self, key: str, target_type: type[T]
    ) -> bool:
        if self.hasParentAboveWithType(target_type):
            if key in self.getParent(target_type).keys() and (
                self.getParent(target_type)[key] == self
                or (
                    isinstance(self.getParent(target_type)[key], Iterable)
                    and self in self.getParent(target_type)[key]
                )
            ):  # self can be found under given key
                return True
        return False

    def getID(self):
        return self.get("id")

    def getName(self):
        return self.get("name")

    def getSlug(self):
        return self.get("slug")

    def getCustomFields(self) -> dict:
        return dict(self.get("custom_fields", {}))

    @classmethod
    def tuplize(cls, o):
        if isinstance(o, list) or isinstance(o, set):
            return tuple(cls.tuplize(i) for i in o)
        elif isinstance(o, dict):
            return tuple(cls.tuplize(v) for k, v in without_keys(o, "__parent").items())
        else:
            return o

    @abstractmethod
    def getBasePath(self):  # as in, netbox HTML view path
        pass

    def getRelPath(self) -> str:
        return urljoin(self.getBasePath(), self.getID())

    def getMetaInfo(self) -> "NetboxObjectMetaInfo":
        return NetboxObjectMetaInfo(self)


class NetboxObjectMetaInfo:
    id: int
    type: str
    rel_path: str
    device_rel_path: str
    display_name: str
    device_display_name: str

    def __init__(self, o: AbstractNetboxType):
        self.id = o.getID()
        self.type = o.getNetboxType()
        self.rel_path = o.getRelPath()
        self.device_rel_path = (
            o.getParent(DeviceType).getRelPath()
            if not isinstance(o, DeviceType)
            else o.getRelPath()
        )
        self.display_name = o.getName()
        self.device_display_name = (
            o.getParent(DeviceType).getName()
            if not isinstance(o, DeviceType)
            else o.getName()
        )

    def getFullObjectURL(self, netbox_instance_url: str):
        return urljoin(netbox_instance_url, self.rel_path)

    def toJSON(self):
        return self.__dict__


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

    def getBasePath(self):
        return "/dcim/devices/"

    def isCompositeRoot(self) -> bool:
        return not bool(self.get("__parent", False))

    def getDeviceType(self):
        return self["device_type"]

    def getPlatform(self):
        return self["platform"]

    def getInterfaces(self) -> list["InterfaceType"]:
        return self.get("interfaces", [])

    def getSerial(self) -> str:
        return self.get("serial", "")

    def getISISIdentifier(self) -> str | None | Never:
        sys_id: Any | None = self.getCustomFields().get("isis_system_id")
        if sys_id and not re.match(r"\d{4}.\d{4}.\d{4}", str(sys_id)):
            raise DeviceSerializationError(
                f"IS-IS System ID {sys_id} is invalid", on=self
            )
        return str(sys_id)


class DeviceTypeType(AbstractNetboxType):
    def getBasePath(self):
        return "/dcim/device-types/"


class PlatformType(AbstractNetboxType):
    def getBasePath(self):
        return "/dcim/platforms/"

    def getManufacturer(self):
        return self["manufacturer"]


class ManufacturerType(AbstractNetboxType):
    def getBasePath(self):
        return "/dcim/manufacturers/"


class IPAddressType(AbstractNetboxType):
    def getBasePath(self):
        return "/ipam/ip-addresses/"

    def getIPAddress(self) -> str:
        return self["address"]

    def getIPInterfaceObject(self) -> IPv4Interface | IPv6Interface:
        return ipaddress.ip_interface(self.getIPAddress())

    def isGlobal(self) -> bool:
        return self.getIPInterfaceObject().is_global

    def getRole(self) -> str:
        return self.get("role")


class TagType(AbstractNetboxType):
    _delimiter = ":"

    def __eq__(self, other):
        if not isinstance(other, str):
            return super().__eq__(other)
        else:
            return self.getTagName() == other or [
                self.getTagName(),
                self.getTagValue(),
            ] == other.split(self._delimiter)

    def getBasePath(self):
        return "/extras/tags/"

    def getTagComponents(self):
        return self.get("name").split(self._delimiter)

    def getTagName(self):
        name, _ = (self.getTagComponents() + [None])[:2]
        return name

    def getTagValue(self):
        _, value = (self.getTagComponents() + [None])[:2]
        return value

    def __repr__(self):
        return f"{super().__repr__()}({self.getTagName()},{self.getTagValue()})"

    @classmethod
    def filterTags(
        cls, l: list[Self], name: str, value: str | None = None
    ) -> list[Self]:
        return list(
            filter(
                lambda t: (t.getTagName() == name and value is None)
                or (t.getTagName() and t.getTagValue() == value),
                l,
            )
        )


class RouteTargetType(AbstractNetboxType):
    def getBasePath(self):
        return "/ipam/route-targets/"


class VRFType(AbstractNetboxType):
    def getBasePath(self):
        return "/ipam/vrfs/"

    def getDescription(self) -> str:
        return self["description"]

    def getExportTargets(self) -> list[RouteTargetType]:
        return self["export_targets"]

    def getImportTargets(self) -> list[RouteTargetType]:
        return self["import_targets"]

    def getRouteDistinguisher(self) -> str:
        return self["rd"]


class IWithAssociatedDevice(metaclass=ABCMeta):
    @abstractmethod
    def get(self, *args, **kwargs):
        pass

    def getAssociatedDevice(self) -> DeviceType | None:
        return self.get("device")


class FrontPortType(AbstractNetboxType, IWithAssociatedDevice):
    def getBasePath(self):
        return "/dcim/front-ports/"


class RearPortType(AbstractNetboxType, IWithAssociatedDevice):
    def getBasePath(self):
        return "/dcim/rear-ports/"


class CircuitTerminationType(AbstractNetboxType):
    def getBasePath(self):
        return "/circuits/circuit-terminations/"


class ConsolePortType(AbstractNetboxType, IWithAssociatedDevice):
    def getBasePath(self):
        return "/dcim/console-ports/"


class ConsoleServerPortType(AbstractNetboxType, IWithAssociatedDevice):
    def getBasePath(self):
        return "/dcim/console-server-ports/"


class InterfaceType(AbstractNetboxType, IWithAssociatedDevice):
    def __repr__(self):
        return super().__repr__() + f"({self.getName()})"

    def getBasePath(self):
        return "/dcim/interfaces/"

    def getMACAddress(self) -> str | None:
        return self.get("mac_address")

    def getUntaggedVLAN(self):
        cf = self.getCustomFields()
        if "untagged_vlan" in self.keys() and self["untagged_vlan"]:
            if cf.get("outer_tag"):
                raise InterfaceSerializationError(
                    f"has untagged {self['untagged_vlan']} and outer_tag "
                    f"{cf.get('outer_tag')}! outer_tag should not be used with "
                    f"untagged_vlan. Please fix data source.",
                    on=self,
                )
            return self["untagged_vlan"]
        elif cf.get("outer_tag"):
            # we have to build the VLANType object in the case of
            # outer_tag usage, since there's no native type in netbox
            return VLANType(
                {"vid": int(cf["outer_tag"]), "interfaces_as_untagged": [self]}
            )

    def getTaggedVLANS(self) -> list:
        return self.get("tagged_vlans", [])

    def isEnabled(self) -> bool:
        return bool(self.get("enabled", True))

    def isLagMember(self):
        if "lag" in self.keys() and self["lag"]:
            return True
        return False

    def isLagInterface(self):
        if "type" in self.keys() and str(self["type"]).lower() == "lag":
            return True
        return False

    def isSubInterface(self):
        return "." in self.getName()

    def getUnitNumber(self) -> int | None:
        ret = None
        if self.isSubInterface():
            ret = int(self.getName().split(".")[1])
        return ret

    def getSubInterfaceParentInterfaceName(self) -> str | None:
        ret = None
        if self.isSubInterface():
            ret = self.getName().split(".")[0]
        return ret

    def getVRF(self) -> VRFType | None:
        return self.get("vrf")

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
                    "units": {self.getUnitNumber(): {**d}}
                }
            }
        else:
            return {self.getName(): {**d}}

    def getMode(self) -> str | None:
        return self.get("mode")

    def isInAccessMode(self):
        if self.getMode() and self.getMode().lower() == "access":
            return True
        return False

    def getMTU(self):
        return self.get("mtu")

    def getTags(self) -> list[TagType]:
        return self.get("tags", [])

    def getDescription(self):
        return self.get("description")

    def hasDescription(self):
        return self.getDescription() != "" and self.getDescription() is not None

    def getRawType(self) -> str:
        return self.get("type", "")

    def getAssociatedType(self):
        # TODO: move me in manufacturer strategy?
        raw_type_l = self.getRawType().lower()
        authorized_types = ["lag", "loopback", "virtual", "access"]
        access = any([tag.getTagName() == "access" for tag in self.getTags()])
        if access and "lag" == raw_type_l:
            return "lag-access"
        elif access:
            return "access"
        elif "base" in raw_type_l:
            return "physical"
        elif raw_type_l in authorized_types:
            return raw_type_l

    def isLoopbackOrParentIsLoopback(self) -> bool:
        if self.getAssociatedType() == "loopback":
            return True
        elif self.isSubInterface():
            parent_interface_name = self.getSubInterfaceParentInterfaceName()
            parent_interface = head(
                list(
                    filter(
                        lambda i: i.getName() == parent_interface_name,
                        self.getParent(DeviceType).getInterfaces(),
                    )
                )
            )
            if not parent_interface:
                raise InterfaceSerializationError(
                    f"Cannot find parent interface of {self.getName()}, please ensure it is defined and that "
                    f"parent-child association is correct in data source.",
                    on=self,
                )
            return parent_interface.isLoopbackOrParentIsLoopback()
        elif self.getName().startswith("lo"):
            raise InterfaceSerializationError(
                f"Interface {self.getName()} is named as a loopback but is not marked"
                f"as such in the data source, please fix.",
                on=self,
            )
        return False

    def getIPAddresses(self) -> list[IPAddressType]:
        return self.get("ip_addresses", [])

    def hasParentInterface(self) -> bool:
        return bool(self.get("parent"))

    def isLoopbackChild(self):
        return "." in self.getName() and self.getName().startswith("lo")

    def getConnectedEndpoints(self) -> list[ConnectionTerminationType]:
        return self.get("connected_endpoints", [])

    def hasConnectedEndpoints(self) -> bool:
        return bool(len(self.getConnectedEndpoints()))

    def getLinkPeers(self) -> list[ConnectionTerminationType]:
        return self.get("link_peers", [])

    def hasLinkPeers(self):
        return bool(len(self.getLinkPeers()))

    def hasAnAttachedTobagoLine(self):
        return self.get("attached_tobago_line") is not None


class VLANType(AbstractNetboxType):
    def __repr__(self):
        return f"{super().__repr__()}({self.getVID()})"

    def getBasePath(self):
        return "/ipam/vlans/"

    def getVID(self):
        return self["vid"]

    def getInterfacesAsTagged(self) -> list[InterfaceType]:
        return self.get("interfaces_as_tagged", [])

    def getInterfacesAsUntagged(self) -> list[InterfaceType]:
        return self.get("interfaces_as_untagged", [])


class L2VPNTerminationType(AbstractNetboxType):
    def getBasePath(self):
        return "/vpn/l2vpn-terminations/"

    def getAssignedObject(self) -> InterfaceType | VLANType:
        return self["assigned_object"]


class L2VPNType(AbstractNetboxType):
    def __repr__(self):
        return f"{super().__repr__()}({self.getName()})"

    def getBasePath(self):
        return "/vpn/l2vpns/"

    def getIdentifier(self) -> int:
        if self["identifier"]:
            return self["identifier"]
        else:
            return self["id"]

    def getType(self) -> str:
        return self["type"]

    def getL2VPNTerminationTypeList(self) -> list[L2VPNTerminationType]:
        return self["terminations"]

    def getTerminations(self) -> list[InterfaceType | VLANType]:
        return list(
            map(lambda t: t.getAssignedObject(), self.getL2VPNTerminationTypeList())
        )


class CosmoStaticRouteType(AbstractNetboxType):
    # TODO: fixme
    # hacky! does not respect usual workflow
    def getBasePath(self):
        return "/plugins/routing/static_routes/"

    def getNextHop(self) -> IPAddressType | None:
        if self["next_hop"]:
            return IPAddressType(self["next_hop"])
        return None

    def getInterface(self) -> InterfaceType | None:
        if self["interface"]:
            return InterfaceType(self["interface"])
        return None

    def getPrefixFamily(self) -> int:
        return self["prefix"]["family"]["value"]

    def getPrefix(self) -> str:
        return self["prefix"]["prefix"]

    def getMetric(self) -> int | None:
        return self["metric"]

    def getVRF(self) -> VRFType | None:
        if self["vrf"]:
            return VRFType(self["vrf"])
        return None

    def __repr__(self):
        return f"{super().__repr__()}({self.getPrefix()})"


class CosmoLoopbackType(AbstractNetboxType):
    # TODO: refactor me for greater code reuse! (see netbox_v4.py)
    # this is an artificial type that we create in cosmo
    # it does not exist in netbox
    def getBasePath(self):
        return ""  # no path

    def getIpv4(self) -> str | None:
        return self["ipv4"]

    def getIpv6(self) -> str | None:
        return self["ipv6"]

    def deriveRouterId(self) -> str:
        ipv4 = self.getIpv4()
        if ipv4 is None:
            raise DeviceSerializationError(
                "Can't derive Router ID, no suitable loopback IP address found."
            )

        ipv4_address_without_cidr = str(ipaddress.ip_interface(ipv4).ip)
        return ipv4_address_without_cidr


class CosmoIPPoolType(AbstractNetboxType):
    def getBasePath(self):
        return ""  # type does not exist in netbox

    def getPrefixes(self) -> list[IPv6Interface | IPv4Interface]:
        return [ipaddress.ip_interface(p["prefix"]) for p in self["ip_prefixes"]]

    def isUniqueToDevice(self) -> bool:
        return len(self["devices"]) == 1

    def hasIPRanges(self) -> bool:
        return len(self["ip_ranges"]) > 0


class CosmoTobagoLine(AbstractNetboxType):
    class TobagoLineType(StrEnum):
        CUSTOMER = "Customer"
        PEERING = "Peering"
        CORE = "Core"
        SUBSCRIBER = "Subscriber"

    def getLineType(self) -> TobagoLineType:
        device_interface_tags = self.getParent(InterfaceType).getTags()
        line_type = self.TobagoLineType.CUSTOMER
        if "core" in device_interface_tags:
            line_type = self.TobagoLineType.CORE
        elif "access" in device_interface_tags:
            line_type = self.TobagoLineType.SUBSCRIBER
        elif (
            "edge:peering-pni" in device_interface_tags
            or "edge:peering-ixp" in device_interface_tags
        ):
            line_type = self.TobagoLineType.PEERING
        return line_type

    def getTerminationObjectForTypeAndData(self, termination_type: str, data: dict):
        tobago_termination_classes: list[type[TobagoAbstractTerminationType]] = (
            TobagoAbstractTerminationType.__subclasses__()
        )
        for c in tobago_termination_classes:
            if c.accepts(termination_type):
                return c(data)
        raise InterfaceSerializationError(
            f"Unrecognized Tobago termination type {termination_type}",
            on=self,
        )

    def getBasePath(self):
        return "/plugins/tobago/lines/"

    def _getCurrentLineMetadata(self):
        return self["version"]

    def _getCurrentLine(self):
        return self._getCurrentLineMetadata()["line"]

    def _getCurrentService(self):
        return self._getCurrentLine()["service"]

    def _getCurrentTenant(self):
        return self._getCurrentService()["tenant"]

    def getLineID(self) -> str:
        return str(self._getCurrentLine()["id"])

    def getLineNameLong(self):
        return self._getCurrentLine()["name_long"]

    def getName(self):
        return self.getLineNameLong()

    def getTenantName(self):
        return self._getCurrentTenant()["name"]

    def getLineStatus(self):
        return self._getCurrentLineMetadata()["status"]

    def getRelPath(self) -> str:
        return urljoin(self.getBasePath(), self.getLineID())

    def getOppositeTerminationObjectOf(
        self, i: InterfaceType
    ) -> TobagoAbstractTerminationType:
        terminations = [
            {"type": self["termination_a_type"], "data": self["termination_a"]},
            {"type": self["termination_b_type"], "data": self["termination_b"]},
        ]
        opposite_termination = next(
            filter(lambda t: int(t["data"]["id"]) != int(i.getID()), terminations)
        )
        return self.getTerminationObjectForTypeAndData(
            opposite_termination["type"], opposite_termination["data"]
        )

    def describe(self) -> str:
        device_interface: InterfaceType = self.getParent(InterfaceType)
        line_type = self.getLineType()

        match line_type:
            case self.TobagoLineType.SUBSCRIBER | self.TobagoLineType.CORE:
                return (
                    f"{line_type}: [{self.getOppositeTerminationObjectOf(device_interface)}]"
                    f" {{{self.getLineNameLong()}}}"
                )
            case _:
                return (
                    f"{line_type}: {self.getTenantName()}"
                    f" [{self.getOppositeTerminationObjectOf(device_interface)}]"
                    f" {{{self.getLineNameLong()}}}"
                )
