import json
from string import Template

import requests


class GraphqlClient:
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

    def get_data(self, device_config):
        query_template = Template(
            """
            {
              device_list(
                name: $device_array,
              ) {
                __typename
                id
                name
                serial
                
                device_type {
                  slug
                }
                platform {
                  __typename
                  manufacturer {
                   __typename
                    slug
                  }
                  slug
                }
                primary_ip4 {
                  __typename
                  address
                }
                interfaces {
                  __typename
                  id
                  name
                  enabled
                  type
                  mode
                  mtu
                  mac_address
                  description
                  vrf {
                    __typename
                    id
                  }
                  lag {
                    __typename
                    id
                  }
                  ip_addresses {
                    __typename
                    address
                  }
                  untagged_vlan {
                    __typename
                    id
                    name
                    vid
                  }
                  tagged_vlans {
                    __typename
                    id
                    name
                    vid
                  }
                  tags {
                    __typename
                    name
                    slug
                  }
                  parent {
                    __typename
                    id
                  }
                  connected_endpoints {
                    __typename
                    ... on InterfaceType {
                      __typename
                      name
                      device {
                        __typename
                        primary_ip4 {
                          __typename
                          address
                        }
                        interfaces {
                          __typename
                          ip_addresses {
                            __typename
                            address
                          }
                        }
                      }
                    }
                  }
                  custom_fields
                }
                staticroute_set {
                  __typename
                  interface {
                    __typename
                    name
                  }
                  vrf {
                    __typename
                    name
                  }
                  prefix {
                    __typename
                    prefix
                    family {
                      __typename
                      value
                    }
                 }
                 next_hop {
                    __typename
                   address
                 }
                 metric
                }
              }
              vrf_list {
                __typename
                id
                name
                description
                rd
                export_targets {
                  __typename
                  name
                }
                import_targets {
                  __typename
                  name
                }
              }
              l2vpn_list {
                __typename
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
                      __typename
                      id
                      device {
                        __typename
                        name
                        interfaces (type: "virtual") {
                          __typename
                          ip_addresses {
                            __typename
                            address
                          }
                          parent {
                            __typename
                            name
                            type
                          }
                          vrf {
                            __typename
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

        query = query_template.substitute(
            device_array=json.dumps(device_config['router'] + device_config['switch'])
        )

        r = self.query(query)

        return r['data']
