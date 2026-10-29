# Device porting checklist

**Status: blocked on device identification.** “My phone” is not enough to select a safe kernel configuration or boot-image layout. The current ARM64 Image is a development artifact only.

## Information to collect

Please provide:

- Manufacturer, full marketing name, model number, and device codename.
- SoC, if known.
- Stock ROM or custom ROM name, exact build number, Android version, and security patch level.
- Output of `uname -r` and `uname -a` from the installed system.
- Whether the bootloader is already unlocked. Do not unlock or erase data just to answer this.
- The exact matching stock boot image, plus vendor-boot/init-boot/DTB/VBMeta images where the device uses them.
- Matching kernel source, vendor-module source, device defconfig, and build instructions/manifest.
- Current root solution, if any, and whether preserving user data is required.

From an authorized ADB shell, these are read-only identification commands:

```sh
adb shell getprop ro.product.model
adb shell getprop ro.product.device
adb shell getprop ro.build.fingerprint
adb shell getprop ro.build.version.release
adb shell getprop ro.boot.slot_suffix
adb shell uname -a
```

Property names and availability vary by device. An ADB shell does not establish bootloader unlock state or prove GKI compatibility. Share text output, not serial numbers, IMEI, accounts, or other personal identifiers.

## Why the common kernel is insufficient

Android common source does not contain every phone's board configuration, display/touch drivers, camera stack, modem integration, device tree, vendor modules, or boot packaging metadata. Two phones using Linux 5.10 can require incompatible kernels and module ABIs.

The Linux version alone is not a KMI match. The full Android kernel release, vendor symbol requirements, compiler configuration, module layout, and device firmware must agree. DinoDev's custom local version and development LTO choice are additional reasons not to treat its Image as a stock drop-in replacement.

## Porting sequence

1. **Identify and preserve:** record the exact installed build and obtain matching factory images. Verify checksums against the manufacturer's published values where available.
2. **Reproduce stock:** build the manufacturer's/device maintainer's kernel with its own config and toolchain. Compare release string, configuration, module ABI, and packaging with the installed build.
3. **Boot the baseline:** validate the untouched device-specific build before adding DinoDev branding or KernelSU. Keep a device-specific tested recovery path.
4. **Add minimal changes:** port branding/build infrastructure first. Add root support separately so a failure can be attributed.
5. **Package correctly:** use the device's supported image tools and measured header/page-size/address/ramdisk/compression parameters. Handle boot, vendor-boot, init-boot, DTB, and AVB according to that device—not a generic tutorial.
6. **Validate:** test cold boot, reboot, slots/OTA behavior, suspend/resume, charging/thermals, touch/display, Wi-Fi/Bluetooth/cellular, audio/cameras, USB, storage encryption, and root authorization as applicable.
7. **Release:** publish exact source revisions, config, toolchain details, checksums, supported ROM/build matrix, known limitations, and recovery instructions. Do not call a build stable based only on compilation.

## Recovery and data safety

Bootloader unlocking commonly erases user data. Flashing an incompatible kernel can cause a bootloop, loss of touch/network/storage access, or a device that needs manufacturer recovery tools. Back up user data independently and confirm that the exact stock images can be restored.

Do not assume `fastboot boot` is supported, that every phone has A/B slots, or that the active slot is a safe fallback. Do not flash both slots experimentally. Do not disable AVB/dm-verity or sign with public test keys as a shortcut.

This repository intentionally contains no automatic flashing, unlock, wipe, or verified-boot bypass command. Device-specific instructions should be reviewed only after the model and firmware are known.
