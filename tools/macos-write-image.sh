#!/bin/zsh
set -euo pipefail

usage() {
  cat <<'EOF'
Použití: macos-write-image.sh /cesta/ConsolePi-master.img /dev/diskN

Zapíše obraz na externí SD kartu, porovná velikost a po zápisu ověří obsah.
Všechna data na cílové kartě budou nenávratně přepsána.
EOF
}

[[ $# -eq 2 ]] || { usage >&2; exit 2; }
image=$1
disk=$2
[[ -f $image ]] || { print -u2 "Obraz neexistuje: $image"; exit 2; }
[[ $disk == /dev/disk<-> ]] || { print -u2 "Použijte celý disk, například /dev/disk6."; exit 2; }

info=$(diskutil info "$disk")
print -- "$info" | grep -q 'Internal:.*No' || { print -u2 "Odmítám interní disk: $disk"; exit 1; }
disk_bytes=$(print -- "$info" | sed -nE 's/.*\(([0-9]+) Bytes\).*/\1/p' | head -1)
image_bytes=$(stat -f '%z' "$image")
[[ $disk_bytes == <-> ]] || { print -u2 "Nelze zjistit velikost cílového disku."; exit 1; }
if (( image_bytes > disk_bytes )); then
  print -u2 "Obraz má $image_bytes B, ale cílová karta pouze $disk_bytes B. Zápis není bezpečný."
  exit 1
fi

if [[ -f "$image.sha256" ]]; then
  print "Ověřuji obraz podle $image.sha256"
  (cd "${image:h}" && shasum -a 256 -c "${image:t}.sha256")
fi

print "Obraz: $image ($image_bytes B)"
print "Cíl:   $disk ($disk_bytes B)"
print -n "Všechna data na $disk budou přepsána. Pro pokračování napište WRITE: "
read -r confirmation
[[ $confirmation == WRITE ]] || { print "Zrušeno."; exit 0; }

diskutil unmountDisk "$disk"
raw="/dev/r${disk#/dev/}"
sudo dd if="$image" of="$raw" bs=4m status=progress
sync

print "Ověřuji zapsaných $image_bytes bajtů."
sudo cmp -n "$image_bytes" "$image" "$raw"
diskutil eject "$disk"
print "Klon byl zapsán, ověřen a bezpečně vysunut."
