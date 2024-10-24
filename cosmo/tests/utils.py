import json


class CommonSetup:
    PROGNAME = 'cosmo'
    TEST_URL = 'https://netbox.example.com'
    TEST_TOKEN = 'token123'
    DEFAULT_ENVIRON = {'NETBOX_URL': TEST_URL, 'NETBOX_API_TOKEN': TEST_TOKEN}
    DEFAULT_CFGFILE = 'cosmo.example.yml'

    def __init__(
            self, mocker, environ=DEFAULT_ENVIRON,
            cfgFile=DEFAULT_CFGFILE, args=[PROGNAME]):
        self.mocker = mocker
        self.patches = []
        # we need to setup correct test environ before running
        self.patches.append(self.mocker.patch.dict('os.environ', environ))
        # patch args, since current ones are from pytest call
        self.patches.append(self.mocker.patch('sys.argv', args))
        # patch configuration file lookup if requested

        # Note: If there is no configuration file given, we still need to patch this.
        # The user can have a cosmo.yml in their folder, which still gets loaded without a mock.
        # Afterward the test would run with an unknown cosmo.yml.
        if cfgFile:
            p = PatchIoFilePath(self.mocker, 'cosmo.__main__', 'cosmo.yml', cfgFile)
        else:
            p = PatchIoFilePath(self.mocker, 'cosmo.__main__', 'f5175f8c-dd7c-4b3b-904f-ece63c45ea49.yml', cfgFile)

        self.patches += p.getPatches()

    def stop(self):
        for patch in self.patches:
            self.mocker.stop(patch)


class RequestResponseMock:
    def __init__(self, **kwargs):
        self.status_code = kwargs['status_code']
        self.text = kwargs['text']

    @staticmethod
    def patchTool(mocker, graphqlData=None, versionData=None):

        if graphqlData is None:
            graphqlData = {'status_code': 200, 'text': json.dumps({"data": {"vrf_list": [], "device_list": []}})}

        if versionData is None:
            versionData = {'status_code': 200, 'text': json.dumps({"netbox-version": "wc_3.7.5-0.7.0"})}

        postMock1 = mocker.patch('requests.get', return_value=RequestResponseMock(**versionData))
        postMock2 = mocker.patch('requests.post', return_value=RequestResponseMock(**graphqlData))
        return [postMock1, postMock2]

    def json(self):
        return json.loads(self.text)


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
        self.patches.append(self.mocker.patch(self.namespace + '.open', self._openReplacement))
        self.patches.append(self.mocker.patch(self.namespace + '.os.path.isfile',
                                              lambda f: True if f == self.requestedPath else False))

    def getPatches(self):
        return self.patches
