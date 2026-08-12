#!/bin/sh
set -eu

PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
MANAGEMENT_CIDR=192.168.1.0/24
TRANSCRIPTS=no
INSTALL_FIREWALL=yes
CHECK_ONLY=no
UPDATE_MODE=no
FIRSTBOOT_PENDING=no

usage()
{
    cat <<'EOF'
Použití: sudo ./install.sh [volby]
  --management-cidr CIDR  IPv4 management síť (výchozí 192.168.1.0/24)
  --enable-transcripts    ukládat úplné transcripty sériových relací
  --no-firewall           neměnit nftables
  --update                instalovat podepsanou aktualizaci bez změny provozní konfigurace
  --firstboot             po instalaci otevřít průvodce nového zařízení
  --check-only            pouze kontrolovat zdrojový balík
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --management-cidr)
            [ "$#" -ge 2 ] || { usage >&2; exit 2; }
            MANAGEMENT_CIDR=$2
            shift 2
            ;;
        --enable-transcripts)
            TRANSCRIPTS=yes
            shift
            ;;
        --no-firewall)
            INSTALL_FIREWALL=no
            shift
            ;;
        --update)
            UPDATE_MODE=yes
            INSTALL_FIREWALL=no
            shift
            ;;
        --firstboot)
            FIRSTBOOT_PENDING=yes
            shift
            ;;
        --check-only)
            CHECK_ONLY=yes
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'Neznámá volba: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

case "$MANAGEMENT_CIDR" in
    *[!0-9./]*|*.*.*.*.*|''|*/*/*)
        printf 'Neplatný formát IPv4 CIDR: %s\n' "$MANAGEMENT_CIDR" >&2
        exit 2
        ;;
esac

"$ROOT/tests/check.sh"

if grep -q 'REPLACE_' "$ROOT/etc/consolepi/ports.conf"; then
    printf '%s\n' 'Nahraďte všechny REPLACE_* v etc/consolepi/ports.conf.' >&2
    [ "$CHECK_ONLY" = yes ] || exit 1
fi

if [ "$CHECK_ONLY" = yes ]; then
    printf '%s\n' 'Kontrola zdrojového balíku dokončena.'
    exit 0
fi

[ "$(id -u)" -eq 0 ] || {
    printf '%s\n' 'Instalaci spusťte jako root (sudo).' >&2
    exit 1
}

[ "$UPDATE_MODE" = yes ] || [ -f "$ROOT/authorized_keys" ] || {
    printf '%s\n' 'Chybí authorized_keys. Vytvořte jej podle authorized_keys.example.' >&2
    exit 1
}
if [ "$UPDATE_MODE" != yes ]; then
grep -Eq '^[[:space:]]*(ssh-(ed25519|rsa)|ecdsa-sha2-nistp(256|384|521)|sk-(ssh-ed25519|ecdsa-sha2-nistp256)@openssh\.com)[[:space:]]+' "$ROOT/authorized_keys" || {
    printf '%s\n' 'authorized_keys neobsahuje rozpoznaný veřejný SSH klíč.' >&2
    exit 1
}
fi

export DEBIAN_FRONTEND=noninteractive
if [ "$UPDATE_MODE" != yes ]; then
    apt-get update
    apt-get install -y openssh-server picocom util-linux nftables logrotate udev \
        python3-flask python3-cryptography python3-bcrypt gunicorn nginx openssl \
        libpam-radius-auth gcc libpam0g-dev chrony cloud-guest-utils lldpd snmpd
fi

BACKUP_DIR=/var/backups/consolepi/$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$BACKUP_DIR"

backup_if_exists()
{
    target=$1
    if [ -e "$target" ]; then
        relative=${target#/}
        mkdir -p "$BACKUP_DIR/$(dirname "$relative")"
        cp -a "$target" "$BACKUP_DIR/$relative"
    fi
}

install -d -m 0755 /etc/consolepi /etc/ssh/sshd_config.d /etc/profile.d /usr/local/sbin /usr/local/lib /usr/local/libexec /usr/share/consolepi
install -d -m 0755 /etc/udev/rules.d /etc/tmpfiles.d /etc/logrotate.d
install -d -m 0755 /etc/systemd/system /etc/nginx/sites-available /etc/sudoers.d
install -d -m 0755 /etc/consolepi/tls

for target in \
    /etc/consolepi/ports.conf \
    /etc/consolepi/serial.conf \
    /etc/consolepi/consolepi.conf \
    /etc/consolepi/auth.conf \
    /etc/consolepi/radius.json \
    /etc/consolepi/radius-secrets.json \
    /etc/consolepi/identity.json \
    /etc/consolepi/firstboot.json \
    /etc/consolepi/labels.json \
    /etc/consolepi/access-sources.json \
    /etc/consolepi/snmpv3.json \
    /etc/consolepi/snmpv3-secrets.json \
    /etc/consolepi/pam_radius_auth.conf \
    /etc/pam.d/consolepi-radius \
    /etc/ssh/sshd_config.d/40-consolepi.conf \
    /usr/local/sbin/consolepi-session \
    /usr/local/sbin/consolepi-diagnose \
    /usr/local/sbin/consolepi-control \
    /usr/local/sbin/consolepi-maintenance \
    /usr/local/sbin/consolepi-login-status \
    /usr/local/sbin/consolepi-log-maintain \
    /usr/local/sbin/consolepi-transcript-writer \
    /usr/local/sbin/consolepi-update-check \
    /usr/local/sbin/consolepi-generic-image-firstboot \
    /usr/local/sbin/consolepi-generic-recovery \
    /usr/local/sbin/consolepi-prepare-generic-image \
    /usr/local/lib/consolepi_firstboot_security.py \
    /usr/local/lib/consolepi_imager_security.py \
    /usr/local/lib/consolepi_generic_recovery.py \
    /usr/local/libexec/consolepi-imager-guard \
    /usr/local/libexec/consolepi-imager-custom-guard \
    /usr/local/libexec/consolepi-imager-userconf-guard \
    /usr/local/libexec/consolepi-imager-postvalidate \
    /usr/local/sbin/consolepi-snmp-pass-persist \
    /usr/local/sbin/consolepi-release \
    /etc/profile.d/consolepi-status.sh \
    /etc/tmpfiles.d/consolepi.conf \
    /etc/logrotate.d/consolepi \
    /etc/systemd/system/consolepi-web.service \
    /etc/systemd/system/consolepi-port-monitor.service \
    /etc/systemd/system/consolepi-update-check.service \
    /etc/systemd/system/consolepi-update-check.timer \
    /etc/systemd/system/consolepi-system-upgrade.service \
    /etc/systemd/system/consolepi-generic-image-firstboot.service \
    /etc/systemd/system/consolepi-generic-recovery.service \
    /etc/nginx/sites-available/consolepi \
    /etc/sudoers.d/consolepi-web \
    /etc/pam.d/sshd
do
    backup_if_exists "$target"
done

if [ ! -e /etc/consolepi/ports.conf ]; then
    install -m 0644 "$ROOT/etc/consolepi/ports.conf" /etc/consolepi/ports.conf
fi
if [ ! -e /etc/consolepi/serial.conf ]; then
    install -m 0644 "$ROOT/etc/consolepi/serial.conf" /etc/consolepi/serial.conf
fi
# Režim čisté instalace nesmí převzít žádné přiřazení z případného zdroje
# balíčku. Fyzicky připojené adaptéry se po prvním spuštění zobrazí jako
# nepřiřazené a správce je vědomě spojí s portem 2201–2204.
if [ "$FIRSTBOOT_PENDING" = yes ]; then
    cat >/etc/consolepi/ports.conf <<'EOF'
# SSH_PORT|DEVICE_NAME|SERIAL_DEVICE
2201|KONZOLE-1|/dev/consolepi/unassigned-1
2202|KONZOLE-2|/dev/consolepi/unassigned-2
2203|KONZOLE-3|/dev/consolepi/unassigned-3
2204|KONZOLE-4|/dev/consolepi/unassigned-4
EOF
    cat >/etc/consolepi/serial.conf <<'EOF'
# SSH_PORT|BAUD|DATABITS|PARITY|STOPBITS|FLOW|LOCAL_ECHO
2201|9600|8|none|1|none|no
2202|9600|8|none|1|none|no
2203|9600|8|none|1|none|no
2204|9600|8|none|1|none|no
EOF
    chmod 0644 /etc/consolepi/ports.conf /etc/consolepi/serial.conf
fi
if [ ! -e /etc/consolepi/auth.conf ]; then
    install -m 0644 "$ROOT/etc/consolepi/auth.conf" /etc/consolepi/auth.conf
fi
if [ ! -e /etc/consolepi/radius.json ]; then
    install -m 0644 "$ROOT/etc/consolepi/radius.json" /etc/consolepi/radius.json
fi
if [ ! -e /etc/consolepi/radius-secrets.json ]; then
    install -m 0600 "$ROOT/etc/consolepi/radius-secrets.json" /etc/consolepi/radius-secrets.json
fi
if [ ! -e /etc/consolepi/proxy.json ]; then
    install -m 0600 "$ROOT/etc/consolepi/proxy.json" /etc/consolepi/proxy.json
fi
if [ ! -e /etc/consolepi/identity.json ]; then
    install -m 0644 "$ROOT/etc/consolepi/identity.json" /etc/consolepi/identity.json
fi
if [ ! -e /etc/consolepi/labels.json ]; then
    install -m 0644 "$ROOT/etc/consolepi/labels.json" /etc/consolepi/labels.json
fi
if [ ! -e /etc/consolepi/access-sources.json ]; then
    install -m 0644 "$ROOT/etc/consolepi/access-sources.json" /etc/consolepi/access-sources.json
fi
if [ ! -e /etc/consolepi/discovery.json ]; then
    printf '%s\n' '{"lldp": false, "cdp": false}' >/etc/consolepi/discovery.json
    chmod 0644 /etc/consolepi/discovery.json
    systemctl disable --now lldpd >/dev/null 2>&1 || true
fi
if [ ! -e /etc/consolepi/snmpv3.json ]; then
    install -m 0600 "$ROOT/etc/consolepi/snmpv3.json" /etc/consolepi/snmpv3.json
    install -m 0600 "$ROOT/etc/consolepi/snmpv3-secrets.json" /etc/consolepi/snmpv3-secrets.json
    systemctl disable --now snmpd >/dev/null 2>&1 || true
fi
if [ ! -e /etc/consolepi/pam_radius_auth.conf ]; then
    install -m 0600 "$ROOT/etc/consolepi/pam_radius_auth.conf" /etc/consolepi/pam_radius_auth.conf
fi
install -m 0644 "$ROOT/etc/pam.d/consolepi-radius" /etc/pam.d/consolepi-radius
sed "s/^TRANSCRIPT_ENABLED=.*/TRANSCRIPT_ENABLED=$TRANSCRIPTS/" \
    "$ROOT/etc/consolepi/consolepi.conf" >/etc/consolepi/consolepi.conf
chmod 0644 /etc/consolepi/consolepi.conf
install -m 0644 "$ROOT/etc/ssh/sshd_config.d/40-consolepi.conf" /etc/ssh/sshd_config.d/40-consolepi.conf
install -m 0755 "$ROOT/usr/local/sbin/consolepi-session" /usr/local/sbin/consolepi-session
install -m 0755 "$ROOT/usr/local/sbin/consolepi-diagnose" /usr/local/sbin/consolepi-diagnose
install -m 0755 "$ROOT/usr/local/sbin/consolepi-control" /usr/local/sbin/consolepi-control
install -m 0755 "$ROOT/usr/local/sbin/consolepi-maintenance" /usr/local/sbin/consolepi-maintenance
install -m 0755 "$ROOT/usr/local/sbin/consolepi-login-status" /usr/local/sbin/consolepi-login-status
install -m 0755 "$ROOT/usr/local/sbin/consolepi-admin-menu" /usr/local/sbin/consolepi-admin-menu
install -m 0755 "$ROOT/usr/local/sbin/consolepi-reset-web-password" /usr/local/sbin/consolepi-reset-web-password
install -m 0755 "$ROOT/usr/local/sbin/consolepi-log-maintain" /usr/local/sbin/consolepi-log-maintain
install -m 0755 "$ROOT/usr/local/sbin/consolepi-transcript-writer" /usr/local/sbin/consolepi-transcript-writer
install -m 0755 "$ROOT/usr/local/sbin/consolepi-update-check" /usr/local/sbin/consolepi-update-check
install -m 0755 "$ROOT/usr/local/sbin/consolepi-generic-image-firstboot" /usr/local/sbin/consolepi-generic-image-firstboot
install -m 0755 "$ROOT/usr/local/sbin/consolepi-generic-recovery" /usr/local/sbin/consolepi-generic-recovery
install -m 0755 "$ROOT/usr/local/sbin/consolepi-prepare-generic-image" /usr/local/sbin/consolepi-prepare-generic-image
install -m 0644 "$ROOT/usr/local/lib/consolepi_firstboot_security.py" /usr/local/lib/consolepi_firstboot_security.py
install -m 0644 "$ROOT/usr/local/lib/consolepi_imager_security.py" /usr/local/lib/consolepi_imager_security.py
install -m 0644 "$ROOT/usr/local/lib/consolepi_generic_recovery.py" /usr/local/lib/consolepi_generic_recovery.py
install -m 0755 "$ROOT/usr/local/libexec/consolepi-imager-guard" /usr/local/libexec/consolepi-imager-guard
install -m 0755 "$ROOT/usr/local/libexec/consolepi-imager-custom-guard" /usr/local/libexec/consolepi-imager-custom-guard
install -m 0755 "$ROOT/usr/local/libexec/consolepi-imager-userconf-guard" /usr/local/libexec/consolepi-imager-userconf-guard
install -m 0755 "$ROOT/usr/local/libexec/consolepi-imager-postvalidate" /usr/local/libexec/consolepi-imager-postvalidate
install -m 0755 "$ROOT/usr/local/sbin/consolepi-snmp-pass-persist" /usr/local/sbin/consolepi-snmp-pass-persist
install -m 0755 "$ROOT/usr/local/sbin/consolepi-release" /usr/local/sbin/consolepi-release
install -m 0755 "$ROOT/usr/local/sbin/consolepi-release-runner" /usr/local/sbin/consolepi-release-runner
install -m 0644 "$ROOT/VERSION" /usr/share/consolepi/VERSION
install -m 0644 "$ROOT/etc/consolepi/update-allowed-signers" /etc/consolepi/update-allowed-signers
install -m 0644 "$ROOT/etc/profile.d/consolepi-status.sh" /etc/profile.d/consolepi-status.sh
install -d -m 0755 /usr/share/snmp/mibs
install -m 0644 "$ROOT/usr/share/snmp/mibs/CONSOLEPI-MIB.txt" /usr/share/snmp/mibs/CONSOLEPI-MIB.txt
install -m 0644 "$ROOT/etc/tmpfiles.d/consolepi.conf" /etc/tmpfiles.d/consolepi.conf
install -m 0644 "$ROOT/etc/logrotate.d/consolepi" /etc/logrotate.d/consolepi
install -m 0644 "$ROOT/etc/systemd/system/consolepi-web.service" /etc/systemd/system/consolepi-web.service
install -m 0644 "$ROOT/etc/systemd/system/consolepi-port-monitor.service" /etc/systemd/system/consolepi-port-monitor.service
install -m 0644 "$ROOT/etc/systemd/system/consolepi-update-check.service" /etc/systemd/system/consolepi-update-check.service
install -m 0644 "$ROOT/etc/systemd/system/consolepi-update-check.timer" /etc/systemd/system/consolepi-update-check.timer
install -m 0644 "$ROOT/etc/systemd/system/consolepi-system-upgrade.service" /etc/systemd/system/consolepi-system-upgrade.service
install -m 0644 "$ROOT/etc/systemd/system/consolepi-generic-image-firstboot.service" /etc/systemd/system/consolepi-generic-image-firstboot.service
install -m 0644 "$ROOT/etc/systemd/system/consolepi-generic-recovery.service" /etc/systemd/system/consolepi-generic-recovery.service
install -m 0644 "$ROOT/etc/nginx/sites-available/consolepi" /etc/nginx/sites-available/consolepi
install -m 0440 "$ROOT/etc/sudoers.d/consolepi-web" /etc/sudoers.d/consolepi-web
if [ "$UPDATE_MODE" = yes ]; then
    # Běžná aktualizace překladač nepotřebuje: hotový PAM modul se zachová.
    # Starší instalace ale mohly vzniknout po ručním odstranění modulu.
    # V takovém případě jej opravíme jednorázově z aktuálního zdroje.
    # Raspberry Pi OS uses merged-/usr, where /lib is a symlink to /usr/lib.
    # find(1) does not follow a symlink passed as its starting point by default,
    # so inspect the canonical /usr/lib tree as well.
    PAM_MODULE=$(find /lib /usr/lib -path '*/security/pam_consolepi_user.so' -type f -print -quit 2>/dev/null || true)
    [ -n "$PAM_MODULE" ] || {
        printf '%s\n' 'Chybí PAM modul ConsolePi; provádím jednorázovou opravu.'
        apt-get update
        apt-get install -y gcc libpam0g-dev
        PAM_MULTIARCH=$(cc -print-multiarch)
        cc -O2 -fPIC -Wall -Wextra -shared \
            -o "$BACKUP_DIR/pam_consolepi_user.so" "$ROOT/src/pam_consolepi_user.c" -lpam
        install -m 0644 "$BACKUP_DIR/pam_consolepi_user.so" \
            "/lib/$PAM_MULTIARCH/security/pam_consolepi_user.so"
    }
else
    PAM_MULTIARCH=$(cc -print-multiarch)
    cc -O2 -fPIC -Wall -Wextra -shared \
        -o "$BACKUP_DIR/pam_consolepi_user.so" "$ROOT/src/pam_consolepi_user.c" -lpam
    install -m 0644 "$BACKUP_DIR/pam_consolepi_user.so" \
        "/lib/$PAM_MULTIARCH/security/pam_consolepi_user.so"
fi

if [ -f "$ROOT/etc/udev/rules.d/70-consolepi.rules" ]; then
    backup_if_exists /etc/udev/rules.d/70-consolepi.rules
    install -m 0644 "$ROOT/etc/udev/rules.d/70-consolepi.rules" /etc/udev/rules.d/70-consolepi.rules
    udevadm control --reload-rules
    udevadm trigger --subsystem-match=tty
fi

if ! getent group console >/dev/null 2>&1; then
    groupadd --system console
fi
if ! id console >/dev/null 2>&1; then
    useradd --create-home --gid console --groups dialout --shell /bin/sh \
        --comment 'ConsolePi forced-command account' console
    passwd -l console >/dev/null 2>&1 || true
else
    usermod --append --groups dialout --shell /bin/sh console
fi

install -d -o console -g console -m 0700 /home/console/.ssh
if [ "$UPDATE_MODE" != yes ]; then
    install -o console -g console -m 0600 "$ROOT/authorized_keys" /home/console/.ssh/authorized_keys
fi

if ! getent group consolepi-web >/dev/null 2>&1; then
    groupadd --system consolepi-web
fi
if ! id consolepi-web >/dev/null 2>&1; then
    useradd --system --gid consolepi-web --home-dir /nonexistent \
        --shell /usr/sbin/nologin consolepi-web
fi
install -d -o consolepi-web -g consolepi-web -m 0700 /var/lib/consolepi-web/release-uploads

# A card-specific marker distinguishes the source card from a cloned image.
if [ "$FIRSTBOOT_PENDING" = yes ]; then
    printf '%s\n' '{"state": "pending", "reason": "fresh_install"}' >/etc/consolepi/firstboot.json
    chmod 0600 /etc/consolepi/firstboot.json
elif [ ! -e /etc/consolepi/firstboot.json ]; then
    python3 - <<'PY' >/etc/consolepi/firstboot.json
import json
from pathlib import Path

card = ""
for candidate in (
    Path("/sys/block/mmcblk0/device/cid"),
    Path("/sys/block/mmcblk0/device/serial"),
):
    try:
        value = candidate.read_text().strip().lower()
    except OSError:
        continue
    if value:
        card = value
        break
print(json.dumps({"state": "complete", "card_id": card}, indent=2))
PY
    chmod 0600 /etc/consolepi/firstboot.json
fi

backup_if_exists /opt/consolepi-web
install -d -o root -g root -m 0755 /opt/consolepi-web
cp -a "$ROOT/opt/consolepi-web/." /opt/consolepi-web/
chown -R root:root /opt/consolepi-web
find /opt/consolepi-web -type d -exec chmod 0755 {} \;
find /opt/consolepi-web -type f -exec chmod 0644 {} \;

if [ ! -s /etc/consolepi/web.secret ]; then
    python3 -c 'import secrets; print(secrets.token_hex(32))' >/etc/consolepi/web.secret
    chmod 0640 /etc/consolepi/web.secret
    chown root:consolepi-web /etc/consolepi/web.secret
fi

if [ ! -s /etc/consolepi/tls/consolepi.key ] || [ ! -s /etc/consolepi/tls/consolepi.crt ]; then
    TLS_IP=$(hostname -I | awk '{print $1}')
    openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 825 \
        -subj "/CN=$(hostname)" \
        -addext "subjectAltName=DNS:$(hostname),DNS:$(hostname).local,IP:$TLS_IP" \
        -keyout /etc/consolepi/tls/consolepi.key \
        -out /etc/consolepi/tls/consolepi.crt
    chmod 0600 /etc/consolepi/tls/consolepi.key
    chmod 0644 /etc/consolepi/tls/consolepi.crt
fi

if [ ! -s /etc/consolepi/web.auth ] && [ "$FIRSTBOOT_PENDING" != yes ]; then
    [ -t 0 ] || {
        printf '%s\n' 'První instalace webu vyžaduje interaktivní terminál pro zadání hesla.' >&2
        exit 1
    }
    printf 'Nové heslo webové administrace: ' >/dev/tty
    stty -echo </dev/tty
    IFS= read -r WEB_PASSWORD </dev/tty
    stty echo </dev/tty
    printf '\n' >/dev/tty
    [ "${#WEB_PASSWORD}" -ge 8 ] || {
        printf '%s\n' 'Webové heslo musí mít alespoň 8 znaků.' >&2
        exit 1
    }
    WEB_PASSWORD=$WEB_PASSWORD python3 -c \
        'import os; from werkzeug.security import generate_password_hash; print(generate_password_hash(os.environ["WEB_PASSWORD"]))' \
        >/etc/consolepi/web.auth
    unset WEB_PASSWORD
    chmod 0640 /etc/consolepi/web.auth
    chown root:consolepi-web /etc/consolepi/web.auth
fi

visudo -cf /etc/sudoers.d/consolepi-web
/usr/local/sbin/consolepi-control auth sync
rm -f /etc/nginx/sites-enabled/default
# Některé vadně zapsané SD karty změnily tento očekávaný symlink na adresář.
# Odstraníme jen přesně tento cíl a vždy vytvoříme správný symlink.
rm -rf /etc/nginx/sites-enabled/consolepi
ln -s /etc/nginx/sites-available/consolepi /etc/nginx/sites-enabled/consolepi
nginx -t

systemd-tmpfiles --create /etc/tmpfiles.d/consolepi.conf
chown root:console /var/log/consolepi
chmod 0750 /var/log/consolepi
chown console:console /var/log/consolepi/transcripts
chmod 0700 /var/log/consolepi/transcripts

sshd -t

if [ "$INSTALL_FIREWALL" = yes ]; then
    backup_if_exists /etc/nftables.conf
    nft_tmp=$(mktemp)
    trap 'rm -f "$nft_tmp"' EXIT HUP INT TERM
    sed "s#MANAGEMENT_CIDR#$MANAGEMENT_CIDR#g" "$ROOT/etc/nftables.conf" >"$nft_tmp"
    nft -c -f "$nft_tmp"
    install -m 0755 "$nft_tmp" /etc/nftables.conf
fi

# Starší instalace znaly jen jeden management subnet. Při aktualizaci jej
# převedeme na nový allowlist, jehož první neměnnou položkou je aktuální
# ethernetová síť; vlastní položky zůstávají v access-sources.json.
if [ "$UPDATE_MODE" = yes ]; then
    /usr/local/sbin/consolepi-control access migrate
fi

systemctl enable ssh
systemctl reload ssh
systemctl daemon-reload
systemctl enable nginx consolepi-web consolepi-port-monitor
if [ "$UPDATE_MODE" = yes ]; then
    # Webová aktualizace běží jako samostatný pracovní proces odvozený z
    # consolepi-web. Restart této služby by jej zabil dříve, než stačí zapsat
    # stav „rebooting“ a provést řízený restart celého zařízení. Nové soubory
    # se proto při aktualizaci aktivují až následným rebootem release runneru.
    printf '%s\n' 'Aktualizace: restart služeb je odložen až na řízený reboot ConsolePi.'
else
    systemctl restart nginx consolepi-web consolepi-port-monitor
fi
systemctl enable --now consolepi-update-check.timer

if [ "$INSTALL_FIREWALL" = yes ]; then
    systemctl enable nftables
    systemctl restart nftables
fi

printf '\nInstalace dokončena. Záloha: %s\n' "$BACKUP_DIR"
if [ "$FIRSTBOOT_PENDING" = yes ]; then
    printf '%s\n' 'Otevřete HTTPS adresu ConsolePi a dokončete průvodce nového zařízení.'
fi
printf '%s\n' 'PONECHTE TUTO SSH RELACI OTEVŘENOU a v novém terminálu ověřte port 22.'
/usr/local/sbin/consolepi-diagnose || true
