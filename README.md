# ConsolePi

<sub>Light mode:</sub><br>
<img width="359" height="276" alt="ConsolePi - DBOARD" src="https://github.com/user-attachments/assets/911fd4b6-fda4-4be1-9d5f-32ab78845392" /><img width="359" height="276" alt="ConsolePI - HEALTH" src="https://github.com/user-attachments/assets/4408876b-0a74-4b4b-a5d3-8fa07a47aa8a" /><br>
<sub>Dark mode:</sub><br>
<img width="347" height="360" alt="Snímek obrazovky 2026-08-01 v 19 35 04" src="https://github.com/user-attachments/assets/0fe9cc1d-aa8b-46a6-94ae-c7070da7ab0f" /><img width="347" height="360" alt="Snímek obrazovky 2026-08-01 v 19 35 23" src="https://github.com/user-attachments/assets/edf5a3cd-bb01-410f-ba45-1c004b10984a" />


ConsolePi turns a Raspberry Pi 3 into a secure, web-managed serial console
server for network equipment. Each attached USB serial adapter is mapped to an
SSH port (for example, `2201` to `2204`) and opens a Cisco-compatible serial
console at 9600 8N1 by default.

The web interface currently ships in Czech. The public documentation is
available in English here and in Czech in [README.cs.md](README.cs.md).

## Features

- SSH administration on port `22` and restricted serial-console sessions on
  ports `2201`–`2204`;
- stable USB adapter identification, port labels and serial settings;
- exclusive per-port locking, serial-session and connection logging;
- local password, SSH public-key, or RADIUS authentication for console ports;
- web setup wizard, network configuration, firewall access-source allowlist,
  optional SNMPv3, CDP/LLDP and health monitoring;
- signed application updates and a first-boot workflow suitable for cloned or
  custom SD-card images.

## Quick installation on Raspberry Pi OS Lite

Download the matching installer first from
[downloads/ConsolePi-1.6.0-install.tar.gz](downloads/ConsolePi-1.6.0-install.tar.gz).
Its [SHA-256 checksum](downloads/ConsolePi-1.6.0-install.tar.gz.sha256) is
published alongside it.

1. Use Raspberry Pi Imager to write **Raspberry Pi OS Lite (64-bit)** to the
   SD card. Configure an administrator named `consolepi`, enable SSH with
   public-key authentication, and use DHCP for the initial network connection.
   The separate generic ConsolePi image must instead follow its key-only guide.
2. Boot the Pi and update the base operating system:

       ssh -i "$HOME/.ssh/consolepi-admin" consolepi@PI_ADDRESS
       sudo apt update
       sudo apt full-upgrade -y
       sudo reboot

3. Copy the release bundle to the `consolepi` home directory:

       scp -i "$HOME/.ssh/consolepi-admin" ConsolePi-1.6.0-install.tar.gz consolepi@PI_ADDRESS:~/

4. Log in again and run the bootstrap installer:

       install_dir="$HOME/consolepi-install"
       mkdir -p "$install_dir"
       tar --no-same-owner -xzf "$HOME/ConsolePi-1.6.0-install.tar.gz" -C "$install_dir"
       cd "$install_dir"
       ./bootstrap-install.sh

5. Open `https://PI_ADDRESS/` and complete the first-boot wizard. It sets the
   web password, device identity, host keys and administrative SSH access.

For a detailed Czech clean-install guide, see
[docs/INSTALACE-RPI3.md](docs/INSTALACE-RPI3.md). For a compressed custom SD
image, see [docs/INSTALACE-IMAGE-RPI-IMAGER.txt](docs/INSTALACE-IMAGE-RPI-IMAGER.txt).

## SSH keys

Create an Ed25519 key pair on the administrator workstation:

    ssh-keygen -t ed25519 -f "$HOME/.ssh/consolepi-admin" -C "consolepi-admin"

Keep `consolepi-admin` private. The `.pub` file is safe to paste into Raspberry
Pi Imager or into the ConsolePi first-boot wizard. Windows PowerShell users
should first run `New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh"`,
then use the equivalent `ssh-keygen` command.

When reusing an IP address after a first-boot reset, remove the old host key
before reconnecting:

    ssh-keygen -R IP_RPI

## Development and release safety

This working tree can contain local build output and confidential material. Do
not publish it directly. Before making a public GitHub repository, run:

    ./tools/build-public-source.sh

The script creates a source archive that excludes local SSH keys, signing
private keys, release artifacts, disk images and macOS metadata. Review the
archive before publishing. The public signing key
`release-signing-private.pem.pub` may be published; the matching private key
must never leave the release administrator's secure workstation.

Read [PUBLIC_RELEASE.md](PUBLIC_RELEASE.md) before publishing. A project
license must be chosen by the copyright holder before the repository is made
public.

## Security reporting

Please do not publish security-sensitive issues, credentials, device
configuration, serial transcripts or private keys. See
[SECURITY.md](SECURITY.md).
