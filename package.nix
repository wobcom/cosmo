{ python3Packages, version, ... }:

python3Packages.buildPythonApplication rec {
  inherit version;
  
  pname = "cosmo";
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
