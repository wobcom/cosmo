import yaml
from coverage.html import os

from cosmo.serializer import RouterSerializer, SwitchSerializer


def get_router_sd_from_path(path):
    dirname = os.path.dirname(__file__)
    test_case_name = os.path.join(dirname, path)

    test_case = open(test_case_name, 'r')
    test_data = yaml.safe_load(test_case)

    return [RouterSerializer(device=device, l2vpn_list=test_data['l2vpn_list'], vrfs=test_data['vrf_list']).serialize() for device in test_data['device_list']]

def get_switch_sd_from_path(path):
    dirname = os.path.dirname(__file__)
    test_case_name = os.path.join(dirname, path)

    test_case = open(test_case_name, 'r')
    test_data = yaml.safe_load(test_case)

    return [SwitchSerializer(device=device).serialize() for device in test_data['device_list']]

def test_router_physical_interface():
    [sd] = get_router_sd_from_path("./test_case_1.yaml")

    assert 'et-0/0/0' in sd['interfaces']
    assert 'physical' == sd['interfaces']['et-0/0/0']['type']
    assert 'Customer: Test-Port' == sd['interfaces']['et-0/0/0']['description']
    assert sd['interfaces']['et-0/0/0']['gigether']['autonegotiation']

    assert 'et-0/0/3' in sd['interfaces']
    assert 'Customer: Disabled Test-Port' == sd['interfaces']['et-0/0/3']['description']
    assert sd['interfaces']['et-0/0/3']['shutdown']
    assert sd['interfaces']['et-0/0/3']['mtu'] == 9000
    assert sd['interfaces']['et-0/0/3']['gigether']['speed'] == '10g'


def test_router_logical_interface():
    [sd] = get_router_sd_from_path("./test_case_2.yaml")

    assert 139 in sd['interfaces']['et-0/0/0']['units']

    unit = sd['interfaces']['et-0/0/0']['units'][139]

    assert "Customer: Test-VLAN" == unit['description']
    assert 139 == unit['vlan']


def test_router_lag():

    [sd] = get_router_sd_from_path("./test_case_lag.yaml")

    assert 'et-0/0/0' in sd['interfaces']
    assert 'et-0/0/1' in sd['interfaces']
    assert 'lag_member' in sd['interfaces']['et-0/0/0']['type']
    assert 'lag_member' in sd['interfaces']['et-0/0/1']['type']

    assert 'ae0' in sd['interfaces']
    assert 'lag' == sd['interfaces']['ae0']['type']


def test_router_fec():

    [sd] = get_router_sd_from_path("./test_case_fec.yaml")

    assert 'et-0/0/0' in sd['interfaces']
    assert 'et-0/0/1' in sd['interfaces']
    assert 'et-0/0/2' in sd['interfaces']

    assert sd['interfaces']['et-0/0/0']['gigether']['fec'] == 'fec91'
    assert sd['interfaces']['et-0/0/1']['gigether']['fec'] == 'fec74'
    assert sd['interfaces']['et-0/0/2']['gigether']['fec'] == 'none'


def test_router_case_mpls_evpn():

    sd = get_router_sd_from_path("./test_case_mpls_evpn.yaml")

    for d in sd:
        assert 'ae0' in d['interfaces']
        assert  338 in  d['interfaces']['ae0']['units']

        unit = d['interfaces']['ae0']['units'][338]

        assert unit['vlan'] == 338
        assert unit['encapsulation'] == "vlan-bridge"

        # mgmt Routing Instance and Routing Instance for L2VPN
        assert len(d['routing_instances']) == 2

        assert len(d['l2circuits']) == 0

        ri = d['routing_instances']['VS_MPLS_EVPN']
        # We need one interface in our routing instance
        assert len(ri['interfaces']) == 1

        assert ri['description'] == "MPLS-EVPN: MPLS_EVPN"

        assert ri['instance_type'] == "evpn"
        assert ri['protocols']['evpn'] == {}

        assert ri['route_distinguisher'] == '9136:338'
        assert ri['vrf_target'] == 'target:1:338'


def test_router_case_vpws():

    sd = get_router_sd_from_path("./test_case_vpws.yaml")

    for index, d in enumerate(sd):
        assert 'et-0/0/0' in d['interfaces']
        assert  0 in  d['interfaces']['et-0/0/0']['units']

        unit = d['interfaces']['et-0/0/0']['units'][0]

        assert unit == {}

        # mgmt Routing Instance and Routing Instance for L2VPN
        assert len(d['routing_instances']) == 2

        assert len(d['l2circuits']) == 0

        ri = d['routing_instances']['VS_VPWS']
        # We need one interface in our routing instance
        assert len(ri['interfaces']) == 1
        assert ri['interfaces'][0] == "et-0/0/0.0"

        assert ri['description'] == "VPWS: VPWS"

        assert ri['instance_type'] == "evpn-vpws"
        assert ri['protocols']['evpn']['interfaces']['et-0/0/0.0']['vpws_service_id']['local'] == 184384 + (index * -1)
        assert ri['protocols']['evpn']['interfaces']['et-0/0/0.0']['vpws_service_id']['remote'] == 184383 + (index * 1)

        assert ri['route_distinguisher'] == '9136:2708'
        assert ri['vrf_target'] == 'target:1:2708'


def test_router_case_local_l2x():

    [d] = get_router_sd_from_path("./test_case_local_l2x.yaml")

    assert 'ifp-0/0/4' in d['interfaces']
    assert 'ifp-0/0/5' in d['interfaces']
    assert len(d['interfaces']) == 2

    for name, interface in d['interfaces'].items():
        assert interface['type'] == 'physical'
        assert 7 in interface['units']

        unit = interface['units'][7]
        assert unit['encapsulation'] == 'vlan-ccc'
        assert unit['vlan'] == 7

    # mgmt Routing Instance
    assert len(d['routing_instances']) == 1

    assert len(d['l2circuits']) == 1

    l2c = d['l2circuits']['L2X']

    assert len(l2c['interfaces']) == 2
    assert l2c['description'] == 'EVPL: L2X via TEST0001'

    assert l2c['interfaces']['ifp-0/0/4.7']['local_label'] == l2c['interfaces']['ifp-0/0/5.7']['remote_label']
    assert l2c['interfaces']['ifp-0/0/5.7']['local_label'] == l2c['interfaces']['ifp-0/0/4.7']['remote_label']

    assert l2c['interfaces']['ifp-0/0/4.7']['remote_ip'] == '45.139.136.10'
    assert l2c['interfaces']['ifp-0/0/5.7']['remote_ip'] == '45.139.136.10'



def test_router_case_local_l3vpn():

    [d] = get_router_sd_from_path("./test_case_l3vpn.yml")

    # We do not need to check the interfaces further, there is no configuration to be found there.
    assert 'ifp-0/1/2' in d['interfaces']
    assert 'lo-0/0/0' in d['interfaces']
    assert len(d['interfaces']) == 2

    assert 'L3VPN' in d['routing_instances']

    ri = d['routing_instances']['L3VPN']

    assert len(ri['interfaces']) == 1
    assert ri['interfaces'][0] == "ifp-0/1/2.100"
    assert ri['instance_type'] == "vrf"

    assert ri['route_distinguisher'] == '45.139.136.10:407'
    assert len(ri['import_targets']) == 1
    assert ri['import_targets'][0] == "target:9136:407"
    assert len(ri['export_targets']) == 1
    assert ri['export_targets'][0] == "target:9136:407"

    assert ri['routing_options'] == {}

def test_switch_mgmt_interface():
    [sd] = get_switch_sd_from_path('./test_case_switch_mgmt.yaml')

    # mgmt port is present
    assert 'eth0' in sd['cumulus__device_interfaces']
    assert 'address' in sd['cumulus__device_interfaces']['eth0']
    # ipv4 parameters are set
    assert '10.120.142.11/24' == sd['cumulus__device_interfaces']['eth0']['address']
    assert '10.120.142.1' == sd['cumulus__device_interfaces']['eth0']['gateway']
    # vrf is set
    assert 'mgmt' == sd['cumulus__device_interfaces']['eth0']['vrf']

def test_switch_case_lag():
    [sd] = get_switch_sd_from_path('./test_case_switch_lag.yaml')

    # check that the switchports are present
    assert 'swp17' in sd['cumulus__device_interfaces']
    assert 'swp18' in sd['cumulus__device_interfaces']
    # check lag construction
    assert 'lag_42' in sd['cumulus__device_interfaces']
    assert 'bond_mode' in sd['cumulus__device_interfaces']['lag_42']
    assert '802.3ad' == sd['cumulus__device_interfaces']['lag_42']['bond_mode']
    # check that the interfaces are registered as lag members
    assert 'swp18' in sd['cumulus__device_interfaces']['lag_42']['bond_slaves']
    assert 'swp17' in sd['cumulus__device_interfaces']['lag_42']['bond_slaves']
