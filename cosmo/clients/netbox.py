import time
from urllib.parse import urljoin

import requests

from cosmo import log
from cosmo.clients.netbox_v4 import NetboxV4Strategy


class NetboxClient:
    def __init__(self, url, token):
        self.url = url
        self.token = token

        self.version = self.query_version()

        if self.version.startswith("4."):
            log.info("Using version 4.x strategy...")
            self.child_client = NetboxV4Strategy(url, token)
        else:
            raise Exception("Unknown Version")

    def query_version(self):
        r = requests.get(
            urljoin(self.url, "/api/status/"),
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
        log.info(f"Data fetching took {round(diff_time, 2)} s...")

        return data


