from urllib.parse import urlencode

import requests


class NetboxAPIClient:
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

        json = r.json()

        if 'errors' in json:
            for e in json['errors']:
                print(e)

        return json

    def query_rest(self, path, queries):
        q = urlencode(queries, doseq=True)
        url = f"{self.url}/{path}?{q}"

        return_array = list()

        while url is not None:
            r = requests.get(
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

            url = data['next']
            return_array.extend(data['results'])

        return return_array
