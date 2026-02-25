import json
import multiprocessing


def override_get_client_mp_context(method=None):
    def overriden_get_client_mp_context():
        return multiprocessing.get_context(method=method)

    return overriden_get_client_mp_context


class CommonSetup:
    PROGNAME = "cosmo"
    TEST_URL = "https://netbox.example.com"
    TEST_TOKEN = "token123"
    DEFAULT_ENVIRON = {"NETBOX_URL": TEST_URL, "NETBOX_API_TOKEN": TEST_TOKEN}
    DEFAULT_CFGFILE = "cosmo.example.yml"

    def __init__(
        self, mocker, environ=DEFAULT_ENVIRON, cfgFile=DEFAULT_CFGFILE, args=[PROGNAME]
    ):
        self.mocker = mocker
        self.patches = []
        # we need to setup correct test environ before running
        self.patches.append(self.mocker.patch.dict("os.environ", environ))
        # patch args, since current ones are from pytest call
        self.patches.append(self.mocker.patch("sys.argv", args))
        # patch netbox client default mp context for the time of the tests
        # patch may be ineffective since not in correct namespace(?)
        self.patches.append(
            self.mocker.patch(
                "cosmo.clients.netbox_v4.get_client_mp_context",
                new=override_get_client_mp_context("fork"),
            )
        )

        # patch configuration file lookup if requested

        # Note: If there is no configuration file given, we still need to patch this.
        # The user can have a cosmo.yml in their folder, which still gets loaded without a mock.
        # Afterward the test would run with an unknown cosmo.yml.
        if cfgFile:
            p = PatchIoFilePath(self.mocker, "cosmo.__main__", "cosmo.yml", cfgFile)
        else:
            p = PatchIoFilePath(
                self.mocker,
                "cosmo.__main__",
                "f5175f8c-dd7c-4b3b-904f-ece63c45ea49.yml",
                cfgFile,
            )

        self.patches += p.getPatches()

    def stop(self):
        for patch in self.patches:
            self.mocker.stop(patch)


class ResponseMock:
    def __init__(self, status_code, obj):
        self.status_code = status_code
        self.text = json.dumps(obj)
        self.obj = obj

    def json(self):
        return self.obj


class RequestResponseMock:
    def __init__(self):
        self.get_responses = dict()
        self.post_responses = dict()

    def patchNetboxClient(self, mocker, **patchKwArgs):

        def patchGetFunc(url, **kwargs):
            if "/api/status" in url:
                r = ResponseMock(
                    200,
                    {
                        "netbox-version": "4.1.2+wobcom_0.4.2",
                        "plugins": [
                            "netbox_plugin_tobago",
                            "netbox_plugin_ip_pools",
                            "netbox_plugin_routing",
                        ],
                    },
                )
            else:
                r = ResponseMock(
                    200,
                    {
                        "next": None,
                        "results": [],
                    },
                )
            self.get_responses[url] = r
            return r

        def patchPostFunc(url, json, **kwargs):
            q = json.get("query")
            request_lists = [
                "device_list",
                "vrf_list",
                "l2vpn_list",
            ]
            retVal = dict()

            for rl in request_lists:
                if "bgp_cpe" in q:
                    retVal["interface_list"] = patchKwArgs.get(
                        "connected_devices_interface_list", []
                    )
                elif 'starts_with: "lo"' in q:
                    retVal["interface_list"] = patchKwArgs.get(
                        "loopback_interface_list", []
                    )
                elif rl in q:
                    retVal[rl] = patchKwArgs.get(rl, [])

            r = ResponseMock(200, {"data": retVal})
            # TODO: find out why value set is being trashed outside context ???
            self.post_responses[q] = r
            return r

        getMock = mocker.patch("requests.get", side_effect=patchGetFunc)
        postMock = mocker.patch("requests.post", side_effect=patchPostFunc)
        return [getMock, postMock]


# it has to be stateful - so I'm making an object
class PatchIoFilePath:
    def __init__(self, mocker, patchInNamespace, requestedPath, pathToRealData):
        self.requestedPath = requestedPath
        self.pathToRealData = pathToRealData
        self.namespace = patchInNamespace
        self.mocker = mocker
        self.patches = []
        self._patch()

    def _openReplacement(self, file, *args, **kwargs):
        if file == self.requestedPath:
            return open(self.pathToRealData, *args, **kwargs)
        else:
            return open(file, *args, **kwargs)

    def _patch(self):
        self.patches.append(
            self.mocker.patch(self.namespace + ".open", self._openReplacement)
        )
        self.patches.append(
            self.mocker.patch(
                self.namespace + ".os.path.isfile",
                lambda f: True if f == self.requestedPath else False,
            )
        )

    def getPatches(self):
        return self.patches
