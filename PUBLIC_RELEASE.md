# Public release checklist

This repository is intended to become an open source ConsolePi distribution.
Complete every item below before making a GitHub repository public.

## 1. Select a license

The copyright holder must select a license. For a permissive community project,
MIT is a simple choice. GPL-3.0-or-later is more appropriate if every modified
redistribution must remain open source. Do not publish until a final `LICENSE`
file has been added.

## 2. Create a clean public source archive

Run from the project root:

    ./tools/build-public-source.sh

The generated archive intentionally excludes:

- `release-signing-private.pem`;
- local `authorized_keys`;
- previously built update packages, installer archives and disk images;
- macOS metadata and release-map files.

Inspect the archive before uploading:

    tar -tzf dist-public/ConsolePi-*-source.tar.gz

Never commit private keys, device images made from a configured appliance,
RADIUS/SNMP passwords, access logs or serial transcripts.

## 3. Create the GitHub repository

Create an empty repository under the GitHub account **jiriflos-eng**:

- name: `consolepi`;
- visibility: **Private** during first review;
- do not initialize it with a README, `.gitignore` or license.

Once the repository name exists, ConsolePi can be uploaded through the connected
GitHub integration. Make it public only after this checklist, including the
license, is complete.

## 4. Release artifacts

Publish source and installer archives as GitHub Release assets. A compressed
`.img.xz` is optional and should be built from a factory-reset image. Publish
its SHA-256 file alongside it. Do not publish an image that contains a known
host key, web password, device identity or administrator public key.

## 5. Third-party notices

ConsolePi installs and configures software from Raspberry Pi OS/Debian and
other upstream projects. Keep their license notices and package licensing
available. Do not imply endorsement by Raspberry Pi, Debian, Cisco or other
vendors.

