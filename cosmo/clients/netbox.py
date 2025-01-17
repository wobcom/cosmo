import re
import time
from urllib.parse import urljoin

import requests
from packaging.version import Version

from cosmo import log
from cosmo.clients.netbox_v4 import NetboxV4Strategy


class NetboxClient:
    def __init__(self, url, token):
        self.url = url
        self.token = token

        version = self.query_version()
        base_version_match = re.search(r'[\d.]+', version)
        base_version = Version(base_version_match.group(0))

        if base_version > Version("4.2.0"):
            log.info("Using version 4.2.x strategy...")
            self.child_client = NetboxV4Strategy(url, token, multiple_mac_addresses=True)
        elif base_version > Version("4.0.0"):
            log.info("Using version 4.0.x strategy...")
            self.child_client = NetboxV4Strategy(url, token, multiple_mac_addresses=False)
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


