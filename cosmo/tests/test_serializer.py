import yaml
from coverage.html import os

from cosmo.serializer import RouterSerializer


def get_sc_from_path(path):
    dirname = os.path.dirname(__file__)
    test_case_name = os.path.join(dirname, path)

    test_case = open(test_case_name, 'r')
    test_data = yaml.safe_load(test_case)

    router_serializer = RouterSerializer(
        device=test_data['device_list'][0],
        l2vpn_list=[],
        vrfs=[],
    )

    return router_serializer.serialize()


def test_physical_interface():
    sc = get_sc_from_path("./test_case_1.yaml")

    assert 'et-0/0/0' in sc['interfaces']
    assert 'physical' == sc['interfaces']['et-0/0/0']['type']
    assert 'Customer: Test-Port' == sc['interfaces']['et-0/0/0']['description']
    assert sc['interfaces']['et-0/0/0']['gigether']['autonegotiation']

    assert 'et-0/0/3' in sc['interfaces']
    assert 'Customer: Disabled Test-Port' == sc['interfaces']['et-0/0/3']['description']
    assert sc['interfaces']['et-0/0/3']['shutdown']
    assert sc['interfaces']['et-0/0/3']['mtu'] == 9000
    assert sc['interfaces']['et-0/0/3']['gigether']['speed'] == '10g'


def test_logical_interface():
    sc = get_sc_from_path("./test_case_2.yaml")

    assert 139 in sc['interfaces']['et-0/0/0']['units']

    unit = sc['interfaces']['et-0/0/0']['units'][139]

    assert "Customer: Test-VLAN" == unit['description']
    assert 139 == unit['vlan']


def test_lag():

    sc = get_sc_from_path("./test_case_lag.yaml")

    assert 'et-0/0/0' in sc['interfaces']
    assert 'et-0/0/1' in sc['interfaces']
    assert 'lag_member' in sc['interfaces']['et-0/0/0']['type']
    assert 'lag_member' in sc['interfaces']['et-0/0/1']['type']

    assert 'ae0' in sc['interfaces']
    assert 'lag' == sc['interfaces']['ae0']['type']


def test_fec():

    sc = get_sc_from_path("./test_case_fec.yaml")

    assert 'et-0/0/0' in sc['interfaces']
    assert 'et-0/0/1' in sc['interfaces']
    assert 'et-0/0/2' in sc['interfaces']

    assert sc['interfaces']['et-0/0/0']['gigether']['fec'] == 'fec91'
    assert sc['interfaces']['et-0/0/1']['gigether']['fec'] == 'fec74'
    assert sc['interfaces']['et-0/0/2']['gigether']['fec'] == 'none'


