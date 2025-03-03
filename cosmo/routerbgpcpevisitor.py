import warnings
from functools import singledispatchmethod
from ipaddress import IPv4Interface, IPv6Interface

from cosmo.common import head
from cosmo.cperoutervisitor import CpeRouterExporterVisitor
from cosmo.abstractroutervisitor import AbstractRouterExporterVisitor
from cosmo.types import TagType, InterfaceType, DeviceType


class RouterBgpCpeExporterVisitor(AbstractRouterExporterVisitor):
    @singledispatchmethod
    def accept(self, o):
        return super().accept(o)

    def processBgpCpeTag(self, o: TagType):
        linked_interface = o.getParent(InterfaceType)
        group_name = "CPE_" + linked_interface.getName().replace(".", "-").replace("/","-")
        vrf_name = "default"
        policy_v4 = {
            "import_list": []
        }
        policy_v6 = {
            "import_list": []
        }
        if linked_interface.getVRF():
            vrf_name = linked_interface.getVRF().getName()
        if vrf_name == "default":
            policy_v4["export"] = "DEFAULT_V4"
            policy_v6["export"] = "DEFAULT_V6"
        if linked_interface.hasParentInterface():
            parent_interface = next(filter(
                lambda interface: interface == linked_interface["parent"],
                o.getParent(DeviceType).getInterfaces()
            ))
            cpe = head(parent_interface.getConnectedEndpoints())
            if not cpe:
                warnings.warn(
                    f"Interface {linked_interface.getName()} has bgp:cpe tag "
                    "on it without a connected device, skipping..."
                )
            else:
                cpe = DeviceType(cpe["device"])
                v4_import, v6_import = set(), set() # unique
                for item in iter(cpe):
                    ret = CpeRouterExporterVisitor().accept(item)
                    if not ret:
                        continue
                    af, prefix = ret
                    if af and af is IPv4Interface:
                        v4_import.add(prefix)
                    elif af and af is IPv6Interface:
                        v6_import.add(prefix)
                policy_v4["import_list"] = list(v4_import)
                policy_v6["import_list"] = list(v6_import)
        return {
            self._vrf_key: {
                vrf_name: {
                    "protocols": {
                        "bgp": {
                            "groups": {
                                group_name: {
                                    "any_as": True,
                                    "link_local_nexthop_only": True,
                                    "neighbors": [
                                        {"interface": linked_interface.getName()}
                                    ],
                                    "family": {
                                        "ipv4_unicast": {
                                            "extended_nexthop": True,
                                            "policy": policy_v4,
                                        },
                                        "ipv6_unicast": {
                                            "policy": policy_v6,
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

    @accept.register
    def _(self, o: TagType):
        if o.getTagName() == "bgp" and o.getTagValue() == "cpe":
            return self.processBgpCpeTag(o)
