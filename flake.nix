{
  description = "cosmo - ???";

  inputs.flake-utils.url = "github:numtide/flake-utils";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable-small";

  inputs.pyproject-nix = {
    url = "github:pyproject-nix/pyproject.nix";
    inputs.nixpkgs.follows = "nixpkgs";
  };

  inputs.uv2nix = {
    url = "github:pyproject-nix/uv2nix";
    inputs.pyproject-nix.follows = "pyproject-nix";
    inputs.nixpkgs.follows = "nixpkgs";
  };

  inputs.pyproject-build-systems = {
    url = "github:pyproject-nix/build-system-pkgs";
    inputs.pyproject-nix.follows = "pyproject-nix";
    inputs.uv2nix.follows = "uv2nix";
    inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { self, nixpkgs, flake-utils, uv2nix, pyproject-nix, pyproject-build-systems }:
    let
      workspace = uv2nix.lib.workspace.loadWorkspace {
        workspaceRoot = ./.;
      };
    in
      {
        # Nixpkgs overlay providing the application
        overlay = nixpkgs.lib.composeManyExtensions [
          pyproject-build-systems.overlays.default
          (final: prev: {
            cosmo = workspace.mkPyprojectOverlay {
              sourcePreference = "wheel";
            };
          })
        ];
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

          }));
}
