import ipaddress
import re

from cosmo.logger import Logger

l = Logger("serializer.py")

class Tags:
    def __init__(self, tags):
        if tags is None:
            tags = []
        self.tags = tags

    # check if tag exists
    def has(self, item, key = None):
        if key:
           return item.lower() in self.get_from_key(key)
        else:
           return item.lower() in [t["slug"].lower() for t in self.tags]

    # return all sub-tags using a key
    def get_from_key(self, key):
        delimiter = ":"
        keylen = len(key) + len(delimiter)
        return [t['name'][keylen:] for t in self.tags if t['name'].lower().startswith(key.lower()+delimiter)]

    # check if there are any tags with a specified key
    def has_key(self, key):
        return len(self.get_from_key(key)) > 0


class RouterSerializer:

    vendor_prefix = ""
    mgmt_interface = ""

    def __init__(self, device, l2vpn_vlan_terminations, l2vpn_interface_terminations, vrfs):
        self.device = device
        self.l2vpn_vlan_terminations = l2vpn_vlan_terminations
        self.l2vpn_interface_terminations = l2vpn_interface_terminations
        self.l2vpns = {}
        self.vrfs = vrfs
        self.l3vpns = {}

    def _get_subinterfaces(self, interfaces, base_name):
        sub_interfaces = [
            interface
            for interface in interfaces
            if "." in interface["name"] and interface["name"].split(".")[0] == base_name
        ]
        return sub_interfaces

    def _get_vrf_rib(self, routes, vrf):
        rib = {}
        for route in routes:
            if route["vrf"]["name"] == vrf:
                r = {}
                # prefer the explicit next hop over the interface
                if route["next_hop"]:
                    r["next_hop"] = route["next_hop"]["address"].split("/")[0]
                elif route["interface"]:
                    r["next_hop"] = route["interface"]["name"]

                if route["metric"]:
                    r["metric"] = route["metric"]

                # assemble table name
                if route["prefix"]["family"]["value"] == 4:
                    table = "inet.0"
                else:
                    table = "inet6.0"
                if vrf:
                    table = vrf+"."+table

                if table not in rib:
                    rib[table] = {"static": {}}
                rib[table]["static"][route["prefix"]["prefix"]] = r
        return rib


    def _get_unit(self, iface):
        unit_stub = {}
        ipv4s = []
        ipv6s = []
        policer = {}
        tags = Tags(iface.get("tags"))
        is_edge = tags.has_key("edge")
        sample = is_edge and not tags.has("customer", "edge") and not tags.has("disable_sampling")

        for ip in iface["ip_addresses"]:
            ipa = ipaddress.ip_network(ip["address"], strict=False)
            if ipa.version == 4:
                ipv4s.append(ip)
            else:
                ipv6s.append(ip)

        if tags.has_key("policer"):
            policer["input"] = "POLICER_"+tags.get_from_key("policer")[0]
            policer["output"] = "POLICER_"+tags.get_from_key("policer")[0]
        if tags.has_key("policer_in"):
            policer["input"] = "POLICER_"+tags.get_from_key("policer_in")[0]
        if tags.has_key("policer_out"):
            policer["output"] = "POLICER_"+tags.get_from_key("policer_out")[0]

        if policer:
            unit_stub["policer"] = policer
        if iface["mac_address"]:
            unit_stub["mac_address"] = iface["mac_address"]


        families = {}
        if len(ipv4s) > 0:
            families["inet"] = {"address": { address: {} for address in map(lambda addr: addr["address"], ipv4s) }}
            if iface["mtu"]:
                families["inet"]["mtu"] = iface["mtu"]
            if is_edge:
                families["inet"]["filters"] = ["input-list [ EDGE_FILTER ]"]
            if sample:
                families["inet"]["sampling"] = True
            if tags.has("peering-ixp", "edge"):
                families["inet"]["policer"] = ["arp POLICER_IXP_ARP"]
            if tags.has_key("urpf") and not tags.has("disable", "urpf"):
                families["inet"]["rpf_check"] = {"mode": tags.get_from_key("urpf")[0]}
        if len(ipv6s) > 0:
            families["inet6"] = {"address": { address: {} for address in map(lambda addr: addr["address"], ipv6s) }}
            if iface["mtu"]:
                families["inet6"]["mtu"] = iface["mtu"]
            if is_edge:
                families["inet6"]["filters"] = ["input-list [ EDGE_FILTER_V6 ]"]
            if sample:
                families["inet6"]["sampling"] = True
            if tags.has_key("urpf") and "disable" not in tags.get_from_key("urpf"):
                families["inet6"]["rpf_check"] = {"mode": tags.get_from_key("urpf")[0]}
        if tags.has("core"):
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
            if tags.has("customer", "edge"):
                prefix = "Customer: "
            elif tags.has("upstream", "edge"):
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
            l2vpn_vlan_term = self.l2vpn_vlan_terminations.get(iface["untagged_vlan"]["id"])
        else:
            l2vpn_vlan_term = False

        l2vpn = l2vpn_vlan_term or self.l2vpn_interface_terminations.get(iface["id"])
        if l2vpn:
            if l2vpn['type'] == "VPWS" and iface.get("untagged_vlan"):
                unit_stub["encapsulation"] = "vlan-ccc"
            elif l2vpn['type'] in ["MPLS_EVPN", "VXLAN_EVPN"]:
                unit_stub["encapsulation"] = "vlan-bridge"

            if not self.l2vpns.get(l2vpn["id"]):
                l2vpn["interfaces"] = []
                l2vpn["vlan"] = iface["untagged_vlan"]
                self.l2vpns[l2vpn["id"]] = l2vpn
            self.l2vpns[l2vpn["id"]]["interfaces"].append(iface)

        if iface["vrf"]:
            vrfid = iface["vrf"]["id"]
            if vrfid not in self.l3vpns:
                vrf_object = [vrf for vrf in self.vrfs if vrf["id"] == vrfid][0]
                vrf_object["interfaces"] = []
                self.l3vpns[vrfid] = vrf_object

            self.l3vpns[iface["vrf"]["id"]]["interfaces"].append(iface["name"])

        return unit_stub

    def serialize(self):
        device_stub = {
            f"{self.vendor_prefix}__device_model": self.device["device_type"]["slug"],
            f"{self.vendor_prefix}__platform": self.device["platform"]["slug"],
            f"{self.vendor_prefix}__serial": self.device["serial"],
        }
        interfaces = {}

        for interface in self.device["interfaces"]:
            tags = Tags(interface.get('tags'))

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

            for speed in tags.get_from_key("speed"):
                if re.search("[0-9]+[tgmTGM]", speed):
                    if not interface_stub.get('gigether'):
                        interface_stub['gigether'] = {}
                    interface_stub['gigether']["speed"] = speed
                else:
                    l.error(f"Interface speed {speed} on interface {interface['name']} is not known, ignoring")

            if tags.has_key("autoneg"):
                if not interface_stub.get('gigether'):
                    interface_stub['gigether'] = {}
                interface_stub['gigether']['autonegotiation'] = True if tags.get_from_key("autoneg")[0] == "on" else False

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
                if not interface_stub.get('gigether'):
                    interface_stub['gigether'] = {}
                interface_stub["gigether"]["type"] = "802.3ad"
                interface_stub["gigether"]["parent"] = lag_interface["name"]
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

                    l2vpn =  self.l2vpn_interface_terminations.get(si["id"])
                    if len(sub_interfaces) == 1 and l2vpn and l2vpn['type'] == "VPWS" and not si['untagged_vlan']:
                        interface_stub["encapsulation"] = "ethernet-ccc"

                    unit = self._get_unit(si)
                    interface_stub["units"][int(vid)] = unit

            interfaces[interface["name"]] = interface_stub

        device_stub[f"{self.vendor_prefix}__generated_interfaces"] = interfaces

        routing_options = {}

        rib = self._get_vrf_rib(self.device["staticroute_set"], None)
        if len(rib) > 0:
            routing_options["rib"] = rib

        if len(routing_options) > 0:
            device_stub[f"{self.vendor_prefix}__generated_routing_options"] = routing_options

        routing_instances = {
            f"mgmt_{self.vendor_prefix}": {
                "description": "MGMT-ROUTING-INSTANCE",
            }
        }

        if interfaces.get(self.mgmt_interface, {}).get("units", {}).get(0):
            routing_instances[f"mgmt_{self.vendor_prefix}"]["static_routes"] = [
                "0.0.0.0/0 next-hop " + next(
                    ipaddress.ip_network(
                        next(iter(interfaces[self.mgmt_interface]["units"][0]["families"]["inet"]["address"].keys())),
                        strict=False,
                    ).hosts()
                ).compressed]

        if interfaces.get("lo0", {}).get("units", {}).get(0):
            router_id = next(iter(interfaces["lo0"]["units"][0]["families"]["inet"]["address"].keys())).split("/")[0]

        for _, l2vpn in self.l2vpns.items():
            if l2vpn['type'] == "VXLAN_EVPN":
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
            elif l2vpn['type'] == "MPLS_EVPN":
                routing_instances[l2vpn["name"].replace("WAN: ", "")] = {
                    "interfaces": [
                        i["name"] for i in l2vpn["interfaces"]
                    ],
                    "description": "MPLS-EVPN: " + l2vpn["name"].replace("WAN: VS_", ""),
                    "instance_type": "evpn",
                    "protocols": {
                        "evpn": {},
                    },
                    "route_distinguisher": "9136:" + str(l2vpn["identifier"]),
                    "vrf_target": "target:1:" + str(l2vpn["identifier"]),
                }
            elif l2vpn['type'] == "VPWS":
                l2vpn_interfaces = {};
                for i in l2vpn["interfaces"]:
                    id_local = int(i['id'])

                    # get remote interface id by iterating over interfaces in the circuit and using the one that is not ours
                    for termination in l2vpn["terminations"]:
                        if int(termination["assigned_object"]["id"]) != id_local:
                            id_remote = int(termination["assigned_object"]["id"])

                    l2vpn_interfaces[i["name"]] = {
                        "vpws_service_id": {
                            "local": id_local,
                            "remote": id_remote,
                        }
                    }

                routing_instances[l2vpn["name"].replace("WAN: ", "")] = {
                    "interfaces": [
                        i["name"] for i in l2vpn["interfaces"]
                    ],
                    "description": "VPWS: " + l2vpn["name"].replace("WAN: VS_", ""),
                    "instance_type": "evpn-vpws",
                    "protocols": {
                        "evpn": {
                            "interfaces": l2vpn_interfaces,
                        },
                    },
                    "route_distinguisher": "9136:" + str(l2vpn["identifier"]),
                    "vrf_target": "target:1:" + str(l2vpn["identifier"]),
                }

        for _, l3vpn in self.l3vpns.items():
            if l3vpn["rd"]:
                rd = router_id+":"+l3vpn["rd"]
            else:
                rd = router_id+":"+l3vpn["id"]

            routing_options = {}
            rib = self._get_vrf_rib(self.device["staticroute_set"], l3vpn["name"])
            if len(rib) > 0:
                routing_options["rib"] = rib

            routing_instances[l3vpn["name"]] = {
                "interfaces": l3vpn["interfaces"],
                "description": l3vpn["description"],
                "instance_type": "vrf",
                "route_distinguisher": rd,
                "import_targets": [target["name"] for target in l3vpn["import_targets"]],
                "export_targets": [target["name"] for target in l3vpn["export_targets"]],
                "routing_options": routing_options,
            }
        device_stub[f"{self.vendor_prefix}__generated_routing_instances"] = routing_instances

        return device_stub


class JunosSerializer(RouterSerializer):
    vendor_prefix = "junos"
    mgmt_interface = "fxp0"


class RtBrickSerializer(RouterSerializer):
    vendor_prefix = "rtbrick"
    mgmt_interface = "ma1"

class SwitchSerializer:
    def __init__(self, device):
        self.device = device

    def serialize(self):
        device_stub = {}

        interfaces = {}
        vlans = set()

        for interface in self.device["interfaces"]:
            tags = Tags(interface.get('tags'))

            interface_stub = {
                "bpdufilter": True,
            }

            if interface["description"]:
                interface_stub["description"] = interface["description"]
            elif interface['lag']:
                for i in self.device["interfaces"]:
                    if interface['lag']['id'] == i['id']:
                        interface_stub["description"] = "LAG Member of "+i['name']
                        break

            interface_stub["mtu"] = interface["mtu"] if interface["mtu"] else 10000

            if interface["type"] == "LAG":
                interface_stub["bond_mode"] = "802.3ad"
                interface_stub["bond_slaves"] = sorted([i["name"] for i in self.device["interfaces"] if i["lag"] and i["lag"]["id"] == interface["id"]])

            if interface["untagged_vlan"]:
                interface_stub["untagged_vlan"] = interface["untagged_vlan"]["vid"]
                vlans.add(interface_stub["untagged_vlan"])

            if interface["tagged_vlans"]:
                interface_stub["tagged_vlans"] = [v["vid"] for v in interface["tagged_vlans"]]
                # untagged vlans belong to the vid list as well
                if interface["untagged_vlan"] and interface["untagged_vlan"]["vid"] not in interface_stub["tagged_vlans"]:
                    interface_stub["tagged_vlans"].append(interface["untagged_vlan"]["vid"])
                interface_stub["tagged_vlans"].sort()
                vlans.update(interface_stub["tagged_vlans"])

            if len(interface["ip_addresses"]) == 1 and interface["name"].startswith("eth"):
                ip = interface["ip_addresses"][0]["address"]
                interface_stub["address"] = ip
                interface_stub["gateway"] = next(
                    ipaddress.ip_network(
                        ip,
                        strict=False,
                    ).hosts()
                ).compressed
                interface_stub["vrf"] = "mgmt"
                interface_stub["mtu"] = interface["mtu"] if interface["mtu"] else 1500
                interface_stub.pop("bpdufilter")

            for speed in tags.get_from_key("speed"):
                if speed == "1g":
                    interface_stub["speed"] = 1000
                elif speed == "10g":
                    interface_stub["speed"] = 10000
                elif speed == "100g":
                    interface_stub["speed"] = 100000
                else:
                    l.error(f"Interface speed {speed} on interface {interface['name']} is not known, ignoring")

            for fec in tags.get_from_key("fec"):
                if fec in ["off", "rs", "baser"]:
                    interface_stub["fec"] = fec
                else:
                    l.error(f"FEC mode {fec} on interface {interface['name']} is not known, ignoring")

            if tags.has("lldp"):
                interface_stub["lldp"] = True

            interfaces[interface["name"]] = interface_stub

        interfaces["bridge"] = {
            "mtu": 10000,
            "tagged_vlans": sorted(list(vlans)),
            "bridge_ports": sorted([i["name"] for i in self.device["interfaces"] if i["enabled"] and not i["lag"] and (i["untagged_vlan"] or len(i["tagged_vlans"]) > 0)]),
        }

        device_stub["cumulus__device_interfaces"] = interfaces

        return device_stub
