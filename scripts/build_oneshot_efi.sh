#!/bin/sh
# Builds iso/out/bd-oneshot-x64.efi: a standalone GRUB EFI binary that boots the
# forensics ISO's kernel from the CD (label BDFORENSICS) at once - no menu, no
# timeout. scripts/s5_twin.py copies it over the restored clone's UEFI loaders
# (the ESP swap), because Vultr boots the restored disk ahead of the ISO and the
# clone's own GRUB menu never auto-boots (S5 runs 8-10). Verified locally:
# evals/results/local-e2e/kvm-uefi-esp-grub/. Needs grub-efi-amd64-bin.
#   wsl -d Ubuntu-24.04 -u root sh scripts/build_oneshot_efi.sh
set -eu
# run from the repo root
cfg=$(mktemp)
cat > "$cfg" <<'CFG'
search --no-floppy --set=root --label BDFORENSICS
linux /boot/vmlinuz-lts console=ttyS0,115200 console=tty0
initrd /boot/initramfs-bd
boot
CFG
mkdir -p iso/out
grub-mkstandalone -O x86_64-efi -o iso/out/bd-oneshot-x64.efi \
    --install-modules="linux search search_label iso9660 part_gpt part_msdos normal configfile boot echo" \
    "boot/grub/grub.cfg=$cfg"
rm -f "$cfg"
ls -l iso/out/bd-oneshot-x64.efi
