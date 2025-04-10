{
  description = "cosmo - ???";

  inputs.flake-utils.url = "github:numtide/flake-utils";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable-small";

  outputs = { self, nixpkgs, flake-utils }:
    {
      overlay = (final: prev: let 
        pyprojectFile = builtins.fromTOML (builtins.readFile ./pyproject.toml);
        # We absolutly want to ship our own deps, so we use our own python and our own python3Packages.
        pkgs = import nixpkgs {
          inherit (final) system;
        };
      in {
        cosmo = final.callPackage ./package.nix { python3 = pkgs.python3; python3Packages = pkgs.python3.pkgs; version = pyprojectFile.tool.poetry.version; };
      });
    } // (flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          overlays = [ self.overlay ];
        };
      in
      {
        packages = {
          cosmo = pkgs.cosmo;
          default = pkgs.cosmo;
        };

        devShell = pkgs.mkShell {
          buildInputs = [
            (pkgs.python3.withPackages (python-pkgs: with python-pkgs; [
              requests
              pyyaml 
              packaging 
              deepmerge 
              termcolor
              # Dev Dependencies
              mypy
              pytest
              pytest-cov
              pytest-mock
              types-pyyaml
              types-requests
            ]))
          ];
        };
      }));
}
