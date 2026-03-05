import json
import os
from os import PathLike
from pathlib import Path
from typing import Never

import yaml
from jsonschema import validate

from cosmo.features import features


class CosmoConfig:
    SCHEMA_PATH = Path(__file__).parent.joinpath(Path("cosmo_config.schema.json"))

    @staticmethod
    def get_raw_config(config_file_path) -> str | Never:
        if not os.path.isfile(config_file_path):
            raise Exception(
                f"Missing {config_file_path}, please provide a configuration"
            )
        with open(config_file_path, "r") as cfg_file_fd:
            return cfg_file_fd.read()  # let exception bubble up

    @staticmethod
    def _expand_schema_with_dynamic_features(schema):
        for ft in features.getAllFeatureNames():
            schema["properties"]["features"]["properties"][ft] = {"type": "boolean"}

    def _validate(self, raw_config: str) -> dict | Never:
        with open(self.SCHEMA_PATH, "r") as schema_file_fd:
            schema = json.load(schema_file_fd)
            self._expand_schema_with_dynamic_features(schema)
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
