import json

class CommonSetup:
    PROGNAME='cosmo'
    TEST_URL = 'https://netbox.example.com'
    TEST_TOKEN = 'token123'
    DEFAULT_ENVIRON = {'NETBOX_URL': TEST_URL, 'NETBOX_API_TOKEN': TEST_TOKEN}
    DEFAULT_CFGFILE = 'cosmo.example.yml'

    def __init__(
            self, mocker, environ=DEFAULT_ENVIRON,
            cfgFile=DEFAULT_CFGFILE, args=[PROGNAME]):
        self.mocker = mocker
        # we need to setup correct test environ before running
        self.environPatch = self.mocker.patch.dict('os.environ', environ)
        # patch args, since current ones are from pytest call
        self.argsPatch = self.mocker.patch('sys.argv', args)
        # patch configuration file lookup if requested
        self.cfgFilePatch = None
        if cfgFile:
            self.cfgFilePatch = PatchIoFilePath(self.mocker, 'cosmo.__main__', 'cosmo.yml', cfgFile)

class RequestResponseMock:
    def __init__(self, **kwargs):
        self.status_code = kwargs['status_code']
        self.text = kwargs['text']

    @staticmethod
    def patchTool(mocker, returnData={'status_code': 200, 'text': '{"data": {"vrf_list": [], "device_list": []}}'}):
        postMock = mocker.patch('requests.post', return_value=RequestResponseMock(**returnData))
        return postMock

    def json(self):
        return json.loads(self.text)



# it has to be stateful - so I'm making an object
class PatchIoFilePath:
    def __init__(self, mocker, patchInNamespace, requestedPath, pathToRealData):
        self.requestedPath = requestedPath
        self.pathToRealData = pathToRealData
        self.namespace = patchInNamespace
        self.mocker = mocker
        self._patch()

    def _openReplacement(self, file, *args, **kwargs):
        if file == self.requestedPath:
            return open(self.pathToRealData, *args, **kwargs)
        else:
            return open(file, *args, **kwargs)

    def _patch(self):
        self.mocker.patch(self.namespace + '.open', self._openReplacement)
        self.mocker.patch(self.namespace + '.os.path.isfile',
                          lambda f: True if f == self.requestedPath else False)

