from abc import ABCMeta, abstractmethod
from typing import List, NoReturn, TypeGuard

from multimethod import multimethod as singledispatchmethod
from ipaddress import IPv4Interface, IPv6Interface

from cosmo.common import head, CosmoOutputType, InterfaceSerializationError
from cosmo.cperoutervisitor import CpeRouterExporterVisitor, CpeRouterIPVisitor
from cosmo.abstractroutervisitor import AbstractRouterExporterVisitor
from cosmo.log import warn
from cosmo.netbox_types import (
    TagType,
    InterfaceType,
    DeviceType,
    VRFType,
    AbstractNetboxType,
)


class AbstractBgpCpeExporter(metaclass=ABCMeta):
    _vrf_key = "routing_instances"
    _default_vrf_name = "default"

    @abstractmethod
    def getOptionalMaxPrefixAttrs(self) -> CosmoOutputType:
        pass  # template method pattern

    def processNumberedBGP(
        self, cpe, base_group_name, linked_interface, policy_v4, policy_v6
    ):
        ip_addresses = linked_interface.getIPAddresses()
        ip_addresses_ipo = map(lambda x: x.getIPInterfaceObject(), ip_addresses)
        own_ipv4_address = next(
            filter(lambda i: type(i) is IPv4Interface, ip_addresses_ipo), None
        )
        own_ipv6_address = next(
            filter(lambda i: type(i) is IPv6Interface, ip_addresses_ipo), None
        )

        other_ip_networks = []
        if own_ipv4_address:
            other_ip_networks.append(own_ipv4_address.network)
        if own_ipv6_address:
            other_ip_networks.append(own_ipv6_address.network)

        groups = {}

        v4_neighbors = set()
        v6_neighbors = set()

        t_cpe = cpe["device"]
        for item in iter(t_cpe):
            other_ipa = CpeRouterIPVisitor(other_ip_networks).accept(item)
            if not other_ipa:
                continue
            elif type(other_ipa) is IPv4Interface:
                v4_neighbors.add(str(other_ipa.ip))
            elif type(other_ipa) is IPv6Interface:
                v6_neighbors.add(str(other_ipa.ip))
        if v4_neighbors:
            groups[f"{base_group_name}_V4"] = {
                "any_as": True,
                "local_address": str(own_ipv4_address.ip),
                "neighbors": list(map(lambda n: {"peer": n}, v4_neighbors)),
                "family": {
                    "ipv4_unicast": {
                        "policy": policy_v4,
                    }
                    | self.getOptionalMaxPrefixAttrs(),
                },
            }
        if v6_neighbors:
            groups[f"{base_group_name}_V6"] = {
                "any_as": True,
                "local_address": str(own_ipv6_address.ip),
                "neighbors": list(map(lambda n: {"peer": n}, v6_neighbors)),
                "family": {
                    "ipv6_unicast": {
                        "policy": policy_v6,
                    }
                    | self.getOptionalMaxPrefixAttrs(),
                },
            }
        return groups

    def processUnnumberedBGP(
        self, base_group_name, linked_interface, policy_v4, policy_v6
    ):
        return {
            base_group_name: {
                "any_as": True,
                "link_local_nexthop_only": True,
                "neighbors": [{"interface": linked_interface.getName()}],
                "family": {
                    "ipv4_unicast": {
                        "extended_nexthop": True,
                        "policy": policy_v4,
                    }
                    | self.getOptionalMaxPrefixAttrs(),
                    "ipv6_unicast": {
                        "policy": policy_v6,
                    }
                    | self.getOptionalMaxPrefixAttrs(),
                },
            }
        }

    @abstractmethod
    def processImportLists(
        self,
        v4_import: set,
        v6_import: set,
    ) -> tuple[list[str], list[str]]:
        pass

    @abstractmethod
    def acceptVRFNameOrFailOn(
        self, vrf_name: str, on: AbstractNetboxType
    ) -> None | NoReturn:
        pass

    @staticmethod
    def getGroupName(
        linked_interface: InterfaceType, parent_interface: InterfaceType
    ) -> str:
        # technically a type guard, as we're narrowing on TagType. described
        # as such to satisfy the type checker.
        def tagFilter(t: TagType) -> TypeGuard[TagType]:
            return t.getTagName() == "deprecated_naming" and t.getTagValue() == "cpe"

        attached_tobago_line = parent_interface.getAttachedTobagoLine()
        # if legacy naming tag is present, or no tobago line is attached, we keep the old name as a fallback
        if not attached_tobago_line or any(
            filter(
                tagFilter,
                linked_interface.getTags(),
            )
        ):
            return "CPE_" + linked_interface.getName().replace(".", "-").replace(
                "/", "-"
            )
        else:  # use new naming scheme with tobago line name
            return "CUST_" + attached_tobago_line.getLineNameLong()

    def processBgpCpeTag(self, o: TagType):
        linked_interface = o.getParent(InterfaceType)
        if not linked_interface.hasParentInterface():
            warn(
                f"does not have a parent interface configured, skipping...",
                linked_interface,
            )
            return

        parent_interface = next(
            filter(
                lambda interface: interface == linked_interface["parent"],
                o.getParent(DeviceType).getInterfaces(),
            )
        )
        cpe = head(parent_interface.getConnectedEndpoints())
        if not cpe:
            warn(
                f"has bgp:cpe tag on it without a connected device, skipping...",
                linked_interface,
            )
            return

        group_name = self.getGroupName(linked_interface, parent_interface)
        vrf_name = self._default_vrf_name
        # make the type checker happy, since it cannot reliably infer
        # type from default values of policy_v4 and policy_v6
        policy_v4: CosmoOutputType = {"import_list": []}
        policy_v6: CosmoOutputType = {"import_list": []}

        ip_addresses = linked_interface.getIPAddresses()

        vrf_object = linked_interface.getVRF()
        if isinstance(vrf_object, VRFType):
            vrf_name = vrf_object.getName()
        self.acceptVRFNameOrFailOn(vrf_name, linked_interface)
        if vrf_name == self._default_vrf_name:
            policy_v4["export"] = ["DEFAULT_V4"]
            policy_v6["export"] = ["DEFAULT_V6"]

        t_cpe = cpe["device"]
        v4_import, v6_import = set(), set()  # unique
        cpe_visitor = CpeRouterExporterVisitor(
            forbidden_networks=list(
                map(lambda i: i.getIPInterfaceObject().network, ip_addresses)
            )
        )
        for item in iter(t_cpe):
            ret = cpe_visitor.accept(item)
            if not ret:
                continue
            af, prefix = ret
            if af and af is IPv4Interface:
                v4_import.add(prefix)
            elif af and af is IPv6Interface:
                v6_import.add(prefix)

        policy_v4["import_list"], policy_v6["import_list"] = self.processImportLists(
            v4_import, v6_import
        )

        if len(ip_addresses) > 0:
            groups = self.processNumberedBGP(
                cpe, group_name, linked_interface, policy_v4, policy_v6
            )
        else:
            groups = self.processUnnumberedBGP(
                group_name, linked_interface, policy_v4, policy_v6
            )
        return {self._vrf_key: {vrf_name: {"protocols": {"bgp": {"groups": groups}}}}}


class MaxPrefixBgpCpeExporter(AbstractBgpCpeExporter):
    def __init__(self, *args, max_prefix_n: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_prefix_n = max_prefix_n

    def acceptVRFNameOrFailOn(self, vrf_name: str, on: AbstractNetboxType):
        if vrf_name == self._default_vrf_name:
            raise InterfaceSerializationError(
                f"forbidden use of max-prefix in default vrf", on=on
            )

    def getOptionalMaxPrefixAttrs(self) -> CosmoOutputType:
        return {"max_prefixes": str(self.max_prefix_n)}

    def processImportLists(
        self,
        v4_import: set,
        v6_import: set,
    ):
        # we have max-prefix tag set, do not define import-list as it is variable
        return [], []


class DefinedImportListBgpCpeExporter(AbstractBgpCpeExporter):
    def acceptVRFNameOrFailOn(self, vrf_name: str, on: AbstractNetboxType):
        pass  # do not care

    def getOptionalMaxPrefixAttrs(self) -> CosmoOutputType:
        return {}

    def processImportLists(
        self,
        v4_import: set,
        v6_import: set,
    ):
        return list(v4_import), list(v6_import)


class RouterBgpCpeExporterVisitor(AbstractRouterExporterVisitor):
    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    @accept.register
    def _(self, o: List[TagType]):
        if "bgp:cpe" in o and "max-prefixes" in o:
            prefix_tag = head(TagType.filterTags(o, "max-prefixes"))
            return MaxPrefixBgpCpeExporter(
                max_prefix_n=int(prefix_tag.getTagValue())
            ).processBgpCpeTag(head(o))
        elif "bgp:cpe" in o:
            return DefinedImportListBgpCpeExporter().processBgpCpeTag(head(o))
