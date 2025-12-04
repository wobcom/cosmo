from urllib.parse import urlencode, urljoin
from multiprocessing.managers import DictProxy

import requests


class NetboxAPIClient:
    def __init__(self, url, token, interprocess_shared_cache: DictProxy):
        self.url = url
        self.token = token
        self.session = requests.Session()
        self.cache = interprocess_shared_cache

    def query(self, query):
        r = self.session.post(
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

        return json

    def _cached_get(self, url, headers):
        if url not in self.cache:
            self.cache[url] = self.session.get(
                url,
                headers=headers,
            )
        return self.cache.get(url)

    def query_rest(self, path, queries):
        q = urlencode(queries, doseq=True)
        url = urljoin(self.url, path) + f"?{q}"

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

        return return_array
