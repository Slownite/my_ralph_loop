{
  description = "ralf — AFK issue automation loop";

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
          pkgs.opencode
          pkgs.git
          pkgs.bash
          pkgs.xonsh
        ] ++ pkgs.lib.optionals pkgs.stdenv.isLinux [ pkgs.bubblewrap ];

        ralfAssets = pkgs.runCommand "ralf-assets" { } ''
          mkdir -p $out/share/ralf
          cp -r ${./ralf/prompts} $out/share/ralf/prompts
          cp -r ${./ralf/lib} $out/share/ralf/lib
        '';

        mkXonshApp = name:
          pkgs.runCommand name {
            nativeBuildInputs = [ pkgs.makeWrapper ];
          } ''
            install -Dm755 ${./bin}/${name}.xonsh $out/bin/${name}
            substituteInPlace $out/bin/${name} \
              --replace-fail "#!/usr/bin/env xonsh" "#!${pkgs.xonsh}/bin/xonsh"
            wrapProgram $out/bin/${name} \
              --prefix PATH : ${pkgs.lib.makeBinPath runtimeDeps} \
              --set RALF_ROOT ${ralfAssets}/share/ralf
          '';

        ralf-loop = mkXonshApp "ralf-loop";
        ralf-complete = mkXonshApp "ralf-complete";
      in {
        packages = {
          inherit ralf-loop ralf-complete;
          default = pkgs.symlinkJoin {
            name = "ralf";
            paths = [ ralf-loop ];
          };
        };

        devShells.default = pkgs.mkShell {
          packages = runtimeDeps;
          shellHook = ''
            export RALF_ROOT="$PWD/ralf"
          '';
        };
      });
}
