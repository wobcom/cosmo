import json
import os
from os import PathLike
from pathlib import Path
from typing import Never, Final

import yaml
from jsonschema import validate  # type: ignore

from cosmo.features import features


class CosmoConfig:
    SCHEMA_PATH = Path(__file__).parent.joinpath(Path("cosmo_config.schema.json"))
    GLOBAL_VRF_KEY = "global_vrf"

    @staticmethod
    def get_raw_config(config_file_path) -> str | Never:
        if not os.path.isfile(config_file_path):
            raise Exception(
                f"Missing {config_file_path}, please provide a configuration"
            )
        with open(config_file_path, "r") as cfg_file_fd:
            return cfg_file_fd.read()  # let exception bubble up

    def _validate(self, raw_config: str) -> dict | Never:
        with open(self.SCHEMA_PATH, "r") as schema_file_fd:
            schema = json.load(schema_file_fd)
            cosmo_configuration = yaml.safe_load(raw_config)
            validate(
                instance=cosmo_configuration, schema=schema
            )  # let exception bubble up
            return cosmo_configuration

    def __init__(self, config_file_path: str | PathLike | bytes):
        self.raw_config = self.get_raw_config(config_file_path)
        self._store = self._validate(self.raw_config)

    def __getitem__(self, key):
        return self._store[key]

    def get(self, *args, **kwargs):
        return self._store.get(*args, **kwargs)

    def toDict(self) -> dict:
        return self._store

    def getGlobalVRFName(self) -> str:
        return self.get(self.GLOBAL_VRF_KEY)
