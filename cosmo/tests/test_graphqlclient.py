import pytest

import cosmo.tests.utils as utils
from cosmo.graphqlclient import GraphqlClient

TEST_URL = 'https://netbox.example.com'
TEST_TOKEN = 'token123'
TEST_DEVICE_CFG = {
    'router': [
        'router1',
        'router2'
    ],
    'switch': [
        'switch1',
        'switch2'
    ]}

def test_case_query_ok(mocker):
    utils.RequestResponseMock.patchTool(mocker)
    gql = GraphqlClient(TEST_URL, TEST_TOKEN)
    gql.query('check')

def test_case_query_nok(mocker):
    with pytest.raises(Exception):
        utils.RequestResponseMock.patchTool(
            mocker, returnData={'status_code': 403, 'text': 'unauthorized'})
        gql = GraphqlClient(TEST_URL, TEST_TOKEN)
        gql.query('check')

def test_case_get_data(mocker):
    mockAnswer = []
    postMock = utils.RequestResponseMock.patchTool(
        mocker,returnData={'status_code': 200, 'text': '{"data":' + str(mockAnswer) + '}'})
    gql = GraphqlClient(TEST_URL, TEST_TOKEN)
    responseData = gql.get_data(TEST_DEVICE_CFG)
    assert responseData == mockAnswer
    postMock.assert_called_once()
    kwargs = postMock.call_args.kwargs
    assert 'json' in kwargs
    assert 'query' in kwargs['json']
    gqlQueryStr = kwargs['json']['query']
    for device in [*TEST_DEVICE_CFG['router'], *TEST_DEVICE_CFG['switch']]:
        assert device in gqlQueryStr
