# Interaktivní menu pro administrativní SSH i lokální klávesnici a monitor.
if [ "${USER:-}" = "consolepi" ] && [ -t 0 ] && [ -t 1 ]; then
    exec /usr/local/sbin/consolepi-admin-menu
fi
