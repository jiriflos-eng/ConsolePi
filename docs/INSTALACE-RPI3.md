# ConsolePi+: čistá instalace na Raspberry Pi 3

Tento postup nahrazuje klonování bitové kopie SD karty. Výsledkem je nové,
nezávislé zařízení: má vlastní SSH hostitelské klíče, HTTPS certifikát,
identitu i webové heslo. Soukromé SSH klíče se nikam nekopírují.

## Co je potřeba

- Raspberry Pi 3, stabilní zdroj a microSD alespoň 16 GB;
- ethernet do management sítě s DHCP nebo známým statickým nastavením;
- Mac s Raspberry Pi Imagerem a instalačním balíčkem ConsolePi+;
- přístup k internetu pro první instalaci balíčků APT, případně nastavený
  firemní proxy server;
- vlastní veřejný SSH klíč. Jeho soukromá část zůstává v počítači správce.

## 1. Zápis Raspberry Pi OS Lite

1. Otevřete **Raspberry Pi Imager** a vyberte **Raspberry Pi OS Lite (64-bit)**.
2. Jako zařízení zvolte **Raspberry Pi 3** a vyberte správnou microSD kartu.
3. V rozšířeném nastavení Imageru nastavte:
   - dočasný hostname, například `consolepi`;
   - uživatele `consolepi` a jedinečné dočasné silné heslo (nejde o heslo
     distribuované generic image);
   - časové pásmo a klávesnici;
   - **Enable SSH** → **Allow public-key authentication only** a vložte svůj
     veřejný klíč;
   - Wi-Fi není nutná; ConsolePi+ je určené pro ethernet.
4. Zapište kartu, vložte ji do Raspberry Pi a zapněte jej.
5. V DHCP serveru nebo skeneru sítě zjistěte IP adresu a přihlaste se:

   ```sh
   ssh -i "$HOME/.ssh/consolepi-admin" consolepi@IP_ADRESA_PI
   ```

Přihlášení heslem nepoužívejte. ConsolePi+ vyžaduje veřejný klíč, který bootstrap
převezme také pro technický účet `console` používaný na portech 2201–2204.

## 2. Vytvoření instalačního balíčku na Macu

V kořenu zdrojů ConsolePi+ spusťte:

```sh
cd "/cesta/k/consolepi-server"
./tools/build-install-bundle.sh
shasum -a 256 -c dist/ConsolePi-Plus-*-install.tar.gz.sha256
```

Vznikne například `dist/ConsolePi-Plus-1.4.0-install.tar.gz`. Balíček neobsahuje
žádný privátní klíč, webové heslo, RADIUS tajemství ani konfiguraci jiného
zařízení.

## 3. Kopie balíčku na nové Raspberry Pi

Z Macu:

```sh
scp dist/ConsolePi-Plus-*-install.tar.gz consolepi@IP_ADRESA_PI:/tmp/
ssh -tt consolepi@IP_ADRESA_PI
```

Na Raspberry Pi rozbalte a spusťte bootstrap:

```sh
cd /tmp
tar -xzf ConsolePi-Plus-*-install.tar.gz
cd ConsolePi-Plus-*-install
./bootstrap-install.sh
```

Bootstrap automaticky vezme síť získanou na `eth0` a nastaví ji jako první
povolený zdroj pro HTTPS, administrativní SSH a konzolové porty.

Pro statickou nebo jinou management síť ji zadejte výslovně:

```sh
./bootstrap-install.sh --management-cidr 10.176.122.0/24
```

Volitelné úplné přepisy sériové komunikace (s automatickou rotací a ochranou
volného místa) zapnete při instalaci:

```sh
./bootstrap-install.sh --enable-transcripts
```

## 4. Co instalátor nastaví

Instalátor vytvoří a nastaví zejména:

| Oblast | Nastavení |
| --- | --- |
| Technický účet | `console`, bez shellu, člen skupiny `dialout`, veřejné SSH klíče správce |
| Web | `consolepi-web`, systémový účet bez přihlášení |
| Sériové zámky | `/run/lock/consolepi`, `root:console`, režim `0775` |
| Logy | `/var/log/consolepi`, `root:console`, režim `0750` |
| Přepisy relací | `/var/log/consolepi/transcripts`, `console:console`, režim `0700` |
| Citlivá konfigurace | RADIUS, SNMP a webová tajemství v režimu `0600` nebo `0640` |
| Služby | SSH, nginx, web ConsolePi+, monitoring USB portů, automatická kontrola aktualizací a nftables |

Tím je zajištěno, že účet `console` může otevřít sériový adaptér i vytvářet
volitelné přepisy, ale nemá administrativní shell ani přístup k tajemstvím.

## 5. Dokončení ve webovém průvodci

Po skončení instalace otevřete:

```text
https://IP_ADRESA_PI/
```

Prohlížeč správně upozorní na nový lokální HTTPS certifikát. Pokračujte na
stránku a dokončete průvodce:

1. nastavte nové heslo webové administrace;
2. vyplňte hostname, zobrazovaný název, umístění a popis;
3. potvrďte regeneraci SSH hostitelských klíčů a HTTPS certifikátu;
4. pokud je kořenový oddíl menší než fyzická SD karta, nabídněte rozšíření;
5. po dokončení se zobrazí neprivilegovaný přehled konzolí.

Následně se přihlaste tlačítkem **Admin**. V kartě **Síť** podle potřeby
přidejte další povolené zdrojové IP adresy/sítě, CDP/LLDP a SNMPv3. V kartě
**Autentizace** zvolte lokální heslo, SSH klíč nebo RADIUS.

## 6. Kontrola instalace

Administrativní SSH zůstává na portu 22:

```sh
ssh consolepi@IP_ADRESA_PI
sudo consolepi-diagnose
sudo systemctl status consolepi-web nginx nftables consolepi-port-monitor
sudo stat -c '%U:%G %a %n' /var/log/consolepi /var/log/consolepi/transcripts
```

Připojení k sériovému portu po přiřazení kabelu:

```sh
ssh -tt -p 2201 console@IP_ADRESA_PI
```

## Běžná údržba

- Konfiguraci a systém aktualizujte z webu v **Systém → Údržba**.
- Čistě nainstalované zařízení není nutné klonovat. Pro další RPi vždy
  opakujte tento postup z téhož instalačního balíčku.
- Reset do továrního nastavení smaže provozní konfiguraci a po restartu znovu
  otevře průvodce. Neodstraňuje samotnou aplikaci ani balíčky Raspberry Pi OS.
