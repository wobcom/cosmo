import pytest

import cosmo.tests.utils as utils
from cosmo.netboxclient import NetboxClient, NetboxV3Strategy, NetboxV4Strategy

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


def test_case_query_v3_ok(mocker):
    utils.RequestResponseMock.patchTool(mocker)
    nc = NetboxV3Strategy(TEST_URL, TEST_TOKEN)
    nc.query('check')


def test_case_query_v3_nok(mocker):
    with pytest.raises(Exception):
        utils.RequestResponseMock.patchTool(
            mocker, graphqlData={'status_code': 403, 'text': 'unauthorized'})
        nc = NetboxV3Strategy(TEST_URL, TEST_TOKEN)
        nc.query('check')


def test_case_query_v4_ok(mocker):
    utils.RequestResponseMock.patchTool(mocker)
    nc = NetboxV4Strategy(TEST_URL, TEST_TOKEN)
    nc.query('check')


def test_case_query_v4_nok(mocker):
    with pytest.raises(Exception):
        utils.RequestResponseMock.patchTool(
            mocker, graphqlData={'status_code': 403, 'text': 'unauthorized'})
        nc = NetboxV4Strategy(TEST_URL, TEST_TOKEN)
        nc.query('check')


def test_case_get_data(mocker):
    mockAnswer = []
    [versionDetectMock, dataMock] = utils.RequestResponseMock.patchTool(
        mocker, graphqlData={'status_code': 200, 'text': '{"data":' + str(mockAnswer) + '}'})
    nc = NetboxClient(TEST_URL, TEST_TOKEN)
    responseData = nc.get_data(TEST_DEVICE_CFG)
    assert responseData == mockAnswer
    versionDetectMock.assert_called_once()
    dataMock.assert_called_once()
    kwargs = dataMock.call_args.kwargs
    assert 'json' in kwargs
    assert 'query' in kwargs['json']
    ncQueryStr = kwargs['json']['query']
    for device in [*TEST_DEVICE_CFG['router'], *TEST_DEVICE_CFG['switch']]:
        assert device in ncQueryStr
