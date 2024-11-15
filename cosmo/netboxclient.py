import json
import time
from multiprocessing.pool import Pool
from string import Template
from urllib.parse import urlencode

import requests


class NetboxClient:
    def __init__(self, url, token):
        self.url = url
        self.token = token

        self.version = self.query_version()

        if self.version.startswith("4."):
            print("[INFO] Using version 4.x strategy...")
            self.child_client = NetboxV4Strategy(url, token)
        else:
            raise Exception("Unknown Version")

    def query_version(self):
        r = requests.get(
            f"{self.url}/api/status/",
            headers={
                "Authorization": f"Token {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        if r.status_code != 200:
            raise Exception("Error querying api: " + r.text)

        json = r.json()
        return json['netbox-version']

    def get_data(self, device_config):
        start_time = time.perf_counter()
        data = self.child_client.get_data(device_config)
        end_time = time.perf_counter()
        diff_time = end_time - start_time
        print(f"[INFO] Data fetching took {round(diff_time, 2)} s...")

        return data


class NetboxStrategy:
    def __init__(self, url, token):
        self.url = url
        self.token = token

    def query(self, query):
        r = requests.post(
            f"{self.url}/graphql/",
            json={"query": query},
            headers={
                "Authorization": f"Token {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        if r.status_code != 200:
            raise Exception("Error querying api: " + r.text)

        return r.json()

    def query_rest(self, path, queries):
        q = urlencode(queries, doseq=True)
        url = f"{self.url}/{path}?{q}"

        return_array = list()

        while url is not None:
            r = requests.get(
                url,
                headers={
                    "Authorization": f"Token {self.token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )

            if r.status_code != 200:
                raise Exception("Error querying api: " + r.text)

            data = r.json()

            url = data['next']
            return_array.extend(data['results'])

        return return_array


class NetboxV4Strategy(NetboxStrategy):

    def get_data(self, device_config):
        device_list = device_config['router'] + device_config['switch']

        with Pool() as pool:
            device_data = pool.apply_async(self.get_base_data, (device_list,))
            l2vpn_data = pool.apply_async(self.get_l2vpn_data, ())
            connected_devices_data = pool.apply_async(self.get_connected_devices_data, ())
            static_route_data = pool.apply_async(self.get_static_route_data, (device_list,))

            device_data = device_data.get()
            l2vpn_data = l2vpn_data.get()
            connected_devices_data = connected_devices_data.get()
            static_route_data = static_route_data.get()

        graphql_data = {
            **device_data,
            **l2vpn_data,
        }

        for d in graphql_data['device_list']:
            device_static_routes = list(filter(lambda sr: str(sr['device']['id']) == d['id'], static_route_data))
            d['staticroute_set'] = device_static_routes

            for interface in d['interfaces']:
                cd_interface = next(filter(lambda i: i["id"] == interface["id"], connected_devices_data['interface_list']), None)
                if not cd_interface:
                    continue

                parent_interface = next(filter(lambda i: i['id'] == cd_interface['parent']['id'], d['interfaces']), None)
                parent_interface['connected_endpoints'] = cd_interface['parent']['connected_endpoints']

        return graphql_data

    def get_static_route_data(self, device_list):
        static_routes = self.query_rest("api/plugins/routing/staticroutes/", {"device": device_list})
        return static_routes

    def get_base_data(self, device_list):
        query_template = Template(
            """
            query {
              device_list(filters: {
                name: { in_list: $device_array },
              }) {
                id
                name
                serial

                device_type {
                  slug
                }
                platform {
                  manufacturer {
                    slug
                  }
                  slug
                }
                primary_ip4 {
                  address
                }

                interfaces {
                  id
                  name
                  enabled
                  type
                  mode
                  mtu
                  mac_address
                  description
                  vrf {
                    id
                  }
                  lag {
                    id
                  }
                  ip_addresses {
                    address
                  }
                  untagged_vlan {
                    id
                    name
                    vid
                  }
                  tagged_vlans {
                    id
                    name
                    vid
                  }
                  tags {
                    name
                    slug
                  }
                  parent {
                    id
                  }
                  custom_fields
                }
              }
              vrf_list {
                id
                name
                description
                rd
                export_targets {
                  name
                }
                import_targets {
                  name
                }
              }

            }"""
        )

        query = query_template.substitute(
            device_array=json.dumps(device_list)
        )
        return self.query(query)['data']

    def get_l2vpn_data(self):
        l2vpn_template = Template(
            """
            query {
                l2vpn_list (filters: {name: {starts_with: "WAN: "}}) {
                    id
                    name
                    type
                    identifier
                    terminations {
                      id
                      assigned_object {
                        __typename
                        ... on VLANType {
                          id
                        }
                        ... on InterfaceType {
                          id
                          device {
                            name
                            interfaces (filters:{type: {exact: "virtual"}}) {
                              ip_addresses {
                                address
                              }
                              parent {
                                name
                                type
                              }
                              vrf {
                                id
                              }
                            }
                          }
                        }
                      }
                    }
                }
              }
              """

        )

        return self.query(l2vpn_template.substitute())['data']

    def get_connected_devices_data(self):
        connected_devices_template = Template(
            """
            query {
              interface_list(filters: { tag: "bgp_cpe" }) {
                id,
                parent {
                  id,
                  connected_endpoints {
                    ... on InterfaceType {
                      name
                      device {
                        primary_ip4 {
                          address
                        }
                        interfaces {
                          ip_addresses {
                            address
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
            """
        )

        return self.query(connected_devices_template.substitute())['data']
