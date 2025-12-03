{ buildPythonApplication,
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

  passthru = {
    pythonEnv = python.withPackages (_: dependencies);
  };
}
