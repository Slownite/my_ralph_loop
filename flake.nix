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
          pkgs.jq
          pkgs.xonsh
        ] ++ pkgs.lib.optionals pkgs.stdenv.isLinux [ pkgs.bubblewrap ];

        # lib/ may be empty mid-rewrite; only ship it when it actually has files.
        hasLib = builtins.pathExists ./lib && builtins.readDir ./lib != { };

        ralfAssets = pkgs.runCommand "ralf-assets" { } ''
          mkdir -p $out/share/ralf
          cp -r ${./prompts} $out/share/ralf/prompts
          ${pkgs.lib.optionalString hasLib "cp -r ${./lib} $out/share/ralf/lib"}
        '';

        # Package a xonsh script: pin the interpreter to the store xonsh,
        # put runtime tools on PATH, and expose the asset dir as RALF_ROOT.
        mkXonshApp = name:
          pkgs.runCommand name {
            nativeBuildInputs = [ pkgs.makeWrapper ];
          } ''
            install -Dm755 ${./bin}/${name} $out/bin/${name}
            substituteInPlace $out/bin/${name} \
              --replace-fail "#!/usr/bin/env xonsh" "#!${pkgs.xonsh}/bin/xonsh"
            wrapProgram $out/bin/${name} \
              --prefix PATH : ${pkgs.lib.makeBinPath runtimeDeps} \
              --set RALF_ROOT ${ralfAssets}/share/ralf
          '';

        ralf-loop = mkXonshApp "ralf-loop";
        ralf-once = mkXonshApp "ralf-once";
      in {
        packages = {
          inherit ralf-loop ralf-once;
          default = pkgs.symlinkJoin {
            name = "ralf";
            paths = [ ralf-loop ralf-once ];
          };
        };

        devShells.default = pkgs.mkShell {
          packages = runtimeDeps;
          # In-tree assets live at the repo root during development.
          shellHook = ''
            export RALF_ROOT="$PWD"
          '';
        };
      });
}
