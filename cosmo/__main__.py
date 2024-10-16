import ipaddress
import json
import os
import sys
import pathlib
import warnings

import yaml
import argparse

from cosmo.graphqlclient import GraphqlClient
from cosmo.serializer import RouterSerializer, SwitchSerializer, AbstractRecoverableError



def info(string: str) -> None:
    print("[INFO] " + string)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Automagically generate filter lists and BGP sessions for WAN-Core network"
    )
    parser.add_argument('--limit', default=[], metavar="STRING", action="append",
                        help='List of hosts to generate configurations')
    parser.add_argument('--config', '-c', default='cosmo.yml', metavar="CFGFILE",
                        help='Path of the yaml config file to use')

    args = parser.parse_args()

    if len(args.limit) > 1:
        allowed_hosts = args.limit
    elif len(args.limit) == 1 and args.limit[0] != "ci":
        allowed_hosts = args.limit[0].split(',')
    else:
        allowed_hosts = None

    if not os.path.isfile(args.config):
        raise Exception("Missing {}, please provide a configuration.".format(args.config))

    cosmo_configuration = {}
    with open(args.config, 'r') as cfg_file:
        cosmo_configuration = yaml.safe_load(cfg_file)

    info(f"Fetching information from Netbox, make sure VPN is enabled on your system.")

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

    for vrf in cosmo_data["vrf_list"]:
        if len(vrf["export_targets"]) > 1 or len(vrf["import_targets"]) > 1:
            warnings.warn(f"Currently we only support one import/export target per VRF. {vrf['name']} has {len(vrf['import_targets'])} import targets and {len(vrf['export_targets'])} export targets")
            continue

    for device in cosmo_data["device_list"]:

        if 'fqdnSuffix' in cosmo_configuration:
            device_fqdn = f"{str(device['name']).lower()}.{cosmo_configuration['fqdnSuffix']}"
        else:
            device_fqdn = f"{str(device['name']).lower()}"

        if allowed_hosts and device['name'] not in allowed_hosts and device_fqdn not in allowed_hosts:
            continue

        info(f"Generating {device_fqdn}")

        content = None
        try:
            if device['name'] in cosmo_configuration['devices']['router']:
                serializer = RouterSerializer(device, cosmo_data['l2vpn_list'], cosmo_data["vrf_list"])
                content = serializer.serialize()
            elif device['name'] in cosmo_configuration['devices']['switch']:
                serializer = SwitchSerializer(device)
                content = serializer.serialize()
        except AbstractRecoverableError as e:
            warnings.warn(f"{device['name']} serialization error \"{e}\", skipping ...")
            continue

        match cosmo_configuration['output_format']:
            case 'ansible':
                pathlib.Path(f"./host_vars/{device_fqdn}").mkdir(parents=True, exist_ok=True)

                if device['name'] in cosmo_configuration['devices']['router']:
                    with open(f"./host_vars/{device_fqdn}/generated-cosmo.yml", "w") as yaml_file:
                        yaml.dump(content, yaml_file, default_flow_style=False)
                else:
                    with open(f"./host_vars/{device_fqdn}/generated-cosmo.yml", "w") as yaml_file:
                        yaml.dump(content, yaml_file, default_flow_style=False)
            case 'nix':
                pathlib.Path(f"./machines/{device_fqdn}").mkdir(parents=True, exist_ok=True)

                if device['name'] in cosmo_configuration['devices']['router']:
                    with open(f"./machines/{device_fqdn}/generated-cosmo.json", "w") as json_file:
                        json.dump(content, json_file, indent=4)
                else:
                    with open(f"./machines/{device_fqdn}/generated-cosmo.json", "w") as json_file:
                        json.dump(content, json_file, indent=4)
            case other:
                raise Exception(f"unsupported output format {other}")
                return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
