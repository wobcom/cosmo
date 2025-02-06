import json
from abc import ABC, abstractmethod
from builtins import map
from multiprocessing import Pool
from string import Template

from cosmo.clients.netbox_client import NetboxAPIClient


class ParallelQuery(ABC):

    def __init__(self, client: NetboxAPIClient, **kwargs):
        self.client = client

        self.data_promise = None
        self.kwargs = kwargs

    def fetch_data(self, pool):
        return pool.apply_async(self._fetch_data, args=(self.kwargs,))

    @abstractmethod
    def _fetch_data(self, **kwargs):
        pass

    def merge_into(self, data_promise, data: object):
        query_data = data_promise.get()
        return self._merge_into(data, query_data)

    @abstractmethod
    def _merge_into(self, data: object, query_result):
        pass


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


class LoopbackDataQuery(ParallelQuery):
    def _fetch_data(self, kwargs):
        # Note: This does not use the device list, because we can have other participating devices
        # which are not in the same repository and thus are not appearing in device list.

        query_template = Template('''
            query{
              interface_list(filters: {
                name: {starts_with: "lo"},
                type: {exact:"loopback"}
              }) {
                name,
                child_interfaces {
                  name,
                  vrf {
                    id
                  },
                  ip_addresses {
                    address,
                    family {
                     value,
                    }
                  }
                }
                device{
                  name,
                }
              }
            }
        ''')

        return self.client.query(query_template.substitute())['data']

    def _merge_into(self, data: object, query_data):

        loopbacks = dict()

        for interface in query_data['interface_list']:
            child_interface = next(filter(lambda i: i['vrf'] is None, interface['child_interfaces']), None)
            if not child_interface:
                continue
            device_name = interface['device']['name']

            l_ipv4 = next(filter(lambda l: l['family']['value'] == 4, child_interface['ip_addresses']), None)
            l_ipv6 = next(filter(lambda l: l['family']['value'] == 6, child_interface['ip_addresses']), None)
            loopbacks[device_name] = {
                "ipv4": l_ipv4['address'] if l_ipv4 else None,
                "ipv6": l_ipv6['address'] if l_ipv6 else None
            }

        return {
            **data,
            'loopbacks': loopbacks
        }


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


# Note:
# Netbox v4.2 broke mac addresses in the GraphQL queries. Therefore, we just fetch them via the REST API and add them.
class DeviceMACQuery(ParallelQuery):
    def _fetch_data(self, kwargs):
        device_list = kwargs.get("device_list")
        return self.client.query_rest("api/dcim/interfaces", {"primary_mac_address__n": "null", "device": device_list})

    def _merge_into(self, data: dict, query_data):
        for d in data['device_list']:
            for i in d['interfaces']:
                mq = next(
                    filter(
                        lambda mi: str(mi['device']['id']) == d['id'] and str(mi['id']) == i['id'],
                        query_data
                    ),
                    None
                )
                # Field must be set at any time, it's not requested in the GraphQL query anymore.
                i['mac_address'] = mq['primary_mac_address']['mac_address'] if mq else None
        return data


class DeviceDataQuery(ParallelQuery):

    def __init__(self, *args, multiple_mac_addresses=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.multiple_mac_addresses = multiple_mac_addresses

    def _fetch_data(self, kwargs):
        device = kwargs.get("device")
        query_template = Template(
            """
            query {
              device_list(filters: {
                name: { i_exact: $device },
              }) {
                __typename
                id
                name
                serial

                device_type {
                  __typename
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
                    mtu
                  }
                  custom_fields
                }
              }
            }"""
        )

        query = query_template.substitute(
            device=json.dumps(device),
        )

        query_result = self.client.query(query)
        return query_result['data']

    def _merge_into(self, data: dict, query_data):
        if 'device_list' not in data:
            data['device_list'] = []

        data['device_list'].extend(query_data['device_list'])

        return data


class NetboxV4Strategy:

    def __init__(self, url, token, multiple_mac_addresses):
        self.client = NetboxAPIClient(url, token)
        self.multiple_mac_addresses = multiple_mac_addresses

    def get_data(self, device_config):
        device_list = device_config['router'] + device_config['switch']

        queries = list()

        for d in device_list:
            queries.append(
                DeviceDataQuery(self.client, device=d, multiple_mac_addresses=self.multiple_mac_addresses)
            )

        queries.extend([
            VrfDataQuery(self.client, device_list=device_list),
            L2VPNDataQuery(self.client, device_list=device_list),
            StaticRouteQuery(self.client, device_list=device_list),
            DeviceMACQuery(self.client, device_list=device_list),
            ConnectedDevicesDataQuery(self.client, device_list=device_list),
            LoopbackDataQuery(self.client, device_list=device_list)
        ])

        with Pool() as pool:

            data_promises = list(map(lambda x: x.fetch_data(pool), queries))

            data = dict()

            for i, q in enumerate(queries):
                dp = data_promises[i]
                data = q.merge_into(dp, data)

        return data
