{ buildPythonApplication,
  python,
  poetry-core,
  requests,
  pyyaml,
  packaging,
  deepmerge,
  termcolor,
  multimethod,
  jsonschema,
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
    jsonschema
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
    (callPackage (
      { buildPythonPackage, fetchPypi, setuptools, referencing }:
      buildPythonPackage rec {
        pname = "types-jsonschema";
        version = "4.26.0.20260202";

        src = fetchPypi {
          inherit version;
          pname = "types_jsonschema";
          hash = "sha256-KYMbqkMIhlqa7FR6YXl6BvwVKw2sjd3VMeAC8yJlywc=";
        };

        format = "pyproject";
        build-system = [ setuptools ];

        dependencies = [
          referencing
        ];
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
