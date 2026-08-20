# ConsolePi Plus template for Zabbix 7.4

`template_consolepi_snmpv3_7.4.yaml` monitors a ConsolePi Plus system through its
read-only SNMPv3 `authPriv` interface. It contains no user name or passphrases.
After importing a newer revision, use **Execute now** on both discovery rules
if you want service and serial-console rows to appear immediately.

## Import and host configuration

1. In Zabbix, open **Data collection → Templates → Import** and import the YAML
   file.
2. Link **ConsolePi+ by SNMPv3** to the ConsolePi Plus host. Its underlying
   technical template identifier remains unchanged for compatibility with
   existing Zabbix hosts and triggers.
3. Configure the host's SNMP interface with:
   - Version: **SNMPv3**
   - Context name: **empty**
   - Security name: the ConsolePi Plus SNMPv3 user
   - Security level: **authPriv**
   - Authentication protocol: **SHA-256**
   - Privacy protocol: **AES128**
   - authentication and privacy passphrases from the ConsolePi Plus web interface.
4. Ensure that the Zabbix server or proxy source IP/network is listed under
   **ConsolePi+ → Síť → Povolené zdroje přístupu**. ConsolePi Plus permits UDP/161
   only from this management allowlist.
5. To receive automatic service and serial-console discovery immediately, open
   the host's **Discovery rules** and choose **Execute now** for both rules.

The template uses numeric OIDs, so installing `CONSOLEPI-MIB.txt` on the
Zabbix server is optional. The MIB remains useful for manual SNMP tools.

## Monitored values

- CPU utilization and CPU temperature;
- used/total memory and memory utilization;
- used/total root filesystem capacity and utilization;
- uptime;
- cached count of available package updates and reboot-required state;
- Ethernet link state;
- automatic discovery of ConsolePi Plus service states;
- automatic discovery of ConsolePi Plus serial-console port states.

ConsolePi Plus exports temperature in tenths of a degree Celsius; the template
applies a `0.1` multiplier. Service state values are mapped as `1 = Active`
and `2 = Inactive`. Serial-console states are `1 = Unassigned`, `2 =
Disconnected`, and `3 = Connected`. The update count is read from ConsolePi Plus's
local update-check cache; polling SNMP never starts APT or makes a network call.
