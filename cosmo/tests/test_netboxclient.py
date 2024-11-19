import pytest

import cosmo.tests.utils as utils
from cosmo.netboxclient import NetboxClient

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


def test_case_get_data(mocker):
    mockAnswer = {
        "device_list": [],
        "l2vpn_list": [],
        "vrf_list": [],
    }
    [getMock, postMock] = utils.RequestResponseMock.patchNetboxClient(mocker)

    nc = NetboxClient(TEST_URL, TEST_TOKEN)
    assert nc.version == "4.1.2"

    getMock.assert_called_once()

    responseData = nc.get_data(TEST_DEVICE_CFG)
    assert responseData == mockAnswer

    assert getMock.call_count == 2
    assert postMock.call_count == 1

    kwargs = postMock.call_args.kwargs
    assert 'json' in kwargs
    assert 'query' in kwargs['json']
    ncQueryStr = kwargs['json']['query']
    for device in [*TEST_DEVICE_CFG['router'], *TEST_DEVICE_CFG['switch']]:
        assert device in ncQueryStr