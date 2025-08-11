from functools import singledispatchmethod
from ipaddress import IPv4Interface, IPv6Interface, ip_interface

from cosmo.common import head, CosmoOutputType
from cosmo.cperoutervisitor import CpeRouterExporterVisitor, CpeRouterIPVisitor
from cosmo.abstractroutervisitor import AbstractRouterExporterVisitor
from cosmo.log import warn
from cosmo.netbox_types import TagType, InterfaceType, DeviceType, VRFType


class RouterBgpCpeExporterVisitor(AbstractRouterExporterVisitor):
    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    @staticmethod
    def processNumberedBGP(
        cpe, base_group_name, linked_interface, policy_v4, policy_v6
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

        t_cpe = DeviceType(cpe["device"])
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
                    },
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
                    },
                },
            }
        return groups

    @staticmethod
    def processUnnumberedBGP(base_group_name, linked_interface, policy_v4, policy_v6):
        return {
            base_group_name: {
                "any_as": True,
                "link_local_nexthop_only": True,
                "neighbors": [{"interface": linked_interface.getName()}],
                "family": {
                    "ipv4_unicast": {
                        "extended_nexthop": True,
                        "policy": policy_v4,
                    },
                    "ipv6_unicast": {
                        "policy": policy_v6,
                    },
                },
            }
        }

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

        group_name = "CPE_" + linked_interface.getName().replace(".", "-").replace(
            "/", "-"
        )
        vrf_name = "default"
        # make the type checker happy, since it cannot reliably infer
        # type from default values of policy_v4 and policy_v6
        policy_v4: CosmoOutputType = {"import_list": []}
        policy_v6: CosmoOutputType = {"import_list": []}

        ip_addresses = linked_interface.getIPAddresses()

        vrf_object = linked_interface.getVRF()
        if isinstance(vrf_object, VRFType):
            vrf_name = vrf_object.getName()
        if vrf_name == "default":
            policy_v4["export"] = "DEFAULT_V4"
            policy_v6["export"] = "DEFAULT_V6"

        t_cpe = DeviceType(cpe["device"])
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

        policy_v4["import_list"] = list(v4_import)
        policy_v6["import_list"] = list(v6_import)

        if len(ip_addresses) > 0:
            groups = self.processNumberedBGP(
                cpe, group_name, linked_interface, policy_v4, policy_v6
            )
        else:
            groups = self.processUnnumberedBGP(
                group_name, linked_interface, policy_v4, policy_v6
            )
        return {self._vrf_key: {vrf_name: {"protocols": {"bgp": {"groups": groups}}}}}

    @accept.register
    def _(self, o: TagType):
        if o.getTagName() == "bgp" and o.getTagValue() == "cpe":
            return self.processBgpCpeTag(o)
