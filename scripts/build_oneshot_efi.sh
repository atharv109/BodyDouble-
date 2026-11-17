#!/bin/sh
# Builds the ESP-swap payload in iso/out/ (run from the repo root, as root in WSL):
#   bd-oneshot-x64.efi       standalone GRUB EFI binary, config embedded (memdisk)
#   bd-oneshot/vmlinuz-lts   the ISO's own kernel and initramfs, extracted from
#   bd-oneshot/initramfs-bd  iso/out/bodydouble-forensics.iso
# scripts/s5_twin.py copies them onto the restored clone's ESP and the binary over
# its UEFI loaders, because Vultr boots the restored disk ahead of the ISO and the
# clone's own GRUB menu never auto-boots (S5 runs 8-10).
# The kernel lives on the ESP, not the CD: Vultr's UEFI firmware does not expose
# the SATA CD (no DVD-ROM boot option in run11/esp-swap.txt), so GRUB dropped to
# 'grub>' when it searched for the CD label (run11/checkpoints/console-2-take1.png).
# Once the kernel runs, the initramfs finds the CD with its own drivers.
#   wsl -d Ubuntu-24.04 -u root sh scripts/build_oneshot_efi.sh
# Needs grub-efi-amd64-bin and xorriso.
set -eu
out=iso/out
mkdir -p "$out/bd-oneshot"
for f in vmlinuz-lts initramfs-bd; do
    rm -f "$out/bd-oneshot/$f"
    xorriso -osirrox on -indev "$out/bodydouble-forensics.iso" \
        -extract "/boot/$f" "$out/bd-oneshot/$f" 2>/dev/null
done
cfg=$(mktemp)
cat > "$cfg" <<'CFG'
# --install-modules does not autoload partition/filesystem drivers (local test:
# root stayed memdisk), so load them explicitly
insmod part_gpt
insmod part_msdos
insmod fat
insmod search_fs_file
echo "bd-oneshot: searching the ESP for /bd/vmlinuz-lts"
search --no-floppy --set=root --file /bd/vmlinuz-lts
echo "bd-oneshot: root=$root; loading the forensics ISO kernel"
linux /bd/vmlinuz-lts console=ttyS0,115200 console=tty0
initrd /bd/initramfs-bd
boot
echo "bd-oneshot: boot failed"
sleep 600
CFG
grub-mkstandalone -O x86_64-efi -o "$out/bd-oneshot-x64.efi" \
    --install-modules="linux search search_fs_file fat part_gpt part_msdos normal echo sleep boot" \
    "boot/grub/grub.cfg=$cfg"
rm -f "$cfg"
sha256sum "$out/bd-oneshot-x64.efi" "$out/bd-oneshot/vmlinuz-lts" "$out/bd-oneshot/initramfs-bd"
