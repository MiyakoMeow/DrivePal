{
  description = "Thesis Cockpit Memo - 车载AI智能体原型系统";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    { nixpkgs, pyproject-nix, ... }:
    let
      project = pyproject-nix.lib.project.loadPyproject {
        projectRoot = ./.;
      };

      pkgs = nixpkgs.legacyPackages.x86_64-linux;
      python = pkgs.python314;
    in
    {
      devShells.x86_64-linux.default = pkgs.mkShell {
        packages = [
          python
          pkgs.uv
        ];

        env = {
          UV_PYTHON = python.interpreter;
          UV_NO_SYNC = "1";
          UV_PYTHON_DOWNLOADS = "never";
        };

        shellHook = ''
          unset PYTHONPATH
          export REPO_ROOT=$(git rev-parse --show-toplevel)
          export LD_LIBRARY_PATH="${
            pkgs.lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib ]
          }:$LD_LIBRARY_PATH"
        '';
      };
    };
}
