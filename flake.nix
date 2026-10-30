{
  description = "KDE Plasma 6 + Kirigami + PySide6 Development Environment";

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

        # Python 3 with PySide6 (official Qt6 Python bindings).
        # Includes shiboken6 automatically. This is the KDE-recommended
        # binding over PyQt6.
        pythonEnv = pkgs.python3.withPackages (ps: with ps; [
          pyside6
        ]);

      in
      {
        # Optional: nix fmt
        formatter = pkgs.nixpkgs-fmt;

        devShells.default = pkgs.mkShell {
          name = "kirigami-python-dev";

          packages = [
            # -- Core Python + Qt Bindings -------------------------------
            pythonEnv

            # -- KDE Frameworks 6 (KF6) ----------------------------------
            pkgs.kdePackages.kirigami            # Adaptive UI framework
            pkgs.kdePackages.kirigami-addons     # Extra pre-built components
            pkgs.kdePackages.qqc2-desktop-style  # Plasma 6 native QML style
            pkgs.kdePackages.kconfig             # Settings/config framework
            pkgs.kdePackages.kio                 # File I/O (network shares, trash, etc.)
            pkgs.kdePackages.baloo               # File indexer/search
            pkgs.kdePackages.kfilemetadata       # EXIF, ID3, video metadata
            pkgs.kdePackages.knewstuff           # Downloadable content support
            pkgs.kdePackages.qtwayland           # Wayland platform plugin

            # -- Qt6 Libraries -------------------------------------------
            pkgs.qt6.qtbase                      # Core Qt (Core, Gui, Widgets, Network)
            pkgs.qt6.qtdeclarative               # QML engine + QtQuick
            pkgs.qt6.qtmultimedia                # Video/audio playback
            pkgs.qt6.qtsvg                       # SVG rendering
            pkgs.qt6.qtimageformats              # WebP, TIFF, etc.
            pkgs.qt6.qt5compat                   # Qt5 compatibility shims

            # -- Build Tools ---------------------------------------------
            pkgs.cmake
            pkgs.ninja
            pkgs.pkg-config
            pkgs.git

            # -- Packaging / Distribution --------------------------------
            pkgs.flatpak-builder                 # For Flatpak builds
            pkgs.appstream                       # AppStream metadata tools

            # -- Optional IDE --------------------------------------------
            # pkgs.qtcreator                     # Uncomment for Qt Creator
          ];

          # -- Runtime Environment ---------------------------------------
          shellHook = ''
            echo "============================================"
            echo "  KDE Plasma 6 + Kirigami + PySide6 Shell  "
            echo "============================================"
            echo ""
            python --version
            python -c "import PySide6; print('PySide6:', PySide6.__version__)" 2>/dev/null || echo "PySide6: (available)"
            echo ""
            echo "Quick start:"
            echo "  mkdir -p src/qml && touch src/__init__.py src/main.py src/qml/Main.qml"
            echo ""

            # Qt needs these paths to find plugins and QML modules outside FHS.
            # Without them, your app will look generic or fail to find Kirigami.
            #
            # Override (not append) QT_PLUGIN_PATH to exclude system desktop
            # environments (Union, KDE, etc.) whose platform plugins are built
            # against a different Qt version and will crash Nix Qt.
            export QT_PLUGIN_PATH="${pkgs.qt6.qtbase}/lib/qt-6/plugins:${pkgs.kdePackages.qqc2-desktop-style}/lib/qt-6/plugins"
            export QML2_IMPORT_PATH="${pkgs.kdePackages.kirigami}/lib/qt-6/qml:${pkgs.kdePackages.kirigami-addons}/lib/qt-6/qml:${pkgs.kdePackages.qqc2-desktop-style}/lib/qt-6/qml"
            export QT_QUICK_CONTROLS_STYLE="org.kde.desktop"
            export XDG_DATA_DIRS="${pkgs.kdePackages.kirigami}/share:${pkgs.kdePackages.qqc2-desktop-style}/share''${XDG_DATA_DIRS:+:$XDG_DATA_DIRS}"

            # Fallback library path for any binary extensions
            export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
          '';
        };
      }
    );
}
