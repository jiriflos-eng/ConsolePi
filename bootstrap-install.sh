#!/bin/sh
# Bootstrap ConsolePi from a freshly installed Raspberry Pi OS Lite system.
set -eu

PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ADMIN_USER=$(id -un)
AUTHORIZED_KEYS=""
MANAGEMENT_CIDR=""
TRANSCRIPTS=no

usage()
{
    cat <<'EOF'
Použití: ./bootstrap-install.sh [volby]

Spouští se jako běžný administrátor Raspberry Pi OS, ne jako root.
Pokud má správce veřejný SSH klíč, převezme jej pro technický účet ConsolePi
`console`. Při přihlášení heslem vytvoří jen dočasný klíč bez soukromé části;
v průvodci prvního spuštění pak vytvoříte nebo vložíte skutečný osobní klíč.

Volby:
  --admin-user UŽIVATEL       účet s veřejnými klíči (výchozí: aktuální uživatel)
  --authorized-keys SOUBOR    jiný soubor authorized_keys
  --management-cidr CIDR      povolená IPv4 síť pro HTTPS/SSH; výchozí podle eth0
  --enable-transcripts        zapnout úplné záznamy sériových relací
  -h, --help                  zobrazit nápovědu
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --admin-user)
            [ "$#" -ge 2 ] || { usage >&2; exit 2; }
            ADMIN_USER=$2
            shift 2
            ;;
        --authorized-keys)
            [ "$#" -ge 2 ] || { usage >&2; exit 2; }
            AUTHORIZED_KEYS=$2
            shift 2
            ;;
        --management-cidr)
            [ "$#" -ge 2 ] || { usage >&2; exit 2; }
            MANAGEMENT_CIDR=$2
            shift 2
            ;;
        --enable-transcripts)
            TRANSCRIPTS=yes
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

[ "$(id -u)" -ne 0 ] || {
    printf '%s\n' 'Bootstrap spouštějte jako běžný administrátor, bez sudo.' >&2
    exit 1
}

getent passwd "$ADMIN_USER" >/dev/null || {
    printf 'Uživatel neexistuje: %s\n' "$ADMIN_USER" >&2
    exit 1
}

if [ -z "$AUTHORIZED_KEYS" ]; then
    ADMIN_HOME=$(getent passwd "$ADMIN_USER" | awk -F: '{print $6}')
    AUTHORIZED_KEYS=$ADMIN_HOME/.ssh/authorized_keys
fi

KEY_PATTERN='^[[:space:]]*(ssh-(ed25519|rsa)|ecdsa-sha2-nistp(256|384|521)|sk-(ssh-ed25519|ecdsa-sha2-nistp256)@openssh\.com)[[:space:]]+'
TEMP_KEY_DIR=''
if [ -r "$AUTHORIZED_KEYS" ] && grep -Eq "$KEY_PATTERN" "$AUTHORIZED_KEYS"; then
    printf '%s\n' 'Používám existující veřejný SSH klíč správce.'
else
    # Instalace přes heslo je podporována. Technický účet vyžaduje klíč již
    # během instalace, proto vznikne jednorázový klíč; soukromá část se po
    # instalaci odstraní. Průvodce jej nahradí skutečným klíčem správce.
    TEMP_KEY_DIR=$(mktemp -d)
    trap 'rm -rf "$TEMP_KEY_DIR"' EXIT HUP INT TERM
    ssh-keygen -q -t ed25519 -N '' -C 'consolepi-bootstrap-temporary' -f "$TEMP_KEY_DIR/consolepi-bootstrap"
    AUTHORIZED_KEYS="$TEMP_KEY_DIR/consolepi-bootstrap.pub"
    printf '%s\n' 'Nebyl nalezen veřejný SSH klíč; vytvářím dočasný klíč pro dokončení instalace.'
fi

if [ -z "$MANAGEMENT_CIDR" ]; then
    ADDRESS=$(ip -o -4 addr show dev eth0 scope global 2>/dev/null | awk 'NR == 1 {print $4}')
    [ -n "$ADDRESS" ] || {
        printf '%s\n' 'Na eth0 nebyla nalezena IPv4 adresa. Zadejte --management-cidr ručně.' >&2
        exit 1
    }
    MANAGEMENT_CIDR=$(python3 - "$ADDRESS" <<'PY'
import ipaddress
import sys
print(ipaddress.ip_interface(sys.argv[1]).network)
PY
)
fi

case "$MANAGEMENT_CIDR" in
    *[!0-9./]*|*.*.*.*.*|''|*/*/*)
        printf 'Neplatný formát IPv4 CIDR: %s\n' "$MANAGEMENT_CIDR" >&2
        exit 2
        ;;
esac

# Do instalačního adresáře zapisujeme pouze veřejné klíče. Soukromý klíč
# zůstává vždy na počítači správce a balíček jej nikdy neobsahuje.
install -m 0600 "$AUTHORIZED_KEYS" "$ROOT/authorized_keys"

printf 'Instalace ConsolePi: management síť %s\n' "$MANAGEMENT_CIDR"
if [ "$TRANSCRIPTS" = yes ]; then
    sudo "$ROOT/install.sh" --firstboot --management-cidr "$MANAGEMENT_CIDR" --enable-transcripts
else
    sudo "$ROOT/install.sh" --firstboot --management-cidr "$MANAGEMENT_CIDR"
fi

WEB_IP=$(ip -o -4 addr show dev eth0 scope global 2>/dev/null | awk 'NR == 1 {sub(/\/.*/, "", $4); print $4}')
[ -n "$WEB_IP" ] || WEB_IP='IP_ADRESA_RASPBERRY_PI'

cat <<EOF


╔══════════════════════════════════════════════════════════════════════╗
║                     ✓  CONSOLEPI JE NAINSTALOVÁNO  ✓                ║
╚══════════════════════════════════════════════════════════════════════╝

  Instalace služeb, firewallu a bezpečného HTTPS přístupu proběhla úspěšně.
  V průvodci nastavíte skutečný administrativní SSH klíč. Na Raspberry Pi se
  ukládají pouze veřejné klíče; soukromý klíč vždy zůstává na vašem počítači.

  Co udělat nyní:

  1. V prohlížeči otevřete:  https://$WEB_IP/
  2. Dokončete průvodce prvního spuštění:
     - nastavte webové heslo,
     - vyplňte identitu zařízení,
     - nastavte nebo vložte administrativní SSH klíč,
     - podle potřeby rozšiřte oddíl SD karty.
  3. Důležité: dokončení průvodce vytvoří nové SSH hostitelské klíče.
     Pokud jste se na stejnou IP adresu připojovali dříve, na správním
     počítači před dalším SSH jednou spusťte:
     ssh-keygen -R $WEB_IP
     Potom se připojte znovu a potvrďte nový fingerprint zařízení.
  4. Přihlaste se do administrativního SSH:
     ssh -i ~/.ssh/consolepi-admin $ADMIN_USER@$WEB_IP
  5. Připojte USB konzolové kabely a v přehledu jim přiřaďte porty 2201–2204.

  Poznámka: při prvním otevření HTTPS prohlížeč upozorní na nový lokální
  certifikát. Je to očekávané; certifikát byl právě vytvořen pro toto zařízení.

EOF

if [ "$TRANSCRIPTS" = yes ]; then
    printf '%s\n' '  Záznam sériové komunikace: ZAPNUTÝ (spravujete ve webu v části Logy).'
fi
printf '%s\n\n' '  Hotovo. Přejeme klidnou správu konzolí. ✨'
