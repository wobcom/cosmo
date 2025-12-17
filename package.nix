{ lib,
  stdenv,
  buildPythonApplication,
  python,
  poetry-core,
  requests,
  pyyaml,
  packaging,
  deepmerge,
  termcolor,
  multimethod,
  cosmo-version,
  pytestCheckHook,
  pytest-mock,
  coverage,
}:

buildPythonApplication rec {
  pname = "cosmo";
  version = cosmo-version;
  pyproject = true;

  src = ./.;

  build-system = [
    poetry-core
  ];

  dependencies = [
    requests
    pyyaml 
    packaging 
    deepmerge 
    termcolor 
    multimethod
  ];

  nativeCheckInputs = [
    pytestCheckHook
    pytest-mock
    coverage
  ];

  disabledTests = lib.optionals stdenv.hostPlatform.isDarwin [
    # https://github.com/wobcom/cosmo/issues/85
    "test_limit_argument_with_commas"
    "test_limit_arguments_with_repeat"
    "test_device_generation_ansible"
    "test_device_generation_nix"
    "test_device_processing_error"
    "test_case_get_data"
  ];

  passthru = {
    pythonEnv = python.withPackages (_: dependencies);
  };
}
