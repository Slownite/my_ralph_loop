{
  description = "ralf — AFK issue automation loop for Claude Code";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };

        runtimeDeps = [
          pkgs.gh
          pkgs.claude-code
          pkgs.git
          pkgs.bash
        ] ++ pkgs.lib.optionals pkgs.stdenv.isLinux [ pkgs.bubblewrap ];

        ralf-loop = pkgs.writeShellApplication {
          name = "ralf-loop";
          runtimeInputs = runtimeDeps;
          text = builtins.readFile ./bin/ralf-loop;
        };

        ralf-once = pkgs.writeShellApplication {
          name = "ralf-once";
          runtimeInputs = runtimeDeps;
          text = builtins.readFile ./bin/ralf-once;
        };
      in {
        packages = {
          inherit ralf-loop ralf-once;
          default = pkgs.symlinkJoin {
            name = "ralf";
            paths = [ ralf-loop ralf-once ];
          };
        };

        devShells.default = pkgs.mkShell {
          packages = runtimeDeps ++ [ ralf-loop ralf-once ];
        };
      });
}
