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

    def get_data(self, device_list):
        query_template = Template(
            """
            {
              device_list(
                name: $device_array,
                manufacturer: "juniper"
              ) {
                id
                name
                device_type {
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
                  description
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
                    }
                  }
                }
              }
            }"""
        )

        query = query_template.substitute(
            device_array=json.dumps(device_list)
        )

        r = self.query(query)

        return r['data']
