import json

class RequestResponseMock:
    def __init__(self, **kwargs):
        self.status_code = kwargs['status_code']
        self.text = kwargs['text']

    @staticmethod
    def patchTool(mocker, returnData={'status_code': 200, 'text': '{}'}):
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

def patchEnviron(mocker, environ):
    mocker.patch.dict('os.environ', environ)
