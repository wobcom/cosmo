import ipaddress
import re
import json
import warnings
import abc
from collections import defaultdict


class AbstractRecoverableError(Exception, abc.ABC):
    pass


class DeviceSerializationError(AbstractRecoverableError):
    pass


class InterfaceSerializationError(AbstractRecoverableError):
    pass


class Tags:
    def __init__(self, tags):
        if tags is None:
            tags = []
        self.tags = tags

    # check if tag exists
    def has(self, item, key=None):
        if key:
            return item.lower() in self.get_from_key(key)
        else:
            return item.lower() in [t["slug"].lower() for t in self.tags]

    # return all sub-tags using a key
    def get_from_key(self, key):
        delimiter = ":"
        keylen = len(key) + len(delimiter)
        return [t['name'][keylen:] for t in self.tags if t['name'].lower().startswith(key.lower() + delimiter)]

    # check if there are any tags with a specified key
    def has_key(self, key):
        return len(self.get_from_key(key)) > 0


class IPHierarchyNetwork:
    primaryIP = None
    secondaryIPs = None

    def __init__(self):
        self.primaryIP = None
        self.secondaryIPs = list()

    def add_ip(self, ipa, is_secondary=False):
        if is_secondary:
            self.secondaryIPs.append(ipa)
        elif self.primaryIP is None:
            self.primaryIP = ipa
        else:
            warnings.warn(
                f"Ignoring {ipa}, because its marked as a primary IP and an primary IP was already given with {self.primaryIP}")

    def render_addresses(self):
        retVal = {}
        primaryMarker = {"primary": True} if len(self.secondaryIPs) > 0 else {}
        secondaryMarker = {"secondary": True} if len(self.secondaryIPs) > 0 else {}
        retVal[self.primaryIP.with_prefixlen] = primaryMarker
        secondaryIPs = {x.with_prefixlen: secondaryMarker for x in self.secondaryIPs}
        retVal.update(secondaryIPs)
        return retVal


class RouterSerializerConfig:
    def __init__(self, config={}):
        self.config = config

    @property
    def allow_private_ips(self):
        return self.config.get("allow_private_ips", False)


class RouterSerializer:
    def __init__(self, cfg, device, l2vpn_list, vrfs, loopbacks):
        try:
            match device["platform"]["manufacturer"]["slug"]:
                case 'juniper':
                    self.mgmt_routing_instance = "mgmt_junos"
                    self.mgmt_interface = "fxp0"
                    self.bmc_interface = None
                case 'rtbrick':
                    self.mgmt_routing_instance = "mgmt"
                    self.mgmt_interface = "ma1"
                    self.bmc_interface = "bmc0"
                case other:
                    raise DeviceSerializationError(f"unsupported platform vendor: {other}")
                    return
        except KeyError as ke:
            raise KeyError(f"missing key in device info, can't continue.") from ke

        self.cfg = cfg
        self.device = device
        self.l2vpn_vlan_terminations, self.l2vpn_interface_terminations = RouterSerializer.process_l2vpn_terminations(l2vpn_list)
        self.vrfs = vrfs
        self.loopbacks = loopbacks

        self.l2vpns = {}
        self.l3vpns = {}
        self.routing_instances = {}

    @staticmethod
    def process_l2vpn_terminations(l2vpn_list):
        l2vpn_vlan_terminations = {}
        l2vpn_interface_terminations = {}
        for l2vpn in l2vpn_list:
            if not l2vpn["name"].startswith("WAN: "):
                continue
            if l2vpn['type'].lower() == "vpws" and len(l2vpn['terminations']) != 2:
                warnings.warn(
                    f"VPWS circuits are only allowed to have two terminations. {l2vpn['name']} has {len(l2vpn['terminations'])} terminations, ignoring...")
                continue
            for termination in l2vpn["terminations"]:
                if not termination["assigned_object"] or termination['assigned_object']['__typename'] not in [
                    "VLANType", "InterfaceType"]:
                    warnings.warn(f"Found unsupported L2VPN termination in {l2vpn['name']}, ignoring...")
                    continue
                if l2vpn['type'].lower() == "vpws" and termination['assigned_object']['__typename'] != "InterfaceType":
                    warnings.warn(
                        f"Found non-interface termination in L2VPN {l2vpn['name']}, ignoring... VPWS only supports interace terminations.")
                    continue
                if termination['assigned_object']['__typename'] == "VLANType":
                    l2vpn_vlan_terminations[str(termination["assigned_object"]['id'])] = l2vpn
                elif termination['assigned_object']['__typename'] == "InterfaceType":
                    l2vpn_interface_terminations[str(termination["assigned_object"]['id'])] = l2vpn

        return l2vpn_vlan_terminations, l2vpn_interface_terminations

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
                    table = vrf + "." + table

                if table not in rib:
                    rib[table] = {"static": {}}
                rib[table]["static"][route["prefix"]["prefix"]] = r
        return rib

    def _get_unit(self, iface, is_loopback=False):
        unit_stub = {}
        name = iface['name'].split(".")[1]

        ipv4Family = defaultdict(lambda: IPHierarchyNetwork())
        ipv6Family = defaultdict(lambda: IPHierarchyNetwork())
        policer = {}
        tags = Tags(iface.get("tags"))
        is_edge = tags.has_key("edge")
        is_mgmt = iface['name'].startswith(self.mgmt_interface) or (self.bmc_interface and iface['name'].startswith(self.bmc_interface))
        sample = is_edge and not tags.has("customer", "edge") and not tags.has("disable_sampling")

        for ip in iface["ip_addresses"]:
            ipa = ipaddress.ip_interface(ip["address"])
            role = ip.get("role", None)
            is_secondary = role and role.lower() == "secondary"

            # abort if a private IP is used on a unit without a VRF
            # we use !is_global instead of is_private since the latter ignores 100.64/10
            if not iface["vrf"] and not ipa.is_global and not is_mgmt and not self.cfg.allow_private_ips:
                raise InterfaceSerializationError(f"Private IP {ipa} used on interface {iface['name']} in default VRF for device {self.device['name']}. Did you forget to configure a VRF?")

            # We only want /32 on loopback interfaces.
            if is_loopback and not ipa.network.prefixlen == ipa.max_prefixlen and not iface["vrf"]:
                raise InterfaceSerializationError(f"IP {ipa} is not a valid loopback IP address.")

            if ipa.version == 4:
                ipv4Family[ipa.network].add_ip(ipa, is_secondary)
            elif ipa.version == 6:
                ipv6Family[ipa.network].add_ip(ipa, is_secondary)

        if tags.has_key("policer"):
            policer["input"] = "POLICER_" + tags.get_from_key("policer")[0]
            policer["output"] = "POLICER_" + tags.get_from_key("policer")[0]
        if tags.has_key("policer_in"):
            policer["input"] = "POLICER_" + tags.get_from_key("policer_in")[0]
        if tags.has_key("policer_out"):
            policer["output"] = "POLICER_" + tags.get_from_key("policer_out")[0]

        if policer:
            unit_stub["policer"] = policer
        if iface["mac_address"]:
            unit_stub["mac_address"] = iface["mac_address"]

        families = {}
        if len(ipv4Family) > 0:
            families["inet"] = {
                'address': {}
            }
            for network, ipHierarchyNetwork in ipv4Family.items():
                families["inet"]["address"].update(ipHierarchyNetwork.render_addresses())

            if is_edge:
                families["inet"]["filters"] = ["input-list [ EDGE_FILTER ]"]
            if sample:
                families["inet"]["sampling"] = True
            if tags.has("peering-ixp", "edge"):
                families["inet"]["policer"] = ["arp POLICER_IXP_ARP"]
            if tags.has_key("urpf") and not tags.has("disable", "urpf"):
                families["inet"]["rpf_check"] = {"mode": tags.get_from_key("urpf")[0]}
        if len(ipv6Family) > 0:
            families["inet6"] = {
                'address': {}
            }
            for network, ipHierarchyNetwork in ipv6Family.items():
                families["inet6"]["address"].update(ipHierarchyNetwork.render_addresses())
            if is_edge:
                families["inet6"]["filters"] = ["input-list [ EDGE_FILTER_V6 ]"]
            if sample:
                families["inet6"]["sampling"] = True
            if tags.has_key("urpf") and "disable" not in tags.get_from_key("urpf"):
                families["inet6"]["rpf_check"] = {"mode": tags.get_from_key("urpf")[0]}
            if iface.get("custom_fields", {}).get("ipv6_ra", False):
                families["inet6"]["ipv6_ra"] = True

        if tags.has("core"):

            parent_mtu = iface['parent']['mtu'] if iface.get('parent') else None
            mtu = iface['mtu'] or parent_mtu
            # Note: There is a legacy use-case with a 1500 MTU in the network, which is normally not used.
            # We allow this configuration specifically.
            is_sonderlocke_mtu = tags.has( "mtu", "sonderlocke")

            if not is_sonderlocke_mtu and mtu is not None and mtu not in [9216, 9600, 9230, 9586, 9116]:
                warnings.warn(f"Interface {iface['name']} on device {self.device['name']} has MTU {iface['mtu']} set, which is not one of the allowed values for core interfaces.")

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
        if iface["mode"] and iface["mode"].lower() == "access":
            if not iface.get("untagged_vlan"):
                warnings.warn(
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
            if l2vpn['type'].lower() in ["vpws", "evpl"] and unit_stub.get('vlan'):
                unit_stub["encapsulation"] = "vlan-ccc"
            # Note: Netbox v4 uses minus, Netbox v3 uses underscore.
            elif l2vpn['type'].lower() in ["mpls_evpn", "vxlan_evpn", "mpls-evpn", "vxlan-evpn"]:
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
                # get loopback interface of the same VRF for address borrowing
                unit_stub["unnumbered_interface"] = next(
                    filter(
                        lambda i: (i["name"].startswith("lo") and i["vrf"] and i["vrf"]["id"] == iface["vrf"]["id"]),
                        self.device["interfaces"],
                    )
                )["name"]

        if iface["vrf"]:
            vrfid = iface["vrf"]["id"]

            # We need to collect the used L3VPNs for rendering those afterwards in other places within the configuration.
            if vrfid not in self.l3vpns:
                vrf_object = [vrf for vrf in self.vrfs if vrf["id"] == vrfid][0]
                vrf_object["interfaces"] = []
                self.l3vpns[vrfid] = vrf_object

            self.l3vpns[iface["vrf"]["id"]]["interfaces"].append(iface["name"])

        if tags.has("cpe", "bgp"):
            groupname = "CPE_" + iface["name"].replace(".", "-").replace("/", "-")

            if iface["vrf"]:
                vrfname = [v["name"] for v in self.vrfs if v["id"] == iface["vrf"]["id"]][0]
            else:
                vrfname = "default"

            # ensure paths exist
            if not vrfname in self.routing_instances:
                self.routing_instances[vrfname] = {}
            if not "protocols" in self.routing_instances[vrfname]:
                self.routing_instances[vrfname] = {"protocols": {"bgp": {"groups": {}}}}

            policy_v4 = {"import_list": []}
            policy_v6 = {"import_list": []}
            if vrfname == "default":
                policy_v4["export"] = "DEFAULT_V4"
                policy_v6["export"] = "DEFAULT_V6"

            if iface["parent"]:
                parent = [i for i in self.device["interfaces"] if i["id"] == iface["parent"]["id"]][0]
                connected_element = next(iter(parent["connected_endpoints"]), None)
                if connected_element is None:
                    warnings.warn(f"Interface {iface['name']} on device {self.device['name']} has a bgp:cpe tag on it without a connected device, skipping...")
                else:
                    cpe = connected_element["device"]

                    addresses = set()
                    for a in cpe["interfaces"]:
                        for i in a["ip_addresses"]:
                            if cpe["primary_ip4"] and i["address"] == cpe["primary_ip4"]["address"]:
                                continue
                            addresses.add(ipaddress.ip_network(i['address'], strict=False))

                    policy_v4["import_list"] = [a.with_prefixlen for a in addresses if type(a) is ipaddress.IPv4Network]
                    policy_v6["import_list"] = [a.with_prefixlen for a in addresses if type(a) is ipaddress.IPv6Network]

            self.routing_instances[vrfname]["protocols"]["bgp"]["groups"][groupname] = {
                "any_as": True,
                "link_local_nexthop_only": True,
                "family": {
                    "ipv4_unicast": {
                        "extended_nexthop": True,
                        "policy": policy_v4,
                    },
                    "ipv6_unicast": {
                        "policy": policy_v6,
                    },
                },
                "neighbors": [
                    {"interface": iface["name"]}
                ]
            }

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
                    warnings.warn(f"Interface speed {speed} on interface {interface['name']} is not known, ignoring")

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
                        warnings.warn(f"FEC mode {fec} on interface {interface['name']} is not known, ignoring")

            if interface.get("type", '').lower() == "lag" and tags.has_key("access"):
                interface_stub["type"] = "lag-access"
            elif interface.get("type", '').lower() == "lag":
                interface_stub["type"] = "lag"
            elif interface.get("type", '').lower() == "loopback":
                interface_stub["type"] = "loopback"
            elif interface.get("type", '').lower() == "virtual":
                interface_stub["type"] = "virtual"
            elif tags.has_key("access"):
                interface_stub["type"] = "access"
            elif "base" in interface.get("type", "").lower():
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
                is_parent_loopback = interface_stub.get("type") == "loopback"
                is_parent_virtual = interface_stub.get("type") == "virtual"
                for si in sub_interfaces:
                    if not si['enabled']:
                        continue

                    name, unit = self._get_unit(si, is_loopback=is_parent_loopback)
                    sub_num = int(name or '0')
                    if not is_parent_loopback and not is_parent_virtual and sub_num != 0 and not unit.get("vlan", None):
                        warnings.warn(f"Sub interface {si['name']} does not have a access VLAN configured, skipping...")
                        continue

                    l2vpn = self.l2vpn_interface_terminations.get(si["id"])
                    if len(sub_interfaces) == 1 and l2vpn and l2vpn['type'].lower() in ["vpws", "epl", "evpl"] \
                            and not si.get('vlan') and not si.get('custom_fields', {}).get("outer_tag", None):
                        interface_stub["encapsulation"] = "ethernet-ccc"

                    if sub_num == 0 and "vlan" in unit:
                        interface_stub["native_vlan"] = unit["vlan"]

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

        self.routing_instances[self.mgmt_routing_instance] = {
            "description": "MGMT-ROUTING-INSTANCE",
        }

        if interfaces.get(self.mgmt_interface, {}).get("units", {}).get(0):
            self.routing_instances[self.mgmt_routing_instance]["routing_options"] = {
                "rib": {
                    f"{self.mgmt_routing_instance}.inet.0": {
                        "static": {
                            "0.0.0.0/0": {
                                "next_hop": next(
                                    ipaddress.ip_network(
                                        next(iter(interfaces[self.mgmt_interface]["units"][0]["families"]["inet"][
                                                      "address"].keys())),
                                        strict=False,
                                    ).hosts()
                                ).compressed
                            }
                        }
                    }
                }
            }

        router_id = str(ipaddress.ip_interface(self.loopbacks[self.device['name']]['ipv4']).ip)

        for _, l2vpn in self.l2vpns.items():
            if l2vpn['type'].lower() in ["vxlan_evpn", "vxlan-evpn"]:
                self.routing_instances[l2vpn["name"].replace("WAN: ", "")] = {
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
            elif l2vpn['type'].lower() in ["mpls_evpn", "mpls-evpn"]:
                self.routing_instances[l2vpn["name"].replace("WAN: ", "")] = {
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
            elif l2vpn['type'].lower() == "vpws":
                l2vpn_interfaces = {}
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

                self.routing_instances[l2vpn["name"].replace("WAN: ", "")] = {
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
            elif l2vpn['type'].lower() == "epl" or l2vpn['type'].lower() == "evpl":
                l2vpn_interfaces = {}
                if len(l2vpn["terminations"]) != 2:
                    warnings.warn(f"EPL or EVPL {l2vpn['name']} has not exact two terminations...")
                    continue

                local_termination_device = next(filter(
                    lambda term: term["assigned_object"]["device"]['name'] == self.device['name'], l2vpn["terminations"]
                ))
                other_termination_device = next(filter(
                    lambda term: term["id"] != local_termination_device['id'], l2vpn["terminations"]
                ))
                other_device = other_termination_device["assigned_object"]["device"]["name"]

                for termination in l2vpn["terminations"]:
                    # If interface is None, it is not generated yet, since l2vpn['interfaces'] is initialzied lazy.
                    # This can also happen, if you have device not in your generation list.
                    interface = next(filter(lambda i: i['id'] == termination['assigned_object']['id'], l2vpn['interfaces']), None)
                    if not interface:
                        continue

                    # Note: We need the other termination here.
                    # This might be a remote termination or another local termination, so we cannot just check for another device name here.
                    other_termination = next(filter(
                        lambda term: term["id"] != termination['id'], l2vpn["terminations"]
                    ))

                    id_local = int(termination["id"]) + 1000000
                    id_remote = int(other_termination["id"]) + 1000000
                    other_device = other_termination["assigned_object"]["device"]["name"]
                    other_ip = ipaddress.ip_interface(self.loopbacks[other_device]['ipv4'])

                    l2vpn_interfaces[interface["name"]] = {
                        "local_label": id_local,
                        "remote_label": id_remote,
                        "remote_ip": str(other_ip.ip),
                    }

                l2circuits[l2vpn["name"].replace("WAN: ", "")] = {
                    "interfaces": l2vpn_interfaces,
                    "description": f"{l2vpn['type'].upper()}: " + l2vpn["name"].replace("WAN: ",
                                                                                        "") + f" via {other_device}",
                }

        for _, l3vpn in self.l3vpns.items():
            if l3vpn["rd"]:
                rd = router_id + ":" + l3vpn["rd"]
            elif len(l3vpn["export_targets"]) > 0:
                rd = router_id + ":" + l3vpn["id"]
            else:
                rd = None

            routing_options = {}
            rib = self._get_vrf_rib(self.device["staticroute_set"], l3vpn["name"])
            if len(rib) > 0:
                routing_options["rib"] = rib

            if l3vpn["name"] not in self.routing_instances:
                self.routing_instances[l3vpn["name"]] = {}
            self.routing_instances[l3vpn["name"]].update({
                "interfaces": l3vpn["interfaces"],
                "description": l3vpn["description"],
                "instance_type": "vrf",
                "route_distinguisher": rd,
                "import_targets": [target["name"] for target in l3vpn["import_targets"]],
                "export_targets": [target["name"] for target in l3vpn["export_targets"]],
                "routing_options": routing_options,
            })

        device_stub[f"routing_instances"] = self.routing_instances
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

            if interface["type"] and interface['type'].lower() == "lag":
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
                    warnings.warn(f"Interface speed {speed} on interface {interface['name']} is not known, ignoring")

            for fec in tags.get_from_key("fec"):
                if fec in ["off", "rs", "baser"]:
                    interface_stub["fec"] = fec
                else:
                    warnings.warn(f"FEC mode {fec} on interface {interface['name']} is not known, ignoring")

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
