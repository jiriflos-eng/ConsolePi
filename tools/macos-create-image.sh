#!/bin/zsh
set -euo pipefail

usage() {
  cat <<'EOF'
Použití:
  macos-create-image.sh /dev/diskN /cesta/ConsolePi-master.img
  macos-create-image.sh --bytes POCET /dev/diskN /cesta/ConsolePi-compact.img

Vytvoří obraz externí SD karty a soubor SHA-256.
Bez --bytes se čte celá fyzická karta. --bytes použijte pouze pro známý
konec posledního oddílu, například 7948206080 pro dříve ověřený 8GB obraz.
EOF
}

bytes=""
if [[ ${1:-} == "--bytes" ]]; then
  bytes=${2:-}
  shift 2
  [[ $bytes == <-> ]] && (( bytes > 0 )) || { print -u2 "Neplatný počet bajtů."; exit 2; }
fi

[[ $# -eq 2 ]] || { usage >&2; exit 2; }
disk=$1
image=$2
[[ $disk == /dev/disk<-> ]] || { print -u2 "Použijte celý disk, například /dev/disk6."; exit 2; }
[[ ! -e $image ]] || { print -u2 "Cílový soubor již existuje: $image"; exit 2; }

info=$(diskutil info "$disk")
print -- "$info" | grep -q 'Internal:.*No' || { print -u2 "Odmítám interní disk: $disk"; exit 1; }
disk_bytes=$(print -- "$info" | sed -nE 's/.*\(([0-9]+) Bytes\).*/\1/p' | head -1)
[[ $disk_bytes == <-> ]] || { print -u2 "Nelze zjistit velikost disku."; exit 1; }
if [[ -n $bytes && $bytes -gt $disk_bytes ]]; then
  print -u2 "Požadovaná velikost je větší než zdrojová karta."
  exit 1
fi

print "Zdroj: $disk ($disk_bytes B)"
print "Obraz: $image${bytes:+ ($bytes B)}"
print -n "Pro pokračování napište CREATE: "
read -r confirmation
[[ $confirmation == CREATE ]] || { print "Zrušeno."; exit 0; }

mkdir -p "${image:h}"
diskutil unmountDisk "$disk"
raw="/dev/r${disk#/dev/}"

if [[ -z $bytes ]]; then
  sudo dd if="$raw" of="$image" bs=4m status=progress
else
  full_blocks=$(( bytes / 1048576 ))
  remainder=$(( bytes % 1048576 ))
  (( full_blocks > 0 )) && sudo dd if="$raw" of="$image" bs=1m count=$full_blocks status=progress
  if (( remainder > 0 )); then
    offset=$(( full_blocks * 1048576 ))
    sudo dd if="$raw" of="$image" bs=1 skip=$offset seek=$offset count=$remainder conv=notrunc status=progress
  fi
fi

sync
shasum -a 256 "$image" >"$image.sha256"
print "Hotovo: $image"
print "Kontrolní součet: $image.sha256"
diskutil eject "$disk"
