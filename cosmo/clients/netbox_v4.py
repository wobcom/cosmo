import json
from abc import ABC, abstractmethod
from builtins import map
from multiprocessing import Manager
from os import PathLike
from pathlib import Path

from cosmo.clients import get_client_mp_context
from cosmo.clients.netbox_client import NetboxAPIClient
from cosmo.common import FileTemplate


class ParallelQuery(ABC):

    def __init__(self, client: NetboxAPIClient, **kwargs):
        self.client = client

        self.data_promise = None
        self.kwargs = kwargs

    @staticmethod
    def file_template(relpath: str | PathLike):
        return FileTemplate(Path(__file__).parent.joinpath(Path(relpath)))

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
        query_template = self.file_template("queries/connected_devices.graphql")

        return self.client.query(
            query_template.substitute(tag_filter=tag_filter), "connected_devices_query"
        )["data"]

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

        query_template = self.file_template("queries/loopback.graphql")

        return self.client.query(query_template.substitute(), "loopback_query")["data"]

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
        query_template = self.file_template("queries/l2vpn.graphql")

        return self.client.query(query_template.substitute(), "l2vpn_query")["data"]

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
        # Filters for ippools are fucked.
        # Also, pagination is broken, so we just raise the limit and hope, it works.
        return self.client.query_rest("api/plugins/ip-pools/ippools/", {"limit": 1000})

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
        query_template = self.file_template("queries/device.graphql")

        query = query_template.substitute(
            device=json.dumps(device),
        )

        query_result = self.client.query(query, f"device_query_{device}")
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

            # manager.Pool normally takes the amount of CPU cores for the amount of processes it spawns.
            # Since our processes are mostly waiting, I would like to increase this to the amount of queries,
            # we are going to send.
            # Note: This will most likely screw the measured times, because Netbox cannot process too many requests at once
            # and will stall them eventually. So, if you are measuring times, reduce this to a reasonable amounts of 8 or something.
            worker_amount = len(queries)
            with manager.Pool(worker_amount) as pool:
                data_promises = list(map(lambda x: x.fetch_data(pool), queries))

                data = dict()

                for i, q in enumerate(queries):
                    dp = data_promises[i]
                    data = q.merge_into(dp, data)

        return data
