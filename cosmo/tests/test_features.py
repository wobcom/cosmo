import argparse
import os.path

import pytest

from cosmo.features import (
    NonExistingFeatureToggleException,
    FeatureToggle,
    with_feature,
    without_feature,
)


def test_set_get():
    ft = FeatureToggle({"feature_a": False, "feature_b": False})

    ft.setFeature("feature_a", True)
    assert ft.featureIsEnabled("feature_a")

    ft.setFeature("feature_a", False)
    assert not ft.featureIsEnabled("feature_a")

    ft.setFeatures({"feature_a": True, "feature_b": True})
    assert ft.featureIsEnabled("feature_a")
    assert ft.featureIsEnabled("feature_b")


def test_config_from_str():
    ft = FeatureToggle({"feature_a": False, "feature_b": False})
    yaml_config = """
    features:
      feature_a: NO
      feature_b: YES
    """

    ft.setFeaturesFromYAML(yaml_config)
    assert not ft.featureIsEnabled("feature_a")
    assert ft.featureIsEnabled("feature_b")

    ft.setFeaturesFromYAMLFile(
        os.path.join(os.path.dirname(__file__), "cosmo-test-features-toggles.yaml")
    )
    assert ft.featureIsEnabled("feature_a")
    assert not ft.featureIsEnabled("feature_b")


def test_get_feature_names():
    features_dict = {
        "feature_a": True,
        "feature_b": False,
        "feature_c": False,
        "feature_d": True,
    }
    ft = FeatureToggle(features_dict)
    assert list(features_dict.keys()) == ft.getAllFeatureNames()


def test_non_existing_features():
    ft = FeatureToggle({"feature_a": True})

    with pytest.raises(NonExistingFeatureToggleException):
        ft.setFeature("i-do-not-exist", True)


def test_with_feature_decorator():
    ft = FeatureToggle({"feature_a": False})

    @with_feature(ft, "feature_a")
    def execute_with_decorator():
        assert ft.featureIsEnabled("feature_a")

    execute_with_decorator()
    assert not ft.featureIsEnabled("feature_a")


def test_without_feature_decorator():
    ft = FeatureToggle({"feature_a": True})

    @without_feature(ft, "feature_a")
    def execute_with_decorator():
        assert not ft.featureIsEnabled("feature_a")

    execute_with_decorator()
    assert ft.featureIsEnabled("feature_a")


def test_argparse_integration():
    ft = FeatureToggle({"feature_a": False, "feature_b": False, "feature_c": True})

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--enable-feature",
        default=[],
        metavar="ENABLED_FEATURE",
        action=ft.toggleFeatureActionFactory(True),
        choices=ft.getAllFeatureNames(),
        dest="yesfeatures",
        help="selectively enable features",
    )
    parser.add_argument(
        "--disable-feature",
        default=[],
        metavar="DISABLED_FEATURE",
        action=ft.toggleFeatureActionFactory(False),
        choices=ft.getAllFeatureNames(),
        dest="nofeatures",
        help="selectively disable features",
    )

    parser.parse_args(
        [
            "--enable-feature",
            "feature_a",
            "--enable-feature",
            "feature_b",
            "--disable-feature",
            "feature_c",
        ]
    )

    assert ft.featureIsEnabled("feature_a")
    assert ft.featureIsEnabled("feature_b")
    assert not ft.featureIsEnabled("feature_c")
