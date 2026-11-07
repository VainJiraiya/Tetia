## Tetia 0.3.1

A fix for switching to a private profile. After unlocking a Plasma Vault profile, Tetia quits and starts again inside the profile. In installs that start Tetia through a wrapper (the Nix package) the new copy could not start, so the window closed and nothing reopened. It now restarts through the same launcher it was started with. The RPM and `install.sh` installs were not affected.

Everything else is as in [0.3.0](https://github.com/VainJiraiya/Tetia/releases/tag/v0.3.0).

### Install

- **Any distribution:** `git clone --branch v0.3.1 https://github.com/VainJiraiya/Tetia.git && cd Tetia && ./install.sh` (remove with `./uninstall.sh`).
- **Fedora / Nobara:** download the `.rpm` below for your Fedora version and run `sudo dnf install ./tetia-*.rpm` (remove with `sudo dnf remove tetia`).
- **Nix:** `nix run github:VainJiraiya/Tetia/v0.3.1`.
