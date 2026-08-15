#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
failed=0

ok()
{
    printf 'OK: %s\n' "$1"
}

bad()
{
    printf 'CHYBA: %s\n' "$1" >&2
    failed=1
}

for file in \
    "$ROOT/install.sh" \
    "$ROOT/usr/local/sbin/consolepi-session" \
    "$ROOT/usr/local/sbin/consolepi-diagnose" \
    "$ROOT/usr/local/sbin/consolepi-login-status" \
    "$ROOT/usr/local/sbin/consolepi-admin-menu" \
    "$ROOT/usr/local/sbin/consolepi-generic-image-firstboot" \
    "$ROOT/usr/local/sbin/consolepi-generic-recovery" \
    "$ROOT/usr/local/sbin/consolepi-prepare-generic-image" \
    "$ROOT/usr/local/sbin/consolepi-validate-generic-image" \
    "$ROOT/usr/local/libexec/consolepi-imager-custom-guard" \
    "$ROOT/usr/local/libexec/consolepi-imager-userconf-guard" \
    "$ROOT/etc/NetworkManager/dispatcher.d/90-consolepi-firewall" \
    "$ROOT/etc/profile.d/consolepi-status.sh" \
    "$ROOT/bootstrap-install.sh" \
    "$ROOT/tools/build-install-bundle.sh" \
    "$ROOT/tests/check.sh"
do
    if sh -n "$file"; then ok "shell syntax $file"; else bad "shell syntax $file"; fi
done

dispatcher="$ROOT/etc/NetworkManager/dispatcher.d/90-consolepi-firewall"
grep -q '\[ "$1" = eth0 \]' "$dispatcher" &&
    grep -q 'up|dhcp4-change|reapply' "$dispatcher" &&
    grep -q 'flock -n 9' "$dispatcher" &&
    grep -q '/usr/local/sbin/consolepi-control access migrate' "$dispatcher" &&
    ! grep -q '0\.0\.0\.0/0' "$dispatcher" &&
    grep -q '90-consolepi-firewall' "$ROOT/install.sh" &&
    ok "NetworkManager DHCP firewall synchronization" ||
    bad "NetworkManager DHCP firewall synchronization missing"

grep -q 'xattr -cr "$STAGING"' "$ROOT/tools/build-install-bundle.sh" &&
    grep -q 'tar --no-xattrs -C "$STAGING"' "$ROOT/tools/build-install-bundle.sh" &&
    ok "macOS extended attributes removed from install bundle" ||
    bad "install bundle does not remove macOS extended attributes"

if command -v zsh >/dev/null 2>&1; then
    for file in \
        "$ROOT/tools/macos-create-image.sh" \
        "$ROOT/tools/macos-write-image.sh"
    do
        if zsh -n "$file"; then ok "zsh syntax $file"; else bad "zsh syntax $file"; fi
    done
else
    printf '%s\n' 'SKIP: zsh není na tomto systému instalován (macOS nástroje)'
fi

python3 -c 'import ast, pathlib; [ast.parse(pathlib.Path(p).read_text()) for p in (
    "'"$ROOT"'/opt/consolepi-web/app.py",
    "'"$ROOT"'/usr/local/sbin/consolepi-control",
    "'"$ROOT"'/usr/local/sbin/consolepi-log-maintain",
    "'"$ROOT"'/usr/local/sbin/consolepi-transcript-writer",
    "'"$ROOT"'/usr/local/sbin/consolepi-update-check",
    "'"$ROOT"'/usr/local/sbin/consolepi-maintenance",
    "'"$ROOT"'/usr/local/sbin/consolepi-reset-web-password"
)]' &&
    ok "Python syntax" ||
    bad "Python syntax"

python3 -c 'import ast, pathlib; [ast.parse(pathlib.Path(p).read_text()) for p in (
    "'"$ROOT"'/usr/local/libexec/consolepi-imager-guard",
    "'"$ROOT"'/usr/local/libexec/consolepi-imager-postvalidate",
    "'"$ROOT"'/usr/local/lib/consolepi_imager_security.py",
    "'"$ROOT"'/usr/local/lib/consolepi_generic_recovery.py"
)]' && ok "strict Imager guard Python syntax" || bad "strict Imager guard Python syntax"

python3 -c 'import ast, pathlib; ast.parse(pathlib.Path(
    "'"$ROOT"'/usr/local/lib/consolepi_firstboot_security.py").read_text())' &&
    ok "first-boot security Python syntax" || bad "first-boot security Python syntax"

python3 "$ROOT/tests/generic_behavior.py" || bad "generic image behavioral security tests"
python3 "$ROOT/tests/network_apply_behavior.py" || bad "delayed network apply behavior"
if [ "${CONSOLEPI_SKIP_ARCHIVE_TEST:-0}" != 1 ]; then
    "$ROOT/tests/check-install-archive.sh" || bad "install archive credential scan"
fi

grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' "$ROOT/VERSION" &&
    grep -q 'consolepi-update-1' "$ROOT/usr/local/sbin/consolepi-release" &&
    grep -q 'archive.extract(member, target)' "$ROOT/usr/local/sbin/consolepi-release" &&
    grep -q 'def inspect' "$ROOT/usr/local/sbin/consolepi-release" &&
    test -x "$ROOT/usr/local/sbin/consolepi-release-runner" &&
    grep -q 'system_release_upload' "$ROOT/opt/consolepi-web/app.py" &&
    grep -q 'Aktualizace ConsolePi' "$ROOT/opt/consolepi-web/templates/system.html" &&
    grep -q 'ssh-keygen' "$ROOT/tools/build-update-package.py" &&
    grep -q 'release-signing-private.pem' "$ROOT/.gitignore" &&
    test -s "$ROOT/etc/consolepi/update-allowed-signers" &&
    grep -q 'brand-version' "$ROOT/opt/consolepi-web/templates/_brand.html" &&
    grep -q 'VERSION_FILE' "$ROOT/opt/consolepi-web/app.py" &&
    ok "versioned signed release infrastructure" ||
    bad "versioned signed release infrastructure missing"

awk -F '|' '
    /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
    NF != 3 || $1 !~ /^[0-9]+$/ || $2 !~ /^[A-Za-z0-9._-]+$/ { exit 1 }
    seen[$1]++ { exit 1 }
    END { if (length(seen) == 0) exit 1 }
' "$ROOT/etc/consolepi/ports.conf" &&
    ok "ports.conf format and unique ports" ||
    bad "ports.conf format or duplicate port"

awk -F '|' '
    /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
    NF != 7 || $1 !~ /^[0-9]+$/ { exit 1 }
    $2 !~ /^(9600|19200|38400|57600|115200)$/ { exit 1 }
    $3 !~ /^(7|8)$/ || $4 !~ /^(none|even|odd)$/ { exit 1 }
    $5 !~ /^(1|2)$/ || $6 !~ /^(none|hard|soft)$/ || $7 !~ /^(yes|no)$/ { exit 1 }
    seen[$1]++ { exit 1 }
    END { if (length(seen) == 0) exit 1 }
' "$ROOT/etc/consolepi/serial.conf" &&
    ok "serial.conf format and allowed values" ||
    bad "serial.conf format or values"

python3 -c 'import json, pathlib
root = pathlib.Path("'"$ROOT"'")
meta = json.loads((root / "etc/consolepi/radius.json").read_text())
secrets = json.loads((root / "etc/consolepi/radius-secrets.json").read_text())
assert meta["primary_port"] == 1812 and meta["secondary_port"] == 1812
assert set(secrets) == {"primary", "secondary"}
' &&
    ok "RADIUS JSON configuration" ||
    bad "RADIUS JSON configuration"

grep -q '^AUTH_MODE=local_key$' "$ROOT/etc/consolepi/auth.conf" &&
    grep -q 'pam_radius_auth.so' "$ROOT/etc/pam.d/consolepi-radius" &&
    grep -q 'pam_sm_authenticate' "$ROOT/src/pam_consolepi_user.c" &&
    grep -q 'RADIUS uživatel' "$ROOT/src/pam_consolepi_user.c" &&
    grep -q 'def radius_server_check' "$ROOT/usr/local/sbin/consolepi-control" &&
    grep -q 'při chybě se konfigurace neuloží' "$ROOT/opt/consolepi-web/templates/authentication.html" &&
    grep -q 'secondary_enabled' "$ROOT/opt/consolepi-web/app.py" &&
    grep -q 'RADIUS komunikace ověřena' "$ROOT/opt/consolepi-web/templates/authentication.html" &&
    ok "RADIUS mode and PAM profile" ||
    bad "RADIUS mode or PAM profile"

grep -q '^Match User console LocalPort 2201$' "$ROOT/etc/ssh/sshd_config.d/40-consolepi.conf" &&
    ok "OpenSSH Match LocalPort" ||
    bad "OpenSSH Match LocalPort missing"

! grep -q '^Match User consolepi$' "$ROOT/etc/ssh/sshd_config.d/40-consolepi.conf" &&
    ! grep -q 'service.d/consolepi-generic-image.conf' "$ROOT/install.sh" &&
    ! grep -q 'network-online.target' "$ROOT/etc/systemd/system/consolepi-generic-image-firstboot.service" &&
    grep -q '39-consolepi-generic-image.conf' "$ROOT/usr/local/sbin/consolepi-prepare-generic-image" &&
    grep -q 'Match User consolepi' "$ROOT/usr/local/sbin/consolepi-prepare-generic-image" &&
    grep -q 'validate_generic_access' "$ROOT/usr/local/sbin/consolepi-generic-image-firstboot" &&
    grep -q 'passwd -l consolepi' "$ROOT/usr/local/sbin/consolepi-prepare-generic-image" &&
    grep -q 'rm -f /etc/ssh/ssh_host_' "$ROOT/usr/local/sbin/consolepi-prepare-generic-image" &&
    grep -q 'pam_radius_auth.conf' "$ROOT/usr/local/sbin/consolepi-prepare-generic-image" &&
    grep -q '/var/lib/snmp/snmpd.conf' "$ROOT/usr/local/sbin/consolepi-prepare-generic-image" &&
    grep -q '/etc/apt/apt.conf.d/90consolepi-proxy' "$ROOT/usr/local/sbin/consolepi-prepare-generic-image" &&
    grep -q '/var/backups/consolepi' "$ROOT/usr/local/sbin/consolepi-prepare-generic-image" &&
    grep -q 'systemd-analyze verify' "$ROOT/usr/local/sbin/consolepi-prepare-generic-image" &&
    grep -q 'validate_generic_access' "$ROOT/usr/local/sbin/consolepi-generic-image-firstboot" &&
    ! grep -q '.consolepi-firstboot-token' "$ROOT/usr/local/sbin/consolepi-generic-image-firstboot" &&
    ! grep -q 'ownership-verify' "$ROOT/usr/local/sbin/consolepi-maintenance" &&
    ! grep -q 'setup_provisioning_session' "$ROOT/opt/consolepi-web/app.py" &&
    grep -q 'access generic-bootstrap' "$ROOT/usr/local/sbin/consolepi-generic-image-firstboot" &&
    grep -q 'ip saddr 0.0.0.0/0 tcp dport { 22, 80, 443 }' "$ROOT/usr/local/sbin/consolepi-control" &&
    grep -q 'firstboot-finalize' "$ROOT/usr/local/sbin/consolepi-maintenance" &&
    grep -q 'name="management_network" required' "$ROOT/opt/consolepi-web/templates/setup.html" &&
    grep -q 'čárkou nebo mezerou' "$ROOT/opt/consolepi-web/templates/setup.html" &&
    grep -q 'parse_management_networks' "$ROOT/usr/local/sbin/consolepi-maintenance" &&
    grep -q 'generic_firstboot and key_mode != "keep"' "$ROOT/opt/consolepi-web/app.py" &&
    grep -q 'value="keep" checked' "$ROOT/opt/consolepi-web/templates/setup.html" &&
    grep -q 'sanitize_boot_partition' "$ROOT/usr/local/sbin/consolepi-prepare-generic-image" &&
    grep -q 'clear_directory("/var/lib/cloud")' "$ROOT/usr/local/sbin/consolepi-prepare-generic-image" &&
    grep -q 'imager-systemd-compat' "$ROOT/usr/local/sbin/consolepi-prepare-generic-image" &&
    grep -q 'generic_pending' "$ROOT/usr/local/lib/consolepi_imager_security.py" &&
    grep -q 'validate_userconf_request' "$ROOT/usr/local/libexec/consolepi-imager-guard" &&
    grep -q 'consolepi-imager-postvalidate' "$ROOT/usr/local/sbin/consolepi-generic-image-firstboot" &&
    grep -q 'consolepi-generic-recovery.service' "$ROOT/usr/local/sbin/consolepi-prepare-generic-image" &&
    ! grep -q 'systemctl enable consolepi-generic-recovery' "$ROOT/install.sh" &&
    grep -q 'generic-imager-customization-failed' "$ROOT/usr/local/sbin/consolepi-generic-image-firstboot" &&
    ! grep -Eq 'consolepi-imager-(firstrun|import)' "$ROOT/install.sh" &&
    grep -q 'NEZAPÍNEJTE.*Set username and password' "$ROOT/docs/INSTALACE-IMAGE-RPI-IMAGER.txt" &&
    ! grep -q 'Use password authentication' "$ROOT/docs/INSTALACE-IMAGE-RPI-IMAGER.txt" &&
    ok "generic image key-only first boot" ||
    bad "generic image first-boot safeguards missing"

grep -q 'elements = { MANAGEMENT_CIDR }' "$ROOT/etc/nftables.conf" &&
    ok "nftables management placeholder" ||
    bad "nftables management placeholder missing"

dhcp_silent_drop='ip saddr 0.0.0.0 ip daddr 255.255.255.255 udp sport 68 udp dport 67 counter drop'
for firewall_source in "$ROOT/etc/nftables.conf" "$ROOT/usr/local/sbin/consolepi-control"; do
    dhcp_line=$(grep -nF "$dhcp_silent_drop" "$firewall_source" | head -n 1 | cut -d: -f1)
    log_line=$(grep -nF 'log prefix "nft-input-drop: "' "$firewall_source" | head -n 1 | cut -d: -f1)
    if [ -n "$dhcp_line" ] && [ -n "$log_line" ] && [ "$dhcp_line" -lt "$log_line" ]; then
        ok "silent DHCP drop precedes nft-input-drop in ${firewall_source#"$ROOT"/}"
    else
        bad "silent DHCP drop ordering invalid in ${firewall_source#"$ROOT"/}"
    fi
done

grep -q 'def access_add' "$ROOT/usr/local/sbin/consolepi-control" &&
    grep -q 'access migrate' "$ROOT/install.sh" &&
    grep -q 'Povolené zdroje přístupu' "$ROOT/opt/consolepi-web/templates/index.html" &&
    grep -q '0.0.0.0/0' "$ROOT/opt/consolepi-web/templates/help.html" &&
    grep -q 'access-sources.css' "$ROOT/opt/consolepi-web/templates/base.html" &&
    test -s "$ROOT/etc/consolepi/access-sources.json" &&
    ok "firewall allowlist sources" ||
    bad "firewall allowlist sources missing"

grep -Fq "find /lib /usr/lib -path '*/security/pam_consolepi_user.so'" "$ROOT/install.sh" &&
    ok "merged-/usr PAM module detection" ||
    bad "merged-/usr PAM module detection missing"

grep -q 'def factory_reset' "$ROOT/usr/local/sbin/consolepi-control" &&
    grep -q 'factory reset' "$ROOT/usr/local/sbin/consolepi-admin-menu" &&
    grep -q 'system/factory-reset' "$ROOT/opt/consolepi-web/app.py" &&
    ok "factory reset entry points" ||
    bad "factory reset entry points missing"

grep -q -- '--log-io' "$ROOT/usr/local/sbin/consolepi-session" &&
    grep -q 'TRANSCRIPT_MIN_FREE_MB' "$ROOT/etc/consolepi/consolepi.conf" &&
    grep -q 'consolepi-log-maintain --monitor' "$ROOT/etc/systemd/system/consolepi-port-monitor.service" &&
    grep -q 'except PermissionError' "$ROOT/usr/local/sbin/consolepi-log-maintain" &&
    grep -q 'd /var/log/consolepi 0750 root console' "$ROOT/etc/tmpfiles.d/consolepi.conf" &&
    ok "bounded bidirectional console logging" ||
    bad "console logging safeguards missing"

grep -q 'def logs_read' "$ROOT/usr/local/sbin/consolepi-control" &&
    grep -q 'system/logs/view' "$ROOT/opt/consolepi-web/app.py" &&
    grep -q 'data-theme-toggle' "$ROOT/opt/consolepi-web/templates/_navigation.html" &&
    ok "log viewer and theme switch" ||
    bad "log viewer or theme switch missing"

! grep -Rq 'include "_attribution.html"' "$ROOT/opt/consolepi-web/templates" &&
    ! grep -q 'project-attribution' "$ROOT/opt/consolepi-web/static/consolepi.css" &&
    ! grep -Rqi 'ChatGPT\|OpenAI Codex' "$ROOT/README.md" "$ROOT/README.cs.md" "$ROOT/docs" &&
    grep -q 'rm -f /opt/consolepi-web/templates/_attribution.html' "$ROOT/install.sh" &&
    ok "attribution footer absent" ||
    bad "attribution footer still present"

grep -q 'configure_access_sources' "$ROOT/usr/local/sbin/consolepi-admin-menu" &&
    grep -q 'consolepi-control access add' "$ROOT/usr/local/sbin/consolepi-admin-menu" &&
    grep -q 'consolepi-control access delete' "$ROOT/usr/local/sbin/consolepi-admin-menu" &&
    grep -q 'Povolene management site (firewall)' "$ROOT/usr/local/sbin/consolepi-admin-menu" &&
    ok "terminal firewall allowlist management" ||
    bad "terminal firewall allowlist management missing"

grep -q 'TRANSCRIPT_MODE' "$ROOT/etc/consolepi/consolepi.conf" &&
    grep -q 'CITLIVY OBSAH ODSTRANEN' "$ROOT/usr/local/sbin/consolepi-transcript-writer" &&
    grep -q 'Logování na ConsolePi a ochrana citlivých údajů' "$ROOT/opt/consolepi-web/templates/help.html" &&
    ok "logging privacy modes and help" ||
    bad "logging privacy modes or help missing"

grep -q "url_for('admin_dashboard')" "$ROOT/opt/consolepi-web/templates/serial.html" &&
    grep -q 'Zpět do přehledu konzolí' "$ROOT/opt/consolepi-web/templates/serial.html" &&
    ok "serial detail back link" ||
    bad "serial detail back link missing"

grep -q 'Autentizace konzolí' "$ROOT/opt/consolepi-web/templates/help.html" &&
    grep -q 'Lokální heslo pro účet' "$ROOT/opt/consolepi-web/templates/help.html" &&
    grep -q 'SSH klíč pro účet' "$ROOT/opt/consolepi-web/templates/help.html" &&
    grep -q 'RADIUS – osobní uživatel a heslo' "$ROOT/opt/consolepi-web/templates/help.html" &&
    grep -q 'auth-choice-list' "$ROOT/opt/consolepi-web/templates/authentication.html" &&
    grep -q 'auth-local-password' "$ROOT/opt/consolepi-web/templates/help.html" &&
    grep -q 'help/securecrt-radius.png' "$ROOT/opt/consolepi-web/templates/help.html" &&
    grep -q 'help/securecrt-password.png' "$ROOT/opt/consolepi-web/templates/help.html" &&
    grep -q 'help/securecrt-publickey.png' "$ROOT/opt/consolepi-web/templates/help.html" &&
    grep -q 'help/securecrt-publickey-properties.png' "$ROOT/opt/consolepi-web/templates/help.html" &&
    test -s "$ROOT/opt/consolepi-web/static/help/securecrt-radius.png" &&
    test -s "$ROOT/opt/consolepi-web/static/help/securecrt-password.png" &&
    test -s "$ROOT/opt/consolepi-web/static/help/securecrt-publickey.png" &&
    test -s "$ROOT/opt/consolepi-web/static/help/securecrt-publickey-properties.png" &&
    grep -q 'Start log upon connect' "$ROOT/opt/consolepi-web/templates/help.html" &&
    ok "authentication and SecureCRT logging help" ||
    bad "authentication or SecureCRT logging help missing"

grep -q 'OnUnitActiveSec=1d' "$ROOT/etc/systemd/system/consolepi-update-check.timer" &&
    grep -q 'updates_action' "$ROOT/usr/local/sbin/consolepi-control" &&
    grep -q 'Aktualizace operačního systému' "$ROOT/opt/consolepi-web/templates/system.html" &&
    ok "automatic update check and controlled upgrade" ||
    bad "system update controls missing"

grep -q 'def api_updates' "$ROOT/opt/consolepi-web/app.py" &&
    grep -q 'refreshUpdates' "$ROOT/opt/consolepi-web/static/system.js" &&
    grep -q 'update-spinner' "$ROOT/opt/consolepi-web/templates/system.html" &&
    ok "live update progress refresh" ||
    bad "live update progress refresh missing"

grep -q 'def proxy_configure' "$ROOT/usr/local/sbin/consolepi-control" &&
    grep -q 'network/proxy' "$ROOT/opt/consolepi-web/app.py" &&
    grep -q 'HTTP/HTTPS proxy' "$ROOT/opt/consolepi-web/templates/index.html" &&
    grep -q 'Acquire::https::Proxy' "$ROOT/usr/local/sbin/consolepi-control" &&
    ok "secure APT proxy configuration" ||
    bad "APT proxy configuration missing"

grep -q 'def discovery_configure' "$ROOT/usr/local/sbin/consolepi-control" &&
    grep -q 'network/discovery' "$ROOT/opt/consolepi-web/app.py" &&
    grep -q 'CDP / LLDP detekce' "$ROOT/opt/consolepi-web/templates/index.html" &&
    grep -q 'lldpd' "$ROOT/install.sh" &&
    ok "CDP and LLDP neighbor discovery" ||
    bad "CDP or LLDP neighbor discovery missing"

grep -q 'AESGCM' "$ROOT/usr/local/sbin/consolepi-maintenance" &&
    grep -q 'diagnostic_create' "$ROOT/usr/local/sbin/consolepi-maintenance" &&
    grep -q 'system/clone-rekey' "$ROOT/opt/consolepi-web/app.py" &&
    grep -q 'Bezpečnostní kontrola' "$ROOT/opt/consolepi-web/templates/system.html" &&
    ok "maintenance, backup, audit, TLS, NTP and clone controls" ||
    bad "maintenance controls missing"

grep -q 'def label_set' "$ROOT/usr/local/sbin/consolepi-control" &&
    grep -q 'serial_label' "$ROOT/opt/consolepi-web/app.py" &&
    grep -q 'label if connected and label' "$ROOT/opt/consolepi-web/app.py" &&
    grep -q 'data-role="console-name"' "$ROOT/opt/consolepi-web/templates/index.html" &&
    grep -q 'api_public_status' "$ROOT/opt/consolepi-web/app.py" &&
    grep -q 'public-status.js' "$ROOT/opt/consolepi-web/templates/public.html" &&
    test -s "$ROOT/opt/consolepi-web/static/public-status.js" &&
    ok "live conditional port labels on both dashboards" ||
    bad "live port labels missing"

grep -q 'def ports_discover' "$ROOT/usr/local/sbin/consolepi-control" &&
    grep -q 'def ports_assign' "$ROOT/usr/local/sbin/consolepi-control" &&
    grep -q 'os.chown(lock_path, console_user.pw_uid, console_user.pw_gid)' "$ROOT/usr/local/sbin/consolepi-control" &&
    grep -q 'def unassigned_usb_cables' "$ROOT/opt/consolepi-web/app.py" &&
    grep -q 'port_assign' "$ROOT/opt/consolepi-web/app.py" &&
    grep -q 'Nalezené nepřiřazené kabely' "$ROOT/opt/consolepi-web/templates/index.html" &&
    grep -q 'renderUnassignedUsb' "$ROOT/opt/consolepi-web/static/consolepi.js" &&
    ok "post-reset USB cable assignment" ||
    bad "post-reset USB cable assignment missing"

grep -Fq '"$TRANSCRIPT_MODE" != "events" ] &&' "$ROOT/usr/local/sbin/consolepi-session" &&
    ok "console transcript condition syntax" ||
    bad "console transcript condition syntax missing"

grep -q 'CONSOLE_TITLE=' "$ROOT/usr/local/sbin/consolepi-session" &&
    grep -q 'console_title()' "$ROOT/usr/local/sbin/consolepi-login-status" &&
    grep -q 'LABELS_CONFIG=/etc/consolepi/labels.json' "$ROOT/usr/local/sbin/consolepi-login-status" &&
    ok "console labels in SSH terminal output" ||
    bad "console labels missing from SSH terminal output"

grep -q 'selectedPorts.get(cable.stable_id)' "$ROOT/opt/consolepi-web/static/consolepi.js" &&
    grep -q 'const selectedPorts = new Map' "$ROOT/opt/consolepi-web/static/consolepi.js" &&
    ok "unassigned USB port selection persistence" ||
    bad "unassigned USB port selection persistence missing"

grep -q 'class="system-subnav"' "$ROOT/opt/consolepi-web/templates/system.html" &&
    grep -q 'system_section=section' "$ROOT/opt/consolepi-web/app.py" &&
    grep -q 'selectSystemSection' "$ROOT/opt/consolepi-web/static/system.js" &&
    grep -q 'section="maintenance"' "$ROOT/opt/consolepi-web/app.py" &&
    ok "system dashboard subnavigation" ||
    bad "system dashboard subnavigation missing"

grep -q 'consolepi-reset-web-password' "$ROOT/usr/local/sbin/consolepi-admin-menu" &&
    grep -q 'generate_password_hash' "$ROOT/usr/local/sbin/consolepi-reset-web-password" &&
    grep -q 'Zapomenuté heslo webu' "$ROOT/opt/consolepi-web/templates/help.html" &&
    ok "interactive web password recovery" ||
    bad "web password recovery missing"

grep -q 'def firstboot_configure' "$ROOT/usr/local/sbin/consolepi-maintenance" &&
    grep -q 'firstboot_admin_key_install' "$ROOT/usr/local/sbin/consolepi-maintenance" &&
    grep -q 'firstboot.json' "$ROOT/usr/local/sbin/consolepi-control" &&
grep -q 'firstboot_gate' "$ROOT/opt/consolepi-web/app.py" &&
    grep -q 'setup_admin_key_generate' "$ROOT/opt/consolepi-web/app.py" &&
    grep -q 'Administrativní SSH přístup' "$ROOT/opt/consolepi-web/templates/setup.html" &&
    grep -q 'Chybí PAM modul ConsolePi; provádím jednorázovou opravu' "$ROOT/install.sh" &&
    grep -q 'První spuštění' "$ROOT/opt/consolepi-web/templates/setup.html" &&
    grep -q -- '--timeout 150' "$ROOT/etc/systemd/system/consolepi-web.service" &&
    grep -q 'proxy_read_timeout 150s' "$ROOT/etc/nginx/sites-available/consolepi" &&
    grep -q 'growpart' "$ROOT/usr/local/sbin/consolepi-maintenance" &&
    ok "first-boot wizard and safe SD expansion" ||
    bad "first-boot wizard or SD expansion missing"

grep -q -- '--firstboot' "$ROOT/install.sh" &&
    grep -q 'FIRSTBOOT_PENDING' "$ROOT/install.sh" &&
    grep -q '2201|KONZOLE-1|/dev/consolepi/unassigned-1' "$ROOT/etc/consolepi/ports.conf" &&
    grep -q 'Režim čisté instalace' "$ROOT/install.sh" &&
    grep -q 'authorized_keys' "$ROOT/bootstrap-install.sh" &&
    grep -q 'management síť' "$ROOT/bootstrap-install.sh" &&
    grep -q 'release-signing-private.pem' "$ROOT/tools/build-install-bundle.sh" &&
    grep -q -- "--exclude='./.DS_Store'" "$ROOT/tools/build-install-bundle.sh" &&
    grep -q "ConsolePi-$(tr -d '[:space:]' < "$ROOT/VERSION")-install.tar.gz" "$ROOT/README.md" &&
    grep -q 'New-Item -ItemType Directory' "$ROOT/README.md" &&
    grep -q 'scp -i' "$ROOT/README.md" &&
    grep -q 'ssh-keygen -R IP_RPI' "$ROOT/README.md" &&
    grep -q 'ssh-keygen -R \$WEB_IP' "$ROOT/bootstrap-install.sh" &&
    grep -q 'data-no-page-loader' "$ROOT/opt/consolepi-web/templates/keys.html" &&
    grep -q 'data-no-page-loader' "$ROOT/opt/consolepi-web/templates/_keys_manager.html" &&
    grep -q '<style>' "$ROOT/opt/consolepi-web/templates/setup_complete.html" &&
    grep -q 'error_page 502 503 504' "$ROOT/etc/nginx/sites-available/consolepi" &&
    test -s "$ROOT/opt/consolepi-web/static/update-restarting.html" &&
    ! grep -Fq '```sh' "$ROOT/README.md" &&
    test -s "$ROOT/docs/INSTALACE-RPI3.md" &&
    ok "clean Raspberry Pi OS installation bundle" ||
    bad "clean Raspberry Pi OS installation bundle missing"

if command -v nft >/dev/null 2>&1; then
    tmpfile=$(mktemp)
    trap 'rm -f "$tmpfile"' EXIT HUP INT TERM
    sed 's#MANAGEMENT_CIDR#192.168.1.0/24#g' "$ROOT/etc/nftables.conf" >"$tmpfile"
    if nft -c -f "$tmpfile"; then ok "nftables syntax"; else bad "nftables syntax"; fi
else
    printf '%s\n' 'SKIP: nft není na tomto systému instalován'
fi

if [ "$failed" -ne 0 ]; then
    exit 1
fi
