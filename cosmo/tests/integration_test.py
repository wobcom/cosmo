import json
import yaml
import pytest
import os

import cosmo.tests.utils as utils
from cosmo.__main__ import main as cosmoMain

def test_missing_config(mocker):
    utils.CommonSetup(mocker, cfgFile=None)
    with pytest.raises(Exception):
        cosmoMain()

def test_missing_netbox_url(mocker):
    utils.CommonSetup(mocker, environ={'NETBOX_API_TOKEN': utils.CommonSetup.TEST_TOKEN})
    with pytest.raises(Exception):
        cosmoMain()

def test_missing_netbox_api_token(mocker):
    utils.CommonSetup(mocker, environ={'NETBOX_URL': utils.CommonSetup.TEST_URL})
    with pytest.raises(Exception):
        cosmoMain()

def test_limit_argument_with_commas(mocker):
    utils.CommonSetup(mocker, args=[utils.CommonSetup.PROGNAME, '--limit', 'router1,router2'])
    utils.RequestResponseMock.patchTool(mocker)
    assert cosmoMain() == 0

def test_limit_arguments_with_repeat(mocker):
    utils.CommonSetup(mocker, args=[utils.CommonSetup.PROGNAME, '--limit', 'router1', '--limit', 'router2'])
    utils.RequestResponseMock.patchTool(mocker)
    assert cosmoMain() == 0

def test_device_generation_ansible(mocker):
    testEnv = utils.CommonSetup(mocker, cfgFile='cosmo/tests/cosmo.devgen_ansible.yml')
    with open(f"cosmo/tests/test_case_l3vpn.yml") as f:
        utils.RequestResponseMock.patchTool(
            mocker,{'status_code': 200, 'text': '{"data": ' + json.dumps(yaml.safe_load(f)) + '}'})
    assert cosmoMain() == 0
    testEnv.stop()
    assert os.path.isfile('host_vars/test0001/generated-cosmo.yml')

def test_device_generation_nix(mocker):
    testEnv = utils.CommonSetup(mocker, cfgFile='cosmo/tests/cosmo.devgen_nix.yml')
    with open(f"cosmo/tests/test_case_l3vpn.yml") as f:
        utils.RequestResponseMock.patchTool(
            mocker,{'status_code': 200, 'text': '{"data": ' + json.dumps(yaml.safe_load(f)) + '}'})
    assert cosmoMain() == 0
    testEnv.stop()
    assert os.path.isfile('machines/test0001/generated-cosmo.json')

def test_device_processing_error(mocker):
    testEnv = utils.CommonSetup(mocker, cfgFile='cosmo/tests/cosmo.devgen_nix.yml')
    with open(f"cosmo/tests/test_case_vendor_unknown.yaml") as f:
        utils.RequestResponseMock.patchTool(
            mocker,{'status_code': 200, 'text': '{"data": ' + json.dumps(yaml.safe_load(f)) + '}'})
    with pytest.warns(UserWarning, match="unsupported platform vendor"):
        assert cosmoMain() == 0
    testEnv.stop()
