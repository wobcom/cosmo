{
  description = "cosmo - ???";

  inputs.flake-utils.url = "github:numtide/flake-utils";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-23.11";
  inputs.poetry2nix = {
    url = "github:nix-community/poetry2nix";
    inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { self, nixpkgs, flake-utils, poetry2nix }:
    {
      # Nixpkgs overlay providing the application
      overlay = nixpkgs.lib.composeManyExtensions [
        poetry2nix.overlays.default
        (final: prev: {
          # The application
          cosmo = prev.poetry2nix.mkPoetryApplication {
            projectDir = ./.;
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

        devShell = pkgs.mkShell {
          buildInputs = with pkgs; [
            black
            (pkgs.poetry2nix.mkPoetryEnv {
              projectDir = ./.;
              editablePackageSources = {
                cosmo = ./cosmo;
              };
            })
          ];
        };
      }));
}
