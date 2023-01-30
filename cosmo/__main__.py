import ipaddress
import os
import sys
import pathlib

import yaml
import argparse

from cosmo.logger import Logger
from cosmo.graphqlclient import GraphqlClient
from cosmo.serializer import DeviceSerializer

l = Logger("__main__.py")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Automagically generate filter lists and BGP sessions for WAN-Core network"
    )
    parser.add_argument('--limit', default=[], metavar="STRING", action="append",
                        help='List of hosts to generate configurations')

    args = parser.parse_args()

    if len(args.limit) > 1:
        allowed_hosts = args.limit
    elif len(args.limit) == 1 and args.limit[0] != "ci":
        allowed_hosts = args.limit[0].split(',')
    else:
        allowed_hosts = None

    if not os.path.isfile('cosmo.yml'):
        l.error("Missing cosmo.yml, please provide a configuration.")
        return 1

    cosmo_configuration = {}
    with open('cosmo.yml', 'r') as cfg_file:
        cosmo_configuration = yaml.safe_load(cfg_file)

    l.hint(f"Fetching information from Netbox, make sure VPN is enabled on your system.")

    netbox_url = os.environ.get("NETBOX_URL")
    netbox_api_token = os.environ.get("NETBOX_API_TOKEN")

    if netbox_url is None:
        raise Exception("NETBOX_URL is empty.")
    if netbox_api_token is None:
        raise Exception("NETBOX_API_TOKEN is empty.")

    gql = GraphqlClient(url=netbox_url, token=netbox_api_token)
    cosmo_data = gql.get_data(cosmo_configuration['devices'])

    def noop(*args, **kwargs):
        pass

    yaml.emitter.Emitter.process_tag = noop
    pathlib.Path("./generated_vars").mkdir(parents=True, exist_ok=True)

    l2vpn_vlan_terminations = {}
    for l2vpn in cosmo_data["l2vpn_list"]:
        if not l2vpn["name"].startswith("WAN: "):
            continue
        for termination in l2vpn["terminations"]:
            if not termination["assigned_object"] or not termination['assigned_object']['__typename'] == "VLANType":
                l.warning(f"Found unsupported L2VPN termination in {l2vpn['name']}, ignoring...")
                continue
            l2vpn_vlan_terminations[str(termination["assigned_object"]['id'])] = l2vpn

    for device in cosmo_data["device_list"]:

        if allowed_hosts and device['name'] not in allowed_hosts:
            continue

        l.info(f"Generating {device['name']}")

        serializer = DeviceSerializer(device, l2vpn_vlan_terminations)
        content = serializer.serialize()
        if not content:
            continue

        with open("./generated_vars/device-" + device["name"] + ".yml", "w") as yaml_file:
            yaml.dump(content, yaml_file, default_flow_style=False)

    # Writing manifest

    device_manifest = {
        "junos__device_manifest": {}
    }
    for device in cosmo_data["device_list"]:
        if device['name'] not in cosmo_configuration['manifest']['devices']:
            continue

        loopback_interface = next(filter(lambda i: i['name'] == 'lo0.0', device["interfaces"]), None)
        if not loopback_interface:
            l.warning(f"{device['name']} is missing loopback interface, skipping..")

        ipv4s = []
        ipv6s = []

        for ip in loopback_interface["ip_addresses"]:
            ipa = ipaddress.ip_network(ip["address"], strict=False)
            if ipa.version == 4:
                ipv4s.append(ip)
            else:
                ipv6s.append(ip)

        if len(ipv4s) != 1:
            l.warning(f"{device['name']} should contain one IPv4 loopback address, but currently has {len(ipv4s)}")
            continue

        if len(ipv6s) != 1:
            l.warning(f"{device['name']} should contain one IPv4 loopback address, but currently has {len(ipv6s)}")
            continue

        device_manifest["junos__device_manifest"][device['name']] = {
            "loopbackIPv4": ipv4s[0]['address'],
            "loopbackIPv6": ipv6s[0]['address'],
        }

    l.info(f"Generating device manifest")
    with open("./generated_vars/device-manifest.yml", "w") as yaml_file:
        yaml.dump(device_manifest, yaml_file, default_flow_style=False)

    return 0


if __name__ == "__main__":
    sys.exit(main())
