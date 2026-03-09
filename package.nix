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
  callPackage,
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
    (callPackage (
      { buildPythonPackage, fetchPypi, setuptools }:
      buildPythonPackage rec {
        pname = "sharedmock";
        version = "0.1.0";

        format = "pyproject";
        build-system = [ setuptools ];

        src = fetchPypi {
          inherit pname version;
          hash = "sha256-gHEE/KSLe8TMQmDL8jXidpSBgerRX8ZTU4ldOioL7MA=";
        };
      }
    ) {})
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
