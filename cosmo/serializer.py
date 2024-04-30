import ipaddress
import re
import json

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

    def __init__(self, device, l2vpn_vlan_terminations, l2vpn_interface_terminations, vrfs):

        match device["platform"]["manufacturer"]["slug"]:
            case 'juniper':
                self.mgmt_routing_instance = "mgmt_junos"
                self.mgmt_interface = "fxp0"
                self.lo_interface = "lo0"
            case 'rtbrick':
                self.mgmt_routing_instance = "mgmt"
                self.mgmt_interface = "ma1"
                self.lo_interface = "lo-0/0/0"
            case other:
                l.error(f"unsupported platform vendor: {other}")
                return

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
        name = iface['name'].split(".")[1]

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
            if is_edge:
                families["inet6"]["filters"] = ["input-list [ EDGE_FILTER_V6 ]"]
            if sample:
                families["inet6"]["sampling"] = True
            if tags.has_key("urpf") and "disable" not in tags.get_from_key("urpf"):
                families["inet6"]["rpf_check"] = {"mode": tags.get_from_key("urpf")[0]}
        if tags.has("core"):
            families["iso"] = {}
            families["mpls"] = {}

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

        if iface["mtu"]:
            unit_stub["mtu"] = iface["mtu"]

        interface_vlan_id = None
        if iface["mode"] == "ACCESS":
            if not iface.get("untagged_vlan"):
                l.error(
                    f"Interface {iface['name']} on device {self.device['name']} is mode ACCESS but has no untagged vlan, skipping"
                )
                return
            unit_stub["vlan"] = iface["untagged_vlan"]["vid"]
            interface_vlan_id = iface["untagged_vlan"]["id"]

        if outer_tag := iface.get('custom_fields', {}).get("outer_tag", None):
                unit_stub["vlan"] = int(outer_tag)

        l2vpn_vlan_attached = interface_vlan_id and self.l2vpn_vlan_terminations.get(interface_vlan_id)
        l2vpn_interface_attached = self.l2vpn_interface_terminations.get(iface["id"])

        l2vpn = l2vpn_vlan_attached or l2vpn_interface_attached
        if l2vpn:
            if l2vpn['type'] in ["VPWS", "EVPL"] and unit_stub.get('vlan'):
                unit_stub["encapsulation"] = "vlan-ccc"
            elif l2vpn['type'] in ["MPLS_EVPN", "VXLAN_EVPN"]:
                unit_stub["encapsulation"] = "vlan-bridge"

            # We need to collect the used L2VPNs for rendering those afterwards in other places within the configuration.
            if not self.l2vpns.get(l2vpn["id"]):
                l2vpn["interfaces"] = []
                l2vpn["vlan"] = unit_stub.get("vlan", None)
                self.l2vpns[l2vpn["id"]] = l2vpn

            self.l2vpns[l2vpn["id"]]["interfaces"].append(iface)

        if tags.has_key("dhcp"):
            unit_stub["dhcp_profile"] = tags.get_from_key("dhcp")

        if tags.has("unnumbered"):
            unit_stub["unnumbered"] = True

        if iface["vrf"]:
            vrfid = iface["vrf"]["id"]

            # We need to collect the used L3VPNs for rendering those afterwards in other places within the configuration.
            if vrfid not in self.l3vpns:
                vrf_object = [vrf for vrf in self.vrfs if vrf["id"] == vrfid][0]
                vrf_object["interfaces"] = []
                self.l3vpns[vrfid] = vrf_object

            self.l3vpns[iface["vrf"]["id"]]["interfaces"].append(iface["name"])

        return name, unit_stub

    def serialize(self):
        device_stub = {
            f"device_model": self.device["device_type"]["slug"],
            f"platform": self.device["platform"]["slug"],
            f"serial": self.device["serial"],
        }
        interfaces = {}

        for interface in self.device["interfaces"]:
            tags = Tags(interface.get('tags'))

            # Sub Interfaces contains . in names, we render them within the parent, so we ignore those if the parent exists
            if "." in interface["name"]:
                base_name = interface["name"].split(".")[0]
                if not next(
                        filter(
                            lambda i: i["name"] == base_name,
                            self.device["interfaces"],
                        ),
                        None,
                ):
                    # Note: We can add an interface at this point, but we are not able to
                    # infer anything. Therefore, we cannot infer the type of this interface and only use this interface
                    # for rendering, not for generating additional configuration.
                    # If your configuration needs for example an explicit loopback interface, you can create this manually.
                    self.device["interfaces"].append(
                        {
                            "name": base_name,
                            "enabled": True,
                            "description": None,
                            "mtu": None,
                            "lag": None,
                        }
                    )
                continue

            interface_stub = {}

            if not interface["enabled"]:
                interface_stub["shutdown"] = True

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

            for fec in tags.get_from_key("fec"):
                if not interface_stub.get("gigether"):
                    interface_stub["gigether"] = {}
                match fec:
                    case "off":
                        interface_stub["gigether"]["fec"] = "none"
                    case "baser":
                        interface_stub["gigether"]["fec"] = "fec74"
                    case "rs":
                        interface_stub["gigether"]["fec"] = "fec91"
                    case _:
                        l.error(f"FEC mode {fec} on interface {interface['name']} is not known, ignoring")

            if interface.get("type") == "LAG":
                interface_stub["type"] = "lag"
            elif interface.get("type") == "LOOPBACK":
                interface_stub["type"] = "loopback"
            elif interface.get("type") == "VIRTUAL":
                interface_stub["type"] = "virtual"
            elif tags.has_key("access"):
                interface_stub["type"] = "access"
            elif "BASE" in interface.get("type", ""):
                interface_stub["type"] = "physical"

            if tags.has_key("access"):
                interface_stub["port_profile"] = tags.get_from_key("access")

            # If this interface is just part of a lag, we just connect those together and leave
            # the interface alone. Heavy configuration is done on the LAG interface afterwards.
            if interface["lag"]:
                lag_interface = next(
                    filter(
                        lambda i: i["id"] == interface["lag"]["id"],
                        self.device["interfaces"],
                    )
                )
                interface_stub["type"] = "lag_member"
                interface_stub["lag_parent"] = lag_interface["name"]
                interfaces[interface["name"]] = interface_stub
                continue

            sub_interfaces = self._get_subinterfaces(
                self.device["interfaces"], interface["name"]
            )
            if len(sub_interfaces) > 0:
                is_loopback = interface_stub.get("type") == "loopback"
                for si in sub_interfaces:
                    name, unit = self._get_unit(si)
                    sub_num = int(name or '0')
                    if not is_loopback and sub_num != 0 and not unit.get("vlan", None):
                        l.error(f"Sub interface {si['name']} does not have a access VLAN configured, skipping...")
                        continue

                    l2vpn = self.l2vpn_interface_terminations.get(si["id"])
                    if len(sub_interfaces) == 1 and l2vpn and l2vpn['type'] in ["VPWS", "EPL"] and not si.get('vlan'):
                        interface_stub["encapsulation"] = "ethernet-ccc"

                    if not interface_stub.get("units"):
                        interface_stub["units"] = {}

                    interface_stub["units"][sub_num] = unit

            interfaces[interface["name"]] = interface_stub

        device_stub[f"interfaces"] = interfaces

        routing_options = {}

        rib = self._get_vrf_rib(self.device["staticroute_set"], None)
        if len(rib) > 0:
            routing_options["rib"] = rib

        if len(routing_options) > 0:
            device_stub[f"routing_options"] = routing_options

        l2circuits = {}
        routing_instances = {}

        routing_instances[self.mgmt_routing_instance] = {
            "description": "MGMT-ROUTING-INSTANCE",
        }

        if interfaces.get(self.mgmt_interface, {}).get("units", {}).get(0):
            routing_instances[self.mgmt_routing_instance]["routing_options"] = {
                "rib": {
                    f"{self.mgmt_routing_instance}.inet.0": {
                        "static": {
                            "0.0.0.0/0": {
                                "next_hop": next(
                                    ipaddress.ip_network(
                                        next(iter(interfaces[self.mgmt_interface]["units"][0]["families"]["inet"]["address"].keys())),
                                        strict=False,
                                    ).hosts()
                                ).compressed
                            }
                        }
                    }
                }
            }

        if interfaces.get(self.lo_interface, {}).get("units", {}).get(0):
            router_id = next(iter(interfaces[self.lo_interface]["units"][0]["families"]["inet"]["address"].keys())).split("/")[0]

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
            elif l2vpn['type'] == "EPL" or l2vpn['type'] == "EVPL":
                l2vpn_interfaces = {};
                for i in l2vpn["interfaces"]:
                    for termination in l2vpn["terminations"]:
                        if termination["assigned_object"]["id"] == i["id"]:
                            id_local = int(termination["id"]) + 1000000
                        else:
                            id_remote = int(termination["id"]) + 1000000
                            remote_device = termination["assigned_object"]["device"]["name"]
                            remote_interfaces = termination["assigned_object"]["device"]["interfaces"]

                    if not remote_interfaces:
                        l.error("Found no remote interface, skipping...")
                        continue

                    # [TODO]: Refactor this.
                    # We need the Loopback IP of the peer device.
                    # We potentially need data for a device that's not listed in `cosmo.yml`
                    # So we fetch all interfaces of the peer device and use some
                    # dirty heuristics to assume the correct loxopback IP
                    # I wanted to implement this in GraphQL, but Netbox lacks the needed filters.
                    # We pick a `virtual` interface which is not in a VRF and which parent is a `loopback`
                    # Then we pick the first IPv4 address.
                    for a in remote_interfaces:
                        if a["vrf"] == None and a["parent"] and a["parent"]["type"] == "LOOPBACK" and a["parent"]["name"].startswith("lo"):
                            for ip in a['ip_addresses']:
                                ipa = ipaddress.ip_network(ip["address"], strict=False)
                                if ipa.version == 4:
                                    remote_ip = str(ipa[0])
                                    break

                    l2vpn_interfaces[i["name"]] = {
                        "local_label": id_local,
                        "remote_label": id_remote,
                        "remote_ip": remote_ip,
                    }

                l2circuits[l2vpn["name"].replace("WAN: ", "")] = {
                    "interfaces": l2vpn_interfaces,
                    "description": f"{l2vpn['type']}: " + l2vpn["name"].replace("WAN: ", "") + " via " + remote_device,
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
        device_stub[f"routing_instances"] = routing_instances
        device_stub[f"l2circuits"] = l2circuits

        return device_stub


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
