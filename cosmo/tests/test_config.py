import jsonschema.exceptions  # type: ignore
import pytest

from cosmo.config.cosmo_config import CosmoConfig


def test_load_config():
    config = CosmoConfig("cosmo/tests/cosmo.devgen_nix.yml")
    assert config
    assert config["output_format"] == "nix"
    assert config["asn"] == 65542
    assert config["devices"]
    assert "router" in config["devices"]
    assert config["devices"]["router"][0] == "TEST0001"
    assert "switch" in config["devices"]
    with pytest.raises(KeyError):
        assert config["invalidkey"]


def test_load_wrong_config():
    with pytest.raises(jsonschema.exceptions.ValidationError):
        CosmoConfig("cosmo/tests/cosmo.wrong.yml")
