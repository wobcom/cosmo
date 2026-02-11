import json
from abc import ABC, abstractmethod
from builtins import map
from multiprocessing import Manager
from string import Template

from cosmo.clients import get_client_mp_context
from cosmo.clients.netbox_client import NetboxAPIClient


class ParallelQuery(ABC):

    def __init__(self, client: NetboxAPIClient, **kwargs):
        self.client = client

        self.data_promise = None
        self.kwargs = kwargs

    def fetch_data(self, pool):
        return pool.apply_async(self._fetch_data, args=(self.kwargs, pool))

    @abstractmethod
    def _fetch_data(self, kwargs, pool):
        pass

    def merge_into(self, data_promise, data: dict):
        query_data = data_promise.get()
        return self._merge_into(data, query_data)

    @abstractmethod
    def _merge_into(self, data: dict, query_result):
        pass


class ConnectedDevicesDataQuery(ParallelQuery):
    def __init__(self, *args, netbox_43_query_syntax=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.netbox_43_query_syntax = netbox_43_query_syntax

    def _fetch_data(self, kwargs, pool):
        tag_filter = (
            'tags: { name: { exact: "bgp_cpe" }}'
            if self.netbox_43_query_syntax
            else 'tag: "bgp_cpe"'
        )
        query_template = Template(
            """
            query {
              interface_list(filters: { $tag_filter }) {
                __typename
                id,
                parent {
                  __typename
                  id,
                  connected_endpoints {
                    ... on InterfaceType {
                      __typename
                      name
                      device {
                        name
                        __typename
                        primary_ip4 {
                          __typename
                          address
                        }
                        interfaces {
                          id
                          name
                          __typename
                          ip_addresses {
                            __typename
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

        return self.client.query(query_template.substitute(tag_filter=tag_filter))[
            "data"
        ]

    def _merge_into(self, data: dict, query_data):

        for d in data["device_list"]:
            for interface in d["interfaces"]:
                cd_interface = next(
                    filter(
                        lambda i: i["id"] == interface["id"],
                        query_data["interface_list"],
                    ),
                    None,
                )

                if not cd_interface:
                    continue

                parent_interface = next(
                    filter(
                        lambda i: i["id"] == cd_interface["parent"]["id"],
                        d["interfaces"],
                    ),
                    None,
                )

                if not parent_interface:
                    continue

                parent_interface["connected_endpoints"] = cd_interface["parent"][
                    "connected_endpoints"
                ]

        return data


class LoopbackDataQuery(ParallelQuery):
    def _fetch_data(self, kwargs, pool):
        # Note: This does not use the device list, because we can have other participating devices
        # which are not in the same repository and thus are not appearing in device list.

        query_template = Template(
            """
            query{
              interface_list(filters: {
                name: {starts_with: "lo"}
              }) {
                __typename
                name,
                child_interfaces {
                  __typename
                  name,
                  vrf {
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
                  },
                  ip_addresses {
                    __typename
                    address,
                    family {
                     __typename
                     value,
                    }
                  }
                }
                device{
                  __typename
                  name,
                }
              }
            }
        """
        )

        return self.client.query(query_template.substitute())["data"]

    def _merge_into(self, data: dict, query_data):

        loopbacks: dict[str, dict] = dict()

        for interface in query_data["interface_list"]:
            child_interface = next(
                filter(lambda i: i["vrf"] is None, interface["child_interfaces"]), None
            )
            if not child_interface:
                continue
            device_name = interface["device"]["name"]

            l_ipv4 = next(
                filter(
                    lambda l: l["family"]["value"] == 4, child_interface["ip_addresses"]
                ),
                None,
            )
            l_ipv6 = next(
                filter(
                    lambda l: l["family"]["value"] == 6, child_interface["ip_addresses"]
                ),
                None,
            )
            loopbacks[device_name] = {
                "ipv4": l_ipv4["address"] if l_ipv4 else None,
                "ipv6": l_ipv6["address"] if l_ipv6 else None,
                "__typename": "CosmoLoopbackType",
                "device": device_name,
            }

        return {**data, "loopbacks": loopbacks}


class L2VPNDataQuery(ParallelQuery):
    def _fetch_data(self, kwargs, pool):
        query_template = Template(
            """
         query {
            l2vpn_list (filters: {name: {starts_with: "WAN: "}}) {
                __typename
                id
                name
                type
                identifier
                terminations {
                  __typename
                  id
                  assigned_object {
                    __typename
                    ... on VLANType {
                      __typename
                      id
                      name
                      interfaces_as_tagged {
                         id
                         name
                         __typename
                         device {
                            __typename
                            id
                            name
                         }
                      }
                      interfaces_as_untagged {
                         id
                         name
                         __typename
                         device {
                            __typename
                            id
                            name
                         }
                      }
                    }
                    ... on InterfaceType {
                      __typename
                      id
                      name
                      custom_fields
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
                      device {
                        __typename
                        id
                        name
                      }
                    }
                  }
                }
            }
         }
         """
        )

        return self.client.query(query_template.substitute())["data"]

    def _merge_into(self, data: dict, query_data):
        return {
            **data,
            **query_data,
        }


class StaticRouteQuery(ParallelQuery):

    def _fetch_data(self, kwargs, pool):
        device_list = kwargs.get("device_list")
        return self.client.query_rest(
            "api/plugins/routing/staticroutes/", {"device": device_list}
        )

    def _merge_into(self, data: dict, query_data):
        for d in data["device_list"]:
            device_static_routes = list(
                filter(lambda sr: str(sr["device"]["id"]) == d["id"], query_data)
            )
            d["staticroute_set"] = device_static_routes
            for e in d["staticroute_set"]:
                e["__typename"] = "CosmoStaticRouteType"

        return data


class StaticRouteDummyQuery(ParallelQuery):
    def _fetch_data(self, kwargs, pool):
        return []

    def _merge_into(self, data: dict, query_data):
        for d in data["device_list"]:
            d["staticroute_set"] = []

        return data


class IPPoolDataQuery(ParallelQuery):

    def _fetch_data(self, kwargs, pool):
        device_list = kwargs.get("device_list")
        return self.client.query_rest(
            "api/plugins/ip-pools/ippools/", {"devices": device_list}
        )

    def _merge_into(self, data: dict, query_data):

        for d in data["device_list"]:
            if "pool_set" not in d:
                d["pool_set"] = []

            for pool in query_data:
                if next(
                    filter(lambda pd: str(pd["id"]) == d["id"], pool["devices"]), None
                ):
                    d["pool_set"].append({**pool, "__typename": "CosmoIPPoolType"})

        return data


class IPPoolDataDummyQuery(ParallelQuery):
    def _fetch_data(self, kwargs, pool):
        return []

    def _merge_into(self, data: dict, query_data):
        for d in data["device_list"]:
            d["pool_set"] = []
        return data


class TobagoLineMembersDataQuery(ParallelQuery):
    def _fetch_data(self, kwargs, pool):
        device = kwargs.get("device")
        line_members = self.client.query_rest(
            "api/plugins/tobago/line-members/find-by-object/",
            {"content_type": "dcim.device", "object_name": device},
        )
        return line_members

    def _merge_into(self, data: dict, query_result):
        query_device_name = self.kwargs.get("device")
        for d in filter(
            lambda device: device["name"] == query_device_name, data["device_list"]
        ):
            for i in d["interfaces"]:
                attached_tobago_line = next(
                    filter(
                        # tobago is returning IDs as int so I have to do a little type casting
                        lambda l: int(l["termination_a"]["id"]) == int(i["id"])
                        or int(l["termination_b"]["id"]) == int(i["id"]),
                        query_result,
                    ),
                    None,
                )
                i["attached_tobago_line"] = (
                    {
                        **attached_tobago_line,
                        "__typename": "CosmoTobagoLine",
                    }
                    if attached_tobago_line
                    else None
                )
        return data


class TobagoLineMemberDataDummyQuery(ParallelQuery):
    def _fetch_data(self, kwargs, pool):
        return []

    def _merge_into(self, data: dict, query_result):
        for d in data["device_list"]:
            for i in d["interfaces"]:
                i["attached_tobago_line"] = None
        return data


# Note:
# Netbox v4.2 broke mac addresses in the GraphQL queries. Therefore, we just fetch them via the REST API and add them.
class DeviceMACQuery(ParallelQuery):
    def _fetch_data(self, kwargs, pool):
        device_list = kwargs.get("device_list")
        return self.client.query_rest(
            "api/dcim/interfaces",
            {"primary_mac_address__n": "null", "device": device_list},
        )

    def _merge_into(self, data: dict, query_data):
        for d in data["device_list"]:
            for i in d["interfaces"]:
                mq = next(
                    filter(
                        lambda mi: str(mi["device"]["id"]) == d["id"]
                        and str(mi["id"]) == i["id"],
                        query_data,
                    ),
                    None,
                )
                # Field must be set at any time, it's not requested in the GraphQL query anymore.
                i["mac_address"] = (
                    mq["primary_mac_address"]["mac_address"] if mq else None
                )
        return data


class DeviceDataQuery(ParallelQuery):

    def __init__(self, *args, multiple_mac_addresses=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.multiple_mac_addresses = multiple_mac_addresses

    def _fetch_data(self, kwargs, pool):
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
                custom_fields

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
                  connected_endpoints {
                    ... on ProviderNetworkType {
                      __typename
                      display
                    }
                    ... on CircuitTerminationType {
                      __typename
                      display
                    }
                    ... on VirtualCircuitTerminationType {
                      __typename
                      display
                    }
                    ... on InterfaceType {
                      __typename
                      name
                      device {
                        __typename
                        name
                      }
                    }
                    ... on FrontPortType {
                      __typename
                      name
                      device {
                        __typename
                        name
                      }
                    }
                    ... on RearPortType {
                      __typename
                      name
                      device {
                        __typename
                        name
                      }
                    }
                    ... on ConsolePortType {
                      __typename
                      name
                      device {
                        __typename
                        name
                      }
                    }
                    ... on ConsoleServerPortType {
                      __typename
                      name
                      device {
                        __typename
                        name
                      }
                    }
                  }
                  link_peers {
                    ... on CircuitTerminationType {
                      __typename
                      display
                    }
                    ... on FrontPortType {
                      __typename
                      name
                      device {
                        __typename
                        name
                      }
                    }
                    ... on RearPortType {
                      __typename
                      name
                      device {
                        __typename
                        name
                      }
                    }
                    ... on ConsolePortType {
                      __typename
                      name
                      device {
                        __typename
                        name
                      }
                    }
                    ... on ConsoleServerPortType {
                      __typename
                      name
                      device {
                        __typename
                        name
                      }
                    }
                    ... on InterfaceType {
                       __typename
                      name
                      device {
                        __typename
                        name
                      }
                    }
                  }
                  vrf {
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
                  lag {
                    __typename
                    id
                    name
                  }
                  ip_addresses {
                    __typename
                    address
                    role
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
                    id
                    name
                    slug
                  }
                  parent {
                    __typename
                    id
                    mtu
                    name
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
        return query_result["data"]

    def _merge_into(self, data: dict, query_data):
        if "device_list" not in data:
            data["device_list"] = []

        data["device_list"].extend(query_data["device_list"])

        return data


class NetboxV4Strategy:

    def __init__(
        self, url, token, multiple_mac_addresses, netbox_43_query_syntax, feature_flags
    ):
        self.url = url
        self.token = token
        self.multiple_mac_addresses = multiple_mac_addresses
        self.netbox_43_query_syntax = netbox_43_query_syntax
        self.feature_flags = feature_flags

    def get_data(self, device_config):
        device_list = device_config["router"] + device_config["switch"]

        queries = list()

        # https://superfastpython.com/multiprocessing-pool-share-with-workers/
        # pool object is used through manager's proxy multiprocess object,
        # this way, subprocesses can spawn more processes as if it was done
        # from the main thread. by default this is not possible, see
        # https://stackoverflow.com/questions/72411392/can-you-do-nested-parallelization-using-multiprocessing-in-python
        # this avoids having to re-architecture completely using worker/task/queue model.
        with get_client_mp_context().Manager() as manager:
            client = NetboxAPIClient(self.url, self.token, manager.dict())

            for d in device_list:
                queries.extend(
                    [
                        DeviceDataQuery(
                            client,
                            device=d,
                            multiple_mac_addresses=self.multiple_mac_addresses,
                        ),
                        (
                            TobagoLineMembersDataQuery(client, device=d)
                            if self.feature_flags["tobago"]
                            else TobagoLineMemberDataDummyQuery(client, device=d)
                        ),
                    ]
                )

            queries.extend(
                [
                    L2VPNDataQuery(client, device_list=device_list),
                    (
                        StaticRouteQuery(client, device_list=device_list)
                        if self.feature_flags["routing"]
                        else StaticRouteDummyQuery(client, device_list=device_list)
                    ),
                    DeviceMACQuery(client, device_list=device_list),
                    ConnectedDevicesDataQuery(
                        client,
                        device_list=device_list,
                        netbox_43_query_syntax=self.netbox_43_query_syntax,
                    ),
                    LoopbackDataQuery(client, device_list=device_list),
                    (
                        IPPoolDataQuery(client, device_list=device_list)
                        if self.feature_flags["ippools"]
                        else IPPoolDataDummyQuery(client, device_list=device_list)
                    ),
                ]
            )

            with manager.Pool() as pool:
                data_promises = list(map(lambda x: x.fetch_data(pool), queries))

                data = dict()

                for i, q in enumerate(queries):
                    dp = data_promises[i]
                    data = q.merge_into(dp, data)

        return data
