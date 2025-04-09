import re
import yaml
import pytest
import copy

from cosmo.common import L2VPNSerializationError
from coverage.html import os

from cosmo.serializer import RouterSerializer, SwitchSerializer


def _yaml_load(path):
    dirname = os.path.dirname(__file__)
    test_case_name = os.path.join(dirname, path)
    test_case = open(test_case_name, 'r')
    test_data = yaml.safe_load(test_case)
    return test_data


def get_router_s_from_path(path):
    test_data = _yaml_load(path)
    return [
        RouterSerializer(device=device, l2vpn_list=test_data['l2vpn_list'],
                         loopbacks=test_data.get('loopbacks', {}))
        for device in test_data['device_list']]


def get_switch_s_from_path(path):
    test_data = _yaml_load(path)
    return [SwitchSerializer(device=device) for device in test_data['device_list']]


def get_router_sd_from_path(path):
    return list(map(lambda s: s.serialize(), get_router_s_from_path(path)))


def get_switch_sd_from_path(path):
    return list(map(lambda s: s.serialize(), get_switch_s_from_path(path)))


def test_router_platforms():
    [juniper_s] = get_router_s_from_path("./test_case_2.yaml")
    assert juniper_s.mgmt_routing_instance == "mgmt_junos"
    assert juniper_s.mgmt_interface == "fxp0"
    assert juniper_s.bmc_interface == None

    [rtbrick_s] = get_router_s_from_path("./test_case_l3vpn.yml")
    assert rtbrick_s.mgmt_routing_instance == "mgmt"
    assert rtbrick_s.mgmt_interface == "ma1"
    assert rtbrick_s.bmc_interface == "bmc0"

    with pytest.raises(Exception, match="unsupported platform vendor: ACME"):
        get_router_s_from_path("./test_case_vendor_unknown.yaml")

    with pytest.raises(Exception, match="missing key"):
        get_router_s_from_path("./test_case_no_manuf_slug.yaml")


def test_l2vpn_errors(capsys):
    serialize = lambda y: \
        RouterSerializer(device=y['device_list'][0], l2vpn_list=y['l2vpn_list'],
                         loopbacks=y['loopbacks']).serialize()

    template = _yaml_load("./test_case_l2x_err_template.yaml")

    vpws_incorrect_terminations = copy.deepcopy(template)
    vpws_incorrect_terminations['l2vpn_list'].append({
        '__typename': 'L2VPNType',
        'id': '53',
        'identifier': 123456,
        'name': 'WAN: incorrect VPWS',
        'type': 'VPWS',
        'terminations': [
            {
                '__typename': 'L2VPNTerminationType',
                'assigned_object': {}
            }, {
                '__typename': 'L2VPNTerminationType',
                'assigned_object': {}
            }, {
                '__typename': 'L2VPNTerminationType',
                'assigned_object': {}
            }]})
    serialize(vpws_incorrect_terminations)
    capture = capsys.readouterr()
    assert re.search("VPWS circuits are only allowed to have 2 terminations", capture.out)

    unsupported_type_terminations = copy.deepcopy(template)
    unsupported_type_terminations['l2vpn_list'].append({
        '__typename': 'L2VPNType',
        'id': '54',
        'identifier': 123456,
        'name': 'WAN: unsupported termination types 1',
        'type': 'VPWS',
        'terminations': [
            {
                '__typename': 'L2VPNTerminationType',
                'assigned_object': None
            },
            {
                '__typename': 'L2VPNTerminationType',
                'assigned_object': {}
            }]})
    serialize(unsupported_type_terminations)
    capture = capsys.readouterr()
    assert re.search("VPWS L2VPN does not support|Found unsupported L2VPN termination in", capture.out)

    vpws_non_interface_term = copy.deepcopy(template)
    vpws_non_interface_term['l2vpn_list'].append({
        '__typename': 'L2VPNType',
        'id': '54',
        'identifier': 123456,
        'name': 'WAN: WAN: unsupported termination types 2',
        'type': 'VPWS',
        'terminations': [
            {
                '__typename': 'L2VPNTerminationType',
                'assigned_object': {
                '__typename': "VLANType"
            }},
            {
                '__typename': 'L2VPNTerminationType',
                'assigned_object': {
                '__typename': "VLANType"
            }}]})
    serialize(vpws_non_interface_term)
    capture = capsys.readouterr()
    assert re.search("VPWS L2VPN does not support|Found unsupported L2VPN termination in", capture.out)

    vpws_missing_identifier = copy.deepcopy(template)
    vpws_missing_identifier['l2vpn_list'].append({
        '__typename': 'L2VPNType',
        'id': '54',
        'identifier': None,
        'name': 'WAN: WAN: missing L2VPN identifier',
        'type': 'evpn-vpws',
        'terminations': [
            {
                '__typename': 'L2VPNTerminationType',
                'assigned_object': {
                    '__typename': "InterfaceType"
                }
            },
            {
                '__typename': 'L2VPNTerminationType',
                'assigned_object': {
                    '__typename': "InterfaceType"
                }
            }
        ]
    })
    serialize(vpws_missing_identifier)
    capture = capsys.readouterr()
    assert re.search("L2VPN identifier is mandatory.", capture.out)


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
    assert sd['interfaces']['et-0/0/3']['breakout'] == '4x10g'


def test_router_logical_interface():
    [sd] = get_router_sd_from_path("./test_case_2.yaml")

    assert len(sd['interfaces']['et-0/0/0']['units']) == 2

    assert 139 in sd['interfaces']['et-0/0/0']['units']
    assert 150 in sd['interfaces']['et-0/0/0']['units']
    # should be present but shut down
    assert sd['interfaces']['et-0/0/0']['units'][150]['shutdown']

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


def test_router_vrf_rib():
    [sd] = get_router_sd_from_path("./test_case_vrf_staticroute.yaml")

    assert 'routing_instances' in sd
    assert 'L3VPN-TEST' in sd['routing_instances']
    assert 'routing_options' in sd['routing_instances']['L3VPN-TEST']
    assert 'rib' in sd['routing_instances']['L3VPN-TEST']['routing_options']
    assert 'L3VPN-TEST.inet.0' in sd['routing_instances']['L3VPN-TEST']['routing_options']['rib']
    assert 'L3VPN-TEST.inet.0' in sd['routing_instances']['L3VPN-TEST']['routing_options']['rib']
    rib = sd['routing_instances']['L3VPN-TEST']['routing_options']['rib']
    assert 'L3VPN-TEST.inet.0' in rib
    assert 'L3VPN-TEST.inet6.0' in rib
    assert 'static' in rib['L3VPN-TEST.inet.0']
    assert 'static' in rib['L3VPN-TEST.inet6.0']
    assert '10.114.23.36/32' in rib['L3VPN-TEST.inet.0']['static']
    assert 'fd98::1/128' in rib['L3VPN-TEST.inet6.0']['static']
    assert 'next_hop' in rib['L3VPN-TEST.inet.0']['static']['10.114.23.36/32']
    assert 'next_hop' in rib['L3VPN-TEST.inet6.0']['static']['fd98::1/128']
    assert rib['L3VPN-TEST.inet.0']['static']['10.114.23.36/32']['next_hop'] == '10.30.0.154'
    assert rib['L3VPN-TEST.inet6.0']['static']['fd98::1/128']['next_hop'] == 'et-0/0/2.0'
    assert rib['L3VPN-TEST.inet6.0']['static']['fd98::1/128']['metric'] == 100


def test_router_ips():
    [sd] = get_router_sd_from_path("./test_case_ips.yaml")

    assert 'ifp-0/0/2' in sd['interfaces']
    assert 'ifp-0/0/3' in sd['interfaces']
    assert 0 in sd['interfaces']['ifp-0/0/2']['units']
    assert 0 in sd['interfaces']['ifp-0/0/3']['units']

    unit_v4 = sd['interfaces']['ifp-0/0/2']['units'][0]
    unit_v6 = sd['interfaces']['ifp-0/0/3']['units'][0]
    mgmt_v4 = sd['interfaces']['fxp0']['units'][0]
    mgtm_routing_instance_rib = sd['routing_instances']['mgmt_junos']['routing_options']['rib']['mgmt_junos.inet.0']


    assert mgmt_v4['families']['inet']['address']['192.168.1.23/24'] == {}
    assert mgtm_routing_instance_rib['static']['0.0.0.0/0']['next_hop'] == "192.168.1.1"

    assert unit_v4['families']['inet']['address']['45.139.138.1/29'] == {}
    assert unit_v4['families']['inet']['address']['45.139.138.8/29'] == {"primary": True}
    assert unit_v4['families']['inet']['address']['45.139.138.9/29'] == {"secondary": True}

    assert unit_v6['families']['inet6']['address']['2a0e:b941:2::/122'] == {}
    assert unit_v6['families']['inet6']['address']['2a0e:b941:2::40/122'] == {"primary": True}
    assert unit_v6['families']['inet6']['address']['2a0e:b941:2::41/122'] == {"secondary": True}

    # reverse path filtering
    assert unit_v4['families']['inet']['rpf_check']['mode'] == 'loose'
    assert 'inet6' not in unit_v4['families']
    assert unit_v6['families']['inet6']['rpf_check']['mode'] == 'strict'
    assert 'inet' not in unit_v6['families']

    # router advertisement
    assert unit_v6['families']['inet6']['ipv6_ra'] == True


def test_router_case_mpls_evpn():
    sd = get_router_sd_from_path("./test_case_mpls_evpn.yaml")

    for d in sd:
        assert 'ae0' in d['interfaces']
        assert 338 in d['interfaces']['ae0']['units']

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
        assert 0 in d['interfaces']['et-0/0/0']['units']

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


def test_router_case_local_bgpcpe():
    [d] = get_router_sd_from_path("./test_case_bgpcpe.yml")

    # We do not need to check the interfaces further, there is no configuration to be found there.
    assert 'ifp-0/1/2' in d['interfaces']
    assert 3 in d['interfaces']['ifp-0/1/2']['units']
    assert 4 in d['interfaces']['ifp-0/1/2']['units']
    assert 5 in d['interfaces']['ifp-0/1/2']['units']
    assert 'lo-0/0/0' in d['interfaces']
    assert len(d['interfaces']) == 2

    assert 'protocols' in d['routing_instances']['default']
    assert 'bgp' in d['routing_instances']['default']['protocols']

    groups_default = d['routing_instances']['default']['protocols']['bgp']['groups']
    assert len(groups_default) == 1
    assert 'CPE_ifp-0-1-2-3' in groups_default
    assert groups_default['CPE_ifp-0-1-2-3']['neighbors'][0]['interface'] == 'ifp-0/1/2.3'
    assert groups_default['CPE_ifp-0-1-2-3']['family']['ipv4_unicast']['policy']['export'] == 'DEFAULT_V4'
    assert groups_default['CPE_ifp-0-1-2-3']['family']['ipv6_unicast']['policy']['export'] == 'DEFAULT_V6'
    assert groups_default['CPE_ifp-0-1-2-3']['family']['ipv4_unicast']['policy']['import_list'] == ["10.1.0.0/28"]
    assert groups_default['CPE_ifp-0-1-2-3']['family']['ipv6_unicast']['policy']['import_list'] == ['2a0e:b941:2:42::/64', '2a0e:b941:2::/122']

    groups_L3VPN = d['routing_instances']['L3VPN']['protocols']['bgp']['groups']
    
    assert 'CPE_ifp-0-1-2-4' in groups_L3VPN
    assert groups_L3VPN['CPE_ifp-0-1-2-4']['neighbors'][0]['interface'] == 'ifp-0/1/2.4'
    assert not 'export' in groups_L3VPN['CPE_ifp-0-1-2-4']['family']['ipv4_unicast']['policy']
    assert not 'export' in groups_L3VPN['CPE_ifp-0-1-2-4']['family']['ipv6_unicast']['policy']
    assert groups_L3VPN['CPE_ifp-0-1-2-4']['family']['ipv4_unicast']['policy']['import_list'] == ["10.1.0.0/28"]
    assert groups_L3VPN['CPE_ifp-0-1-2-4']['family']['ipv6_unicast']['policy']['import_list'] == ['2a0e:b941:2:42::/64', '2a0e:b941:2::/122']
    
    assert 'CPE_ifp-0-1-2-5_V4' in groups_L3VPN
    assert 'CPE_ifp-0-1-2-5_V6' in groups_L3VPN
    assert groups_L3VPN['CPE_ifp-0-1-2-5_V4']['neighbors'][0]['peer'] == '10.128.6.12'
    assert groups_L3VPN['CPE_ifp-0-1-2-5_V6']['neighbors'][0]['peer'] == '2a0e:b941:2::21'
    assert not 'export' in groups_L3VPN['CPE_ifp-0-1-2-5_V4']['family']['ipv4_unicast']['policy']
    assert not 'export' in groups_L3VPN['CPE_ifp-0-1-2-5_V6']['family']['ipv6_unicast']['policy']
    assert groups_L3VPN['CPE_ifp-0-1-2-5_V4']['family']['ipv4_unicast']['policy']['import_list'] == ["10.1.0.0/28"]
    # should not be allowed to announce our transfer nets, so '2a0e:b941:2::/122' should not be there
    assert groups_L3VPN['CPE_ifp-0-1-2-5_V6']['family']['ipv6_unicast']['policy']['import_list'] == ['2a0e:b941:2:42::/64']


def test_router_case_policer():
    [d] = get_router_sd_from_path("./test_case_policer.yaml")

    assert 'ae0' in d['interfaces']
    assert 'units' in d['interfaces']['ae0']
    assert 2220 in d['interfaces']['ae0']['units']
    assert 'policer' in d['interfaces']['ae0']['units'][2220]
    assert 'POLICER_100M' in d['interfaces']['ae0']['units'][2220]['policer']['input']
    assert 'POLICER_100M' in d['interfaces']['ae0']['units'][2220]['policer']['output']

    assert 101 in d['interfaces']['ae0']['units']
    assert 'families' in d['interfaces']['ae0']['units'][101]
    assert 'inet' in d['interfaces']['ae0']['units'][101]['families']
    assert 'inet6' in d['interfaces']['ae0']['units'][101]['families']
    assert d['interfaces']['ae0']['units'][101]['families']['inet']['policer'] == ['arp POLICER_IXP_ARP']
    assert d['interfaces']['ae0']['units'][101]['families']['inet']['filters'] == ['input-list [ EDGE_FILTER ]']
    assert d['interfaces']['ae0']['units'][101]['families']['inet6']['filters'] == ['input-list [ EDGE_FILTER_V6 ]']
    assert d['interfaces']['ae0']['units'][101]['families']['inet6']['sampling'] == True


def test_switch_lldp():
    [sd] = get_switch_sd_from_path('./test_case_switch_lldp.yaml')

    assert 'swp52' in sd['cumulus__device_interfaces']
    assert 'lldp' in sd['cumulus__device_interfaces']['swp52']
    assert True == sd['cumulus__device_interfaces']['swp52']['lldp']


def test_switch_vlans():
    [sd] = get_switch_sd_from_path('./test_case_switch_vlan.yaml')

    # check that access port gets their vid added
    assert 'swp1' in sd['cumulus__device_interfaces']
    assert 42 == sd['cumulus__device_interfaces']['swp1']['untagged_vlan']
    # check that it was added to bridge tagged vlans
    assert 42 in sd['cumulus__device_interfaces']['bridge']['tagged_vlans']
    # hybrid port should be taken into account, and VIDs are in order
    assert 'tagged_vlans' in sd['cumulus__device_interfaces']['lag_2000']
    assert 'untagged_vlan' in sd['cumulus__device_interfaces']['lag_2000']
    assert 103 == sd['cumulus__device_interfaces']['lag_2000']['untagged_vlan']
    # untagged vlans belong to vid list as well
    assert [101, 102, 103] == sd['cumulus__device_interfaces']['lag_2000']['tagged_vlans']
    # check bridge attrs
    assert 10000 == sd['cumulus__device_interfaces']['bridge']['mtu']
    assert sorted(['swp1', 'lag_2000']) == sd['cumulus__device_interfaces']['bridge']['bridge_ports']


def test_switch_mgmt_interface():
    [sd] = get_switch_sd_from_path('./test_case_switch_mgmt.yaml')

    # mgmt port is present
    assert 'eth0' in sd['cumulus__device_interfaces']
    assert 'address' in sd['cumulus__device_interfaces']['eth0']
    # also check bpdufilter is removed
    assert 'bpdufilter' not in sd['cumulus__device_interfaces']['eth0'].keys()
    # check that bpdufilter is present on eth1 (no ip address assigned)
    assert 'bpdufilter' in sd['cumulus__device_interfaces']['eth1'].keys()
    assert sd['cumulus__device_interfaces']['eth1']['bpdufilter'] == True
    # ipv4 parameters are set
    assert '10.120.142.11/24' == sd['cumulus__device_interfaces']['eth0']['address']
    assert '10.120.142.1' == sd['cumulus__device_interfaces']['eth0']['gateway']
    # vrf is set
    assert 'mgmt' == sd['cumulus__device_interfaces']['eth0']['vrf']
    # description is set (optional)
    assert 'management interface' == sd['cumulus__device_interfaces']['eth0']['description']


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


def test_switch_interface_speed(capsys):
    [sd] = get_switch_sd_from_path('./test_case_switch_interface_speed.yaml')
    captured = capsys.readouterr()
    assert re.search("Interface speed 100m on interface swp4 is not known", captured.out)

    # check all switchports are present
    assert 'swp1' in sd['cumulus__device_interfaces']
    assert 'swp2' in sd['cumulus__device_interfaces']
    assert 'swp3' in sd['cumulus__device_interfaces']
    assert 'swp4' in sd['cumulus__device_interfaces']

    # check that interface speeds are okay
    assert sd['cumulus__device_interfaces']['swp1']['speed'] == 1000
    assert sd['cumulus__device_interfaces']['swp2']['speed'] == 10000
    assert sd['cumulus__device_interfaces']['swp3']['speed'] == 100000


def test_switch_interface_fec(capsys):
    [sd] = get_switch_sd_from_path("./test_case_switch_fec.yaml")
    captured = capsys.readouterr()
    assert re.search("FEC mode undefined on interface swp4 is not known", captured.out)

    assert 'swp1' in sd['cumulus__device_interfaces']
    assert 'swp2' in sd['cumulus__device_interfaces']
    assert 'swp3' in sd['cumulus__device_interfaces']
    assert 'swp4' in sd['cumulus__device_interfaces']

    assert sd['cumulus__device_interfaces']['swp1']['fec'] == 'rs'
    assert sd['cumulus__device_interfaces']['swp2']['fec'] == 'baser'
    assert sd['cumulus__device_interfaces']['swp3']['fec'] == 'off'
