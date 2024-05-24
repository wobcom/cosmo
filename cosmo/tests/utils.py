def requestPatchTool(mocker, returnData=
                     {'status_code': 200, 'text': '{}'}):
    rMock = mocker.PropertyMock(**returnData)
    postMock = mocker.patch('requests.post', return_value=rMock)
    return postMock
