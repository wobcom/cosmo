import json
import re
from sharedmock.mock import SharedMock  # type: ignore
from unittest.mock import call, ANY

import jsonschema.exceptions
import yaml
import pytest
import os

import cosmo.tests.utils as utils
from cosmo.__main__ import main as cosmoMain
from cosmo.common import FileTemplate
from cosmo.features import with_feature, features, without_feature


def test_missing_config(mocker):
    utils.CommonSetup(mocker, cfgFile=None)
    with pytest.raises(Exception):
        cosmoMain()


def test_missing_netbox_url(mocker):
    utils.CommonSetup(
        mocker, environ={"NETBOX_API_TOKEN": utils.CommonSetup.TEST_TOKEN}
    )
    with pytest.raises(Exception):
        cosmoMain()


def test_missing_netbox_api_token(mocker):
    utils.CommonSetup(mocker, environ={"NETBOX_URL": utils.CommonSetup.TEST_URL})
    with pytest.raises(Exception):
        cosmoMain()


def test_limit_argument_with_commas(mocker):
    utils.CommonSetup(
        mocker, args=[utils.CommonSetup.PROGNAME, "--limit", "router1,router2"]
    )
    utils.RequestResponseMock().patchNetboxClient(mocker)
    assert cosmoMain() == 0


def test_limit_arguments_with_repeat(mocker):
    utils.CommonSetup(
        mocker,
        args=[utils.CommonSetup.PROGNAME, "--limit", "router1", "--limit", "router2"],
    )
    utils.RequestResponseMock().patchNetboxClient(mocker)
    assert cosmoMain() == 0


def test_device_generation_ansible(mocker):
    testEnv = utils.CommonSetup(mocker, cfgFile="cosmo/tests/cosmo.devgen_ansible.yml")
    with open(f"cosmo/tests/test_case_l3vpn.yml") as f:
        test_data = yaml.safe_load(f)
        utils.RequestResponseMock().patchNetboxClient(mocker, **test_data)
    assert cosmoMain() == 0
    testEnv.stop()
    assert os.path.isfile("host_vars/test0001/generated-cosmo.yml")


def test_device_generation_nix(mocker):
    testEnv = utils.CommonSetup(mocker, cfgFile="cosmo/tests/cosmo.devgen_nix.yml")
    with open(f"cosmo/tests/test_case_l3vpn.yml") as f:
        test_data = yaml.safe_load(f)
        utils.RequestResponseMock().patchNetboxClient(mocker, **test_data)
    assert cosmoMain() == 0
    testEnv.stop()
    assert os.path.isfile("machines/test0001/generated-cosmo.json")


def test_device_processing_error(mocker, capsys):
    testEnv = utils.CommonSetup(mocker, cfgFile="cosmo/tests/cosmo.devgen_nix.yml")
    with open(f"cosmo/tests/test_case_vendor_unknown.yaml") as f:
        test_data = yaml.safe_load(f)
        utils.RequestResponseMock().patchNetboxClient(mocker, **test_data)
    with pytest.raises(
        Exception, match="Cannot find suitable manufacturer for device .*"
    ):
        cosmoMain()
    testEnv.stop()


@with_feature(features, "interface-auto-descriptions")
def test_autodesc_enabled(mocker):
    device_query_template = FileTemplate("cosmo/clients/queries/device.graphql")
    testEnv = utils.CommonSetup(mocker, cfgFile="cosmo/tests/cosmo.devgen_ansible.yml")
    rrm = utils.RequestResponseMock()
    get_mock = mocker.patch.object(rrm, "get_callback", new=SharedMock())
    post_mock = mocker.patch.object(rrm, "post_callback", new=SharedMock())

    with open("cosmo/tests/test_case_auto_descriptions.yaml") as f:
        test_data = yaml.safe_load(f)
        rrm.patchNetboxClient(mocker, **test_data)

    assert cosmoMain() == 0
    assert get_mock.call_count  # must be at least called once
    assert post_mock.call_count  # same as above
    assert call("https://netbox.example.com/api/status/", ANY) in get_mock.mock_calls
    assert (
        call(
            device_query_template.substitute(
                device='"TEST0001"',
                autodesc_query_extension=FileTemplate(
                    "cosmo/clients/queries/device_autodesc_query.graphql"
                ).substitute(),
            ),
            ANY,
        )
        in post_mock.mock_calls
    )

    testEnv.stop()


@without_feature(features, "interface-auto-descriptions")
def test_autodesc_disabled(mocker):
    device_query_template = FileTemplate("cosmo/clients/queries/device.graphql")
    testEnv = utils.CommonSetup(mocker, cfgFile="cosmo/tests/cosmo.devgen_ansible.yml")
    rrm = utils.RequestResponseMock()
    get_mock = mocker.patch.object(rrm, "get_callback", new=SharedMock())
    post_mock = mocker.patch.object(rrm, "post_callback", new=SharedMock())

    with open(f"cosmo/tests/test_case_auto_descriptions.yaml") as f:
        test_data = yaml.safe_load(f)
        rrm.patchNetboxClient(mocker, **test_data)

    assert cosmoMain() == 0
    assert get_mock.call_count  # must be at least called once
    assert post_mock.call_count  # same as above
    assert call("https://netbox.example.com/api/status/", ANY) in get_mock.mock_calls
    assert (
        call(
            device_query_template.substitute(
                device='"TEST0001"',
                autodesc_query_extension=FileTemplate(
                    "cosmo/clients/queries/device_no_autodesc_query.graphql"
                ).substitute(),
            ),
            ANY,
        )
        in post_mock.mock_calls
    )

    testEnv.stop()


def test_invalid_config_file(mocker, capsys):
    testEnv = utils.CommonSetup(mocker, cfgFile="cosmo/tests/cosmo.wrong.yml")
    with pytest.raises(jsonschema.exceptions.ValidationError):
        cosmoMain()
    testEnv.stop()
