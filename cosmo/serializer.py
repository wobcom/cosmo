import ipaddress

from cosmo.logger import Logger

l = Logger("serializer.py")


class DeviceSerializer:
    def __init__(self, device, l2vpn_vlan_terminations):
        self.device = device
        self.l2vpn_vlan_terminations = l2vpn_vlan_terminations
        self.l2vpns = {}

    def _get_subinterfaces(self, interfaces, base_name):
        sub_interfaces = [
            interface
            for interface in interfaces
            if "." in interface["name"] and interface["name"].split(".")[0] == base_name
        ]
        return sub_interfaces

    def _get_unit(self, iface):
        unit_stub = {}
        ipv4s = []
        ipv6s = []
        tags = [t["slug"] for t in iface["tags"]]
        is_edge = next(filter(lambda t: t.startswith("edge_"), tags), None) is not None
        sample = is_edge and "edge_customer" not in tags and "disable_sampling" not in tags

        for ip in iface["ip_addresses"]:
            ipa = ipaddress.ip_network(ip["address"], strict=False)
            if ipa.version == 4:
                ipv4s.append(ip)
            else:
                ipv6s.append(ip)

        families = {}
        if len(ipv4s) > 0:
            families["inet"] = {"address": ipv4s[0]["address"]}
            if iface["mtu"]:
                families["inet"]["mtu"] = iface["mtu"]
            if is_edge:
                families["inet"]["filters"] = ["input-list [ EDGE_FILTER ]"]
            if sample:
                families["inet"]["sampling"] = True
            if "edge_peering-ixp" in tags:
                families["inet"]["policer"] = ["arp POLICER_IXP_ARP"]
            if "urpf_strict" in tags or "urpf_loose" in tags:
                families["inet"]["rpf_check"] = {"mode": "loose" if "urpf_loose" in tags else "strict"}
        if len(ipv6s) > 0:
            families["inet6"] = {"address": ipv6s[0]["address"]}
            if iface["mtu"]:
                families["inet6"]["mtu"] = iface["mtu"]
            if is_edge:
                families["inet6"]["filters"] = ["input-list [ EDGE_FILTER_V6 ]"]
            if sample:
                families["inet6"]["sampling"] = True
            if "urpf_strict" in tags or "urpf_loose" in tags:
                families["inet6"]["rpf_check"] = {"mode": "loose" if "urpf_loose" in tags else "strict"}
        if "core" in tags:
            families["iso"] = {}
            if iface["mtu"]:
                families["iso"]["mtu"] = iface["mtu"] - 3 # isis has an CLNS/LLC header of 3 bytes
            families["mpls"] = {}
            if iface["mtu"]:
                families["mpls"]["mtu"] = iface["mtu"] - 64 # enough space for 16 labels

        if len(families.keys()) > 0:
            unit_stub["families"] = families

        if iface["description"]:
            prefix = ""
            if "edge_customer" in tags:
                prefix = "Customer: "
            elif "edge_upstream" in tags:
                prefix = "Transit: "
            elif is_edge:
                prefix = "Peering: "

            unit_stub["description"] = prefix + iface["description"]

        if iface["mode"] == "ACCESS":
            if not iface.get("untagged_vlan"):
                l.error(
                    f"Interface {iface['name']} on device {self.device['name']} is mode ACCESS but has no untagged vlan, skipping"
                )
                return
            unit_stub["vlan"] = iface["untagged_vlan"]["vid"]

            l2vpn = self.l2vpn_vlan_terminations.get(iface["untagged_vlan"]["id"])
            if l2vpn:
                unit_stub["encapsulation"] = "vlan-bridge"
                if not self.l2vpns.get(l2vpn["id"]):
                    l2vpn["interfaces"] = []
                    l2vpn["vlan"] = iface["untagged_vlan"]
                    self.l2vpns[l2vpn["id"]] = l2vpn
                self.l2vpns[l2vpn["id"]]["interfaces"].append(iface)

        return unit_stub

    def serialize(self):
        device_stub = {"junos__device_model": self.device["device_type"]["slug"]}
        interfaces = {}

        for interface in self.device["interfaces"]:
            if not interface["enabled"]:
                interfaces[interface["name"]] = {
                    "shutdown": True
                }
                if interface["description"]:
                    interfaces[interface["name"]]["description"] = interface["description"]
                continue
            # Sub Interfaces contains . in names, we render them within the parent, so we ignore those if the parent exists
            if "." in interface["name"]:
                if not next(
                        filter(
                            lambda i: i["name"] == interface["name"].split(".")[0],
                            self.device["interfaces"],
                        ),
                        None,
                ):
                    self.device["interfaces"].append(
                        {
                            "name": interface["name"].split(".")[0],
                            "enabled": True,
                            "description": None,
                            "mtu": None,
                            "lag": None,
                        }
                    )
                continue

            interface_stub = {}

            if interface["description"]:
                interface_stub["description"] = interface["description"]

            if interface["mtu"]:
                interface_stub["mtu"] = interface["mtu"]

            if interface.get("type") == "LAG":
                interface_stub["template"] = "flexible-lacp"

            # If this interface is just part of a lag, we just connect those together and leave
            # the interface alone. Heavy configuration is done on the LAG interface afterwards.
            if interface["lag"]:
                lag_interface = next(
                    filter(
                        lambda i: i["id"] == interface["lag"]["id"],
                        self.device["interfaces"],
                    )
                )
                interface_stub["gigether"] = {
                    "type": "802.3ad",
                    "parent": lag_interface["name"],
                }
                interfaces[interface["name"]] = interface_stub
                continue

            interface_stub["units"] = {}
            sub_interfaces = self._get_subinterfaces(
                self.device["interfaces"], interface["name"]
            )
            if len(sub_interfaces) > 0:
                for si in sub_interfaces:
                    if not si["untagged_vlan"]:
                        vid = si["name"].split(".")[1]
                    else:
                        vid = si["untagged_vlan"]["vid"]

                    unit = self._get_unit(si)
                    if not unit:
                        continue
                    interface_stub["units"][int(vid)] = unit

            interfaces[interface["name"]] = interface_stub

        device_stub["junos__generated_interfaces"] = interfaces

        routing_instances = {
            "mgmt_junos": {
                "description": "MGMT-ROUTING-INSTANCE",
            }
        }

        if interfaces.get("fxp0", {}).get("units", {}).get(0):
            routing_instances["mgmt_junos"]["static_routes"] = [
                "0.0.0.0/0 next-hop " + next(
                    ipaddress.ip_network(
                        interfaces["fxp0"]["units"][0]["families"]["inet"]["address"],
                        strict=False,
                    ).hosts()
                ).compressed]

        for _, l2vpn in self.l2vpns.items():
            routing_instances[l2vpn["name"].replace("WAN: ", "")] = {
                "bridge_domains": [
                    {
                        "interfaces": [
                            {"name": i["name"]} for i in l2vpn["interfaces"]
                        ],
                        "vlan_id": l2vpn["vlan"]["vid"],
                        "name": l2vpn["vlan"]["name"],
                        "vxlan": {
                            "ingress_node_replication": True,
                            "vni": l2vpn["identifier"],
                        },
                    }
                ],
                "description": "Virtual Switch " + l2vpn["name"].replace("WAN: VS_", ""),
                "instance_type": "virtual-switch",
                "protocols": {
                    "evpn": {
                        "vni": [l2vpn["identifier"]],
                    },
                },
                "route_distinguisher": "9136:" + str(l2vpn["identifier"]),
                "vrf_target": "target:1:" + str(l2vpn["identifier"]),
            }

        device_stub["junos__generated_routing_instances"] = routing_instances

        return device_stub
