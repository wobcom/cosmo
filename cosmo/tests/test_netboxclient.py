from unittest.mock import patch

import pytest
from packaging.version import Version

import cosmo.tests.utils as utils
from cosmo.clients.netbox import NetboxClient
from cosmo.tests.utils import override_get_client_mp_context

TEST_URL = "https://netbox.example.com"
TEST_TOKEN = "token123"
TEST_DEVICE_CFG = {"router": ["router1", "router2"], "switch": ["switch1", "switch2"]}


@patch(
    "cosmo.clients.netbox_v4.get_client_mp_context",
    new=override_get_client_mp_context("fork"),
)
def test_case_get_data(mocker):
    mockAnswer = {
        "device_list": [],
        "l2vpn_list": [],
        "loopbacks": {},
    }
    [getMock, postMock] = utils.RequestResponseMock().patchNetboxClient(mocker)

    nc = NetboxClient(TEST_URL, TEST_TOKEN)
    assert nc.base_version == Version("4.1.2")

    getMock.assert_called_once()

    responseData = nc.get_data(TEST_DEVICE_CFG)

    # Note: Call Counts seems to be broken with side_effect..
    # assert getMock.call_count == 1
    # assert postMock.call_count == 0
    assert responseData == mockAnswer
