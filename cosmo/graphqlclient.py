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
                staticroute_set {
                  interface {
                    name
                  }
                  vrf {
                    name
                  }
                  prefix {
                    prefix
                    family {
                      value
                    }
                 }
                 next_hop {
                   address
                 }
                 metric
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
              l2vpn_list {
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
                        interfaces (type: "virtual") {
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

        query = query_template.substitute(
            device_array=json.dumps(device_config['router'] + device_config['switch'])
        )

        r = self.query(query)

        return r['data']
