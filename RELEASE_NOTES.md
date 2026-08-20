# ConsolePi+ 1.9.0 · Integrace a provoz

- V **Síť → APT repozitáře** lze přepnout mezi oficiálními zdroji Debianu/Raspberry Pi a vlastním lokálním mirrorem. Každá změna se před uložením ověřuje odděleným během `apt-get update`, takže nefunkční mirror nenahradí funkční konfiguraci.
- Proxy zůstává samostatné nastavení: lze ji kombinovat s oficiálními repozitáři i s vlastním mirrorem.
- Příprava generic image vždy odstraní proxy a všechny doplňkové APT zdroje, poté obnoví oficiální Raspberry Pi OS repozitáře bez přebírání identity nebo interních adres z master zařízení.
- Záznam sériových relací se bezpečně dokončí i při zavření SSH klienta; port se po ukončení relace korektně uvolní.
- Rozhraní ConsolePi+ sjednocuje síťové a integrační nastavení, přidává přehlednější formuláře a aktualizovanou načítací animaci.

# ConsolePi+ 1.7.0 · Zabbix monitoring

- Přidána importovatelná šablona pro Zabbix 7.4 bez uložených SNMPv3 přihlašovacích údajů.
- SNMPv3 nově poskytuje stav ethernetu, dostupné aktualizace, požadavek na restart a automatický přehled služeb i sériových portů.
- Návod popisuje bezpečné propojení Zabbixu přes stávající allowlist firewallu; UDP/161 se mimo povolené zdroje neotevírá.

# ConsolePi+ 1.6.6 · Spouštěče desktopového Discovery

- macOS ZIP obsahuje složku s aplikací a spouštěčem `Spustit ConsolePi Plus Discovery.command`; po kontrole checksumu odstraní karanténu pouze z přibalené aplikace a otevře ji.
- Windows ZIP používá stejnou strukturu se spouštěčem `Spustit ConsolePi Plus Discovery.cmd`. Microsoft SmartScreen není obcházen; před spuštěním ověřte checksum souboru.
- macOS balíček už nepřenáší skryté AppleDouble soubory, takže ad-hoc podpis aplikace zůstává po rozbalení platný.

# ConsolePi+ 1.6.5 · Desktopový ConsolePi Plus Discovery

- ConsolePi Plus Discovery je nyní připravený jako aplikace pro macOS a Windows: dvojklik otevře lokální grafické rozhraní bez nutnosti pracovat v terminálu.
- Balíčky obsahují společnou ikonu pro Finder, Dock a Průzkumník souborů. Příkaz `--shell` ponechává dostupný textový výpis pro automatizaci.
- Generování administrátorského klíče používá jednotný komentář `consolepi-administrator-key`, který zůstává jedním polem veřejného klíče.

# ConsolePi+ 1.6.4 · Jednotné offline písmo rozhraní

- Web ConsolePi+ používá vlastní lokálně dodané řezy Noto Sans pro celý text, takže se rozhraní na macOS, Windows a Linuxu vykresluje jednotně i bez přístupu k internetu.
- Nápis ConsolePi+ používá zaoblené písmo Baloo 2. Obě rodiny zahrnují Latin Extended včetně české diakritiky; pro další písma lze bezpečně přidat příslušné subsety Noto Sans.
- ConsolePi+ se oznamuje přes mDNS/Bonjour jako `_consolepi._tcp.local`; samostatný nástroj ConsolePi Plus Discovery pro macOS, Windows a Linux je součástí zdrojového stromu a po připojení Ethernetu najde adresu zařízení bez síťového skenování.
- Discovery zobrazuje hostname, zobrazovaný název a umístění zařízení. Tyto údaje se automaticky synchronizují po jejich uložení ve webové správě ConsolePi+.

# ConsolePi+ 1.6.3 · Spolehlivé dokončení změny síťové adresy

- Změna síťového profilu se aktivuje s krátkým zpožděním, takže web stihne zobrazit cílovou adresu a další postup dříve, než původní spojení zanikne.
- Po přihlášení na nové adrese správce změnu výslovně potvrdí; bez potvrzení se po 120 sekundách automaticky obnoví předchozí profil.
- Současně lze připravovat pouze jednu změnu sítě a její stav je bezpečně uložen na serveru.

# ConsolePi+ 1.6.2 · Management sítě z terminálu

- Terminálové administrační menu umožňuje zobrazit, přidat a odebrat explicitně povolené management IPv4 sítě stejným validovaným backendem jako web.
- Před změnou adresy ConsolePi+ do jiné sítě menu připomene povolení původní administrátorské sítě, aby se správce neuzamkl mimo SSH a HTTPS.
- Firewall se po změně DHCP adresy automaticky synchronizuje s novou lokální ethernetovou sítí a nadále zachovává explicitně povolené routované sítě.
- Z webového rozhraní a dokumentace bylo odstraněno dříve přidané informační zápatí; aktualizace odstraní také jeho starou šablonu.
- Generic first boot dočasně zpřístupní z IPv4 sítí pouze SSH 22 a web 80/443. Webový průvodce vyžaduje povinnou management síť; po dokončení se globální pravidlo odstraní.

# ConsolePi+ 1.6.1 · Spolehlivá příprava generic image

- Sanitizaci lze spustit volbou `--poweroff` jako samostatnou systemd úlohu; přerušení SSH relace ji nezastaví.
- Zařízení se vypne pouze po úplné post-sanitizační kontrole a vytvoření zabezpečeného persistentního PASS reportu.
- Generic first boot vyžaduje platný PASS report, takže neúplný nebo neověřený master zůstane fail-closed.
- Aktualizace rozpracovaného generic webového provisioningu již nevyžaduje dočasné sdílené heslo.

# ConsolePi+ 1.6.0 · Test plynulé aktualizace

- Testovací vydání ověřuje bezvarovné rozbalení aktualizace ve verzi 1.5.1 a novější.
- Nemění síť, firewall, sériové porty, uživatele, klíče ani logy.

# ConsolePi+ 1.5.1 · Oprava aktualizace starších instalací

- Pokud starší instalaci chybí PAM modul ConsolePi+, aktualizace jej jednorázově znovu sestaví a nainstaluje.
- Odstraněno varování Pythonu 3.14 při bezpečném rozbalování aktualizačního archivu.
- Běžné aktualizace nadále nevyžadují kompilátor; oprava se provede jen při skutečně chybějícím modulu.

# ConsolePi+ 1.5.0 · Test aktualizačního mechanismu

- Testovací vydání pro ověření nahrání, kontroly podpisu, instalace a řízeného návratu webové administrace.
- Nemění konfiguraci sítě, firewallu, sériových portů, účtů, klíčů ani záznamů.
- Součástí je oprava bootstrapu: čistou instalaci lze spustit i po SSH přihlášení heslem.

# ConsolePi+ 1.4.9 · Instalace i přes SSH heslo

- Bootstrap instalace již nevyžaduje existující veřejný SSH klíč.
- Při přihlášení heslem vytvoří jednorázový instalační klíč bez uložené soukromé části.
- Průvodce prvního spuštění uloží zvolený administrativní veřejný klíč také pro technický účet `console`, aby jím šlo přistupovat ke konzolovým portům.

# ConsolePi+ 1.4.8 · SSH přístup při prvním spuštění

- Průvodce prvního spuštění nyní vyžaduje rozhodnutí o administrativním SSH přístupu: lze vložit existující veřejný Ed25519 klíč nebo bezpečně vytvořit nový osobní klíč s jednorázovým stažením privátní části.
- Vygenerovaný soukromý klíč nikdy neopouští prohlížeč a ConsolePi+ uchovává pouze veřejnou část pro účet `consolepi` na SSH portu 22.
- Aktualizace již nevyžadují kompilátor `cc` ani `dpkg-architecture`; PAM modul se vytváří pouze při čisté instalaci. Odlehčená instalace bez vývojových balíčků se proto může bezpečně aktualizovat.

# ConsolePi+ 1.4.6 · spolehlivé stažení přístupového klíče

- Opraven globální indikátor načítání po vytvoření osobního SSH klíče: formuláře vracející soubor ke stažení už nenechají webovou stránku rozostřenou a zablokovanou.

# ConsolePi+ 1.4.5 · bezpečné navázání po prvním spuštění

- Závěrečný výpis bootstrap instalace nově upozorňuje na vytvoření nových SSH hostitelských klíčů po dokončení průvodce.
- README obsahuje přesný jednorázový příkaz `ssh-keygen -R IP_RPI` pro odstranění starého fingerprintu při opětovném použití stejné IP adresy.

# ConsolePi+ 1.4.4 · spolehlivý upload aktualizací

- Opraven upload aktualizačních balíčků: poznámky k vydání se již neukládají do cookie webové relace.
- Ověření balíčku s delšími poznámkami nyní nevyvolá nginx chybu `upstream sent too big header` ani 502.

# ConsolePi+ 1.4.3 · bezpečný návrat po aktualizaci

- Nginx při krátké nedostupnosti webové aplikace po aktualizaci místo technické chyby 502/503/504 zobrazí stránku ConsolePi+ se stavem restartu.
- Stránka se po pěti sekundách automaticky vrátí na přehled zařízení; uživatel nemusí opakovat nahrání ani instalaci balíčku.

# ConsolePi+ 1.4.2 · srozumitelné dokončení instalace

- Bootstrap po úspěšné instalaci zobrazí závěrečný přehled s adresou webu, SSH příkazem a doporučenými dalšími kroky.
- Instalace už nepoužívá `exec`, takže úspěšné dokončení není skryté za výpisem instalačních služeb.

# ConsolePi+ 1.4.1 · opravy prvního spuštění a terminálu

- Průvodce prvního spuštění po obnově HTTPS identity zobrazuje samostatnou stylovanou dokončovací stránku; změna certifikátu již nezpůsobí nezformátovanou stránku.
- Rámečky v administrativním SSH přehledu i při připojení ke konzoli počítají skutečnou šířku znaků. Pravý okraj tedy zůstává zarovnaný i u českého textu s diakritikou.
- Aktualizační balíček již neobsahuje archivní instalační soubory z adresáře `dist`, takže je menší a bezpečně projde limitem webového uploadu.

# ConsolePi+ 1.4.0 · čistá instalace Raspberry Pi OS

- Přidán přenositelný instalační balíček pro nový Raspberry Pi OS Lite bez závislosti na bitové kopii SD karty.
- Bootstrap bezpečně převezme pouze veřejné SSH klíče správce a po instalaci otevře průvodce nového zařízení.
- Přidán samostatný instalační návod pro Raspberry Pi 3 včetně kontroly oprávnění účtů a adresářů.
- Instalační archiv vytvořený na macOS neukládá Finder metadata ani nezobrazuje při rozbalení v Linuxu varování o rozšířených atributech.
- Nová instalace vždy začíná čtyřmi nepřiřazenými porty `KONZOLE-1` až `KONZOLE-4`; historická USB přiřazení ani názvy kabelů se nepřenášejí.

# ConsolePi+ 1.3.4 · spolehlivé záznamy konzolí

- Opraven přístup uživatele `console` do adresáře přepisů sériových relací.
- Chyba oprávnění logovacího adresáře již nikdy nevypíše Python traceback do připojené konzole; záznam se pouze bezpečně vynechá.

# ConsolePi+ 1.3.3 · vyrovnané služby

- Karta služeb je širší; názvy se na běžné obrazovce nezalamují.
- Akční ikony a barevné štítky stavů používají pevné sloupce.

# ConsolePi+ 1.3.2 · přehlednější služby

- Služby mají sjednocené sloupce: název vlevo, akce uprostřed a barevný stav vpravo.

# ConsolePi+ 1.3.1 · SNMPv3 a čistší firewallový log

- U služby snmpd je tlačítko ▶ pro přímé otevření nastavení SNMPv3 v kartě Síť.
- Firewallový log nyní vynechá každý již povolený zdroj, včetně vědomě nastaveného rozsahu 0.0.0.0/0.

# ConsolePi+ 1.3.0 · SNMPv3 dohled

- V kartě Síť je nový panel SNMPv3 pod CDP/LLDP.
- Podporován je pouze režim SNMPv3 authPriv: SHA-256 pro ověření a AES pro šifrování.
- UDP/161 se automaticky řídí stejným seznamem povolených zdrojů jako HTTPS a SSH.
- Součástí je ke stažení CONSOLEPI-MIB.txt s CPU, teplotou, pamětí, diskem, uptime a stavem služeb ConsolePi+.

# ConsolePi+ 1.2.7 · čistší horní lišta

- Z horní lišty byl odstraněn redundantní stav Ethernetu; webová administrace je dostupná pouze při síťovém spojení.

# ConsolePi+ 1.2.6 · upozornění na systémové aktualizace

- Horní lišta nyní zobrazí jantarový odkaz na Údržbu, pokud jsou dostupné systémové aktualizace.
- Odkaz se automaticky skrývá, pokud systém žádné aktualizace nehlásí.

# ConsolePi+ 1.2.1 · Sjednocená stránka Síť

- Všechny panely na stránce Síť mají jednotnou šířku.
- Aktuální stav ethernetového rozhraní má jemné světle okrové zvýraznění.
- Volba DHCP/statická IPv4 konfigurace je nyní samostatný bílý panel se zaoblením a sjednoceným ovládáním.

# ConsolePi+ 1.2.0 · Povolené zdroje přístupu

- Firewall je nově spravovaný jako skutečný allowlist IPv4 adres a sítí.
- Aktuální lokální ethernetová síť je vždy automaticky povolená a nelze ji omylem odstranit.
- Do tabulky lze přidat jednotlivé IPv4 adresy i CIDR rozsahy včetně vlastního popisu.
- Hodnota `0.0.0.0/0` je možná jen po výslovném potvrzení `POVOLIT VŠEM`.
- Tovární reset smaže vlastní zdroje; zůstane pouze nově získaná lokální DHCP síť.
- Aktualizace z dřívějších verzí automaticky převede původní firewall na nový model.
- Instalátor opravuje případ, kdy se nginx symlink `sites-enabled/consolepi` chybně stal adresářem.

# ConsolePi+ 1.1.8 · SSH terminal bez diakritiky

- Banner seriove relace a administrativni SSH terminal pouzivaji text bez diakritiky pro spolehlive zobrazeni ve vsech terminalech.

# ConsolePi+ 1.1.7 · zachování výběru portu při USB detekci

- Automatické obnovení seznamu nepřiřazených kabelů nyní zachová ručně vybraný SSH port až do stisknutí tlačítka „Přiřadit kabel“.

# ConsolePi+ 1.1.5 · popisky v SSH terminálu

- Uložený popisek připojeného portu se zobrazí také v banneru relace SSH a v administračním terminálovém přehledu.
- Při odpojení kabelu se přehled vrátí na neutrální `KONZOLE-x`.

# ConsolePi+ 1.1.4 · oprava spuštění konzolové relace

- Opravena chyba podmínky záznamu sériové komunikace, která po zobrazení banneru vypisovala `[: missing ]`.

# ConsolePi+ 1.1.3 · oprava zámků konzolových relací

- Opraveno vytvoření zámků portů po administrativní změně přiřazení: relace uživatele `console` nyní může konzoli otevřít i bez připojeného Cisco zařízení.

# ConsolePi+ 1.1.2 · zvýraznění názvů konzolí

- Hlavní názvy konzolí a uložené popisky používají samostatný zelenomodrý odstín, čitelný v denním i nočním režimu.

# ConsolePi+ 1.1.1 · živé názvy konzolí ve veřejném přehledu

- Uložený popisek portu je při připojeném kabelu jeho hlavním názvem na přihlášeném i veřejném přehledu.
- Po odpojení kabelu se název bezpečně vrátí na `KONZOLE-x`; veřejný přehled se aktualizuje automaticky, bez načtení stránky.
- Veřejné rozhraní načítá pouze bezpečný provozní stav portů, nikoli cesty zařízení ani USB identifikátory.

# ConsolePi+ 1.1.0 · přiřazení USB konzolí po resetu

- Přehled automaticky najde USB–RS232 adaptéry, které jsou připojené, ale ještě nemají přiřazený SSH port.
- Každému nalezenému kabelu lze jedním krokem vybrat port 2201–2204. Uloží se stabilní cesta `/dev/serial/by-id`, proto kabel zůstane správně rozpoznaný i po prohození USB konektorů nebo restartu.
- Detail portu umí přiřazení bezpečně odebrat, například při výměně adaptéru.
- Po továrním resetu lze nejdříve dokončit úvodní průvodce a kabely připojit až později; jejich přiřazení se objeví na přehledu samo.

> Aktualizace nemění existující mapování portů, síť, identitu, uživatele, klíče ani nastavení autentizace.
# ConsolePi+ 1.2.2 · oprava překrývajících se rozsahů firewallu

- Generátor nftables před zápisem automaticky sloučí překrývající se IPv4 rozsahy. Přidání `0.0.0.0/0` proto bezpečně nahradí jednotlivé užší rozsahy v nftables setu a služba se spustí.
- Potvrzovací pole `POVOLIT VŠEM` se zobrazí pouze tehdy, když upravovaný nebo nový rozsah skutečně obsahuje `0.0.0.0/0`.
# ConsolePi+ 1.2.3 · přehled zahazovaných paketů

- U služby `nftables` je k dispozici ikona pro zobrazení posledních 100 zahazovaných paketů.
- Výpis barevně rozlišuje čas, zdrojovou IP adresu a zdrojový/cílový port a lze jej posouvat.
- Firewall nezapisuje pakety z lokální ethernetové sítě a zápis ostatních zahazovaných paketů omezuje na 10 za minutu, krátce maximálně na 20 záznamů.
# ConsolePi+ 1.2.4 · zachování zápisu hostname

- Hostname v identitě zařízení nyní zachovává zadaná velká i malá písmena; již se automaticky nepřepisuje na malá.
- V části Údržba jsou nyní samostatně za sebou Aktualizace ConsolePi+ a Systémové aktualizace Raspberry Pi OS.
# ConsolePi+ 1.2.5 · spolehlivé systémové aktualizace

- Řízené systémové aktualizace používají `apt-get full-upgrade`, takže nainstalují i aktualizace kernelu vyžadující nový závislý balíček.
- Chyby obnovení repozitářů nyní odlišují nedostupný internet/DNS od nedostupného repozitáře nebo proxy.
- Ikona výpisu firewallu je v řádku služby umístěná hned za názvem `nftables`, před stavem služby.
