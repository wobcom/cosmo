import time
from urllib.parse import urlencode, urljoin
from multiprocessing.managers import DictProxy

import requests

from cosmo import log


class NetboxAPIClient:
    def __init__(self, url, token, interprocess_shared_cache: DictProxy):
        self.url = url
        self.token = token
        self.cache = interprocess_shared_cache

    def query(self, query, query_name=None):

        start_time = time.perf_counter()

        r = requests.post(
            urljoin(self.url, "/graphql/"),
            json={"query": query},
            headers={
                "Authorization": f"Token {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        if r.status_code != 200:
            raise Exception("Error querying api: " + r.text)

        json = r.json()

        if "errors" in json:
            for e in json["errors"]:
                print(e)

        end_time = time.perf_counter()
        diff_time = end_time - start_time
        log.debug(f"Fetching {query_name} took {round(diff_time, 2)} s...")

        return json

    def _cached_get(self, url, headers):
        if url not in self.cache:
            self.cache[url] = requests.get(
                url,
                headers=headers,
            )
        return self.cache.get(url)

    def query_rest(self, path, queries):
        q = urlencode(queries, doseq=True)
        base_url = urljoin(self.url, path) + f"?{q}"
        url = base_url

        start_time = time.perf_counter()

        return_array = list()

        while url is not None:
            r = self._cached_get(
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

            url = data.get("next")
            if type(data.get("results")) == list:
                return_array.extend(data.get("results"))
            else:
                return data

        end_time = time.perf_counter()
        diff_time = end_time - start_time
        log.debug(f"Fetching {base_url} took {round(diff_time, 2)} s...")

        return return_array
