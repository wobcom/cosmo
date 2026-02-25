# implementation guide
# https://martinfowler.com/articles/feature-toggles.html
import functools
from argparse import Action, ArgumentParser
from typing import Never, Self, Optional, TextIO, Sequence, Any, Callable

import yaml


class NonExistingFeatureToggleException(Exception):
    pass


class FeatureToggle:
    CFG_KEY = "features"

    def __init__(self, features_default_config: dict[str, bool]):
        self._store: dict[str, bool] = features_default_config
        self._authorized_keys = list(features_default_config.keys())

    def checkFeatureExistsOrRaise(self, key: str) -> bool | Never:
        if key in self._authorized_keys:
            return True
        raise NonExistingFeatureToggleException(
            f"feature toggle {key} is unknown, please check your code"
        )

    def getAllFeatureNames(self) -> list[str]:
        return self._authorized_keys

    def featureIsEnabled(self, key: str) -> bool:
        self.checkFeatureExistsOrRaise(key)
        return bool(self._store.get(key))

    def setFeature(self, key: str, toggle: bool) -> Self:
        self.checkFeatureExistsOrRaise(key)
        self._store[key] = toggle
        return self  # chain

    def setFeatures(self, config: dict[str, bool]) -> Self:
        for feature_key, feature_toggle in config.items():
            self.setFeature(feature_key, feature_toggle)
        return self  # chain

    def setFeaturesFromConfig(self, config: dict) -> Self:
        config_dict = dict(config.get(self.CFG_KEY, dict()))
        self.setFeatures(config_dict)
        return self

    def setFeaturesFromYAML(self, yaml_stream_or_str: TextIO | str) -> Self:
        config = yaml.safe_load(yaml_stream_or_str)
        self.setFeaturesFromConfig(config)
        return self

    def setFeaturesFromYAMLFile(self, path: str) -> Self:
        with open(path, "r") as cfg_file:
            self.setFeaturesFromYAML(cfg_file)
        return self

    def toggleFeatureActionFactory(self, toggle_to: bool) -> type[Action]:
        feature_toggle_instance = self

        class ToggleFeatureAction(Action):
            def __call__(
                self,
                parser: ArgumentParser,
                namespace: object,
                values: str | Sequence[Any] | None,
                option_string: Optional[str] = None,
            ):
                if type(values) is list:
                    [feature_toggle_instance.setFeature(v, toggle_to) for v in values]
                elif type(values) is str:
                    feature_toggle_instance.setFeature(values, toggle_to)
                setattr(namespace, self.dest, values)

        return ToggleFeatureAction

    def __str__(self):
        features_desc = []
        conv = {True: "ENABLED", False: "DISABLED"}
        for feature, state in self._store.items():
            features_desc.append(f"{feature}: {conv.get(state)}")
        return ", ".join(features_desc)


def _feature_toggler_decorator_gen(
    instance: FeatureToggle, feature_name: str, target_state: bool
):
    def decorator_with_feature(func: Callable):
        @functools.wraps(func)
        def exe_with_feature(*args, **kwargs):
            previous_state = instance.featureIsEnabled(feature_name)
            instance.setFeature(feature_name, target_state)
            func(*args, **kwargs)
            instance.setFeature(feature_name, previous_state)

        return exe_with_feature

    return decorator_with_feature


def with_feature(instance: FeatureToggle, feature_name: str):
    return _feature_toggler_decorator_gen(instance, feature_name, True)


def without_feature(instance: FeatureToggle, feature_name: str):
    return _feature_toggler_decorator_gen(instance, feature_name, False)


features = FeatureToggle(
    {
        "interface-auto-descriptions": True,
        "new-bgp-cpe-group-naming": False,
        "allow-private-ips-default-vrf": False,
        "netbox-loopback-interface-type": False,
    }
)
