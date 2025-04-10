{ python3Packages, ... }:

python3Packages.buildPythonApplication rec {
  pname = "cosmo";
  version = "0.10.1";
  pyproject = true;

  src = ./.;

  build-system = with python3Packages; [
    poetry-core
  ];

  dependencies = with python3Packages; [
    requests
    pyyaml 
    packaging 
    deepmerge 
    termcolor 
  ];
}
