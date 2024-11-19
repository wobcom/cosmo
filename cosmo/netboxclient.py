import json
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
        return self.child_client.get_data(device_config)


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
            }"""
        )

        device_list = device_config['router'] + device_config['switch']
        query = query_template.substitute(
            device_array=json.dumps(device_list)
        )

        r = self.query(query)
        graphql_data = r['data']

        static_routes = self.query_rest("api/plugins/routing/staticroutes/", {"device": device_list})

        for d in r['data']['device_list']:
            device_static_routes = list(filter(lambda sr: str(sr['device']['id']) == d['id'], static_routes))
            d['staticroute_set'] = device_static_routes

        return graphql_data
