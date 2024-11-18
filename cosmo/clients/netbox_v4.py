import json
from builtins import map
from multiprocessing import Pool
from string import Template

from cosmo.clients.netbox_client import NetboxAPIClient


class ParallelQuery:

    def __init__(self, client: NetboxAPIClient, **kwargs):
        self.client = client

        self.data_promise = None
        self.kwargs = kwargs

    def fetch_data(self, pool):
        return pool.apply_async(self._fetch_data, args=(self.kwargs,))

    def _fetch_data(self, **kwargs):
        raise NotImplementedError()

    def merge_into(self, data_promise, data: object):
        query_data = data_promise.get()
        return self._merge_into(data, query_data)

    def _merge_into(self, data: object, query_result):
        raise NotImplementedError()


class ConnectedDevicesDataQuery(ParallelQuery):
    def _fetch_data(self, kwargs):
        query_template = Template('''
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
        ''')

        return self.client.query(query_template.substitute())['data']

    def _merge_into(self, data: dict, query_data):

        for d in data['device_list']:
            for interface in d['interfaces']:
                cd_interface = next(
                    filter(lambda i: i["id"] == interface["id"], query_data['interface_list']), None)

                if not cd_interface:
                    continue

                parent_interface = next(
                    filter(lambda i: i['id'] == cd_interface['parent']['id'], d['interfaces']),
                    None
                )
                parent_interface['connected_endpoints'] = cd_interface['parent']['connected_endpoints']

        return data

class L2VPNDataQuery(ParallelQuery):
    def _fetch_data(self, kwargs):
        query_template = Template('''
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
         ''')

        return self.client.query(query_template.substitute())['data']

    def _merge_into(self, data: object, query_data):
        return {
            **data,
            **query_data,
        }


class VrfDataQuery(ParallelQuery):
    def _fetch_data(self, kwargs):
        query_template = Template('''
            query {
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
            }
        ''')

        return self.client.query(query_template.substitute())['data']

    def _merge_into(self, data: dict, query_data):
        return {
            **data,
            **query_data,
        }


class StaticRouteQuery(ParallelQuery):

    def _fetch_data(self, kwargs):
        device_list = kwargs.get("device_list")
        return self.client.query_rest("api/plugins/routing/staticroutes/", {"device": device_list})

    def _merge_into(self, data: dict, query_data):
        for d in data['device_list']:
            device_static_routes = list(filter(lambda sr: str(sr['device']['id']) == d['id'], query_data))
            d['staticroute_set'] = device_static_routes

        return data

class DeviceDataQuery(ParallelQuery):
    def _fetch_data(self, kwargs):
        device_list = kwargs.get("device_list")
        query_template = Template(
            """
            query {
              device_list(filters: {
                name: { in_list: $device_list },
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
            }"""
        )

        query = query_template.substitute(
            device_list=json.dumps(device_list)
        )
        return self.client.query(query)['data']

    def _merge_into(self, data: object, query_data):
        return {
            **data,
            **query_data,
        }


class NetboxV4Strategy:

    def __init__(self, url, token):
        self.client = NetboxAPIClient(url, token)

    def get_data(self, device_config):
        device_list = device_config['router'] + device_config['switch']

        queries = [
            DeviceDataQuery(self.client, device_list=device_list),
            VrfDataQuery(self.client, device_list=device_list),
            L2VPNDataQuery(self.client, device_list=device_list),
            StaticRouteQuery(self.client, device_list=device_list),
            ConnectedDevicesDataQuery(self.client, device_list=device_list),
        ]

        with Pool() as pool:

            data_promises = list(map(lambda x: x.fetch_data(pool), queries))

            data = dict()

            for i, q in enumerate(queries):
                dp = data_promises[i]
                data = q.merge_into(dp, data)

        return data
