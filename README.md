# DinoDev Kernel

A custom Android kernel workspace based on the **MillenniumOSS Android 12 / Linux 5.10 common kernel**, with a clean baseline and an explicit, experimental KernelSU profile.

> **Development stage — not a flashable release.** No phone, codename, ROM, or stock boot image has been supplied. This repository builds an ARM64 development `Image`; it does not manufacture a device-compatible `boot.img`, vendor modules, or a recovery ZIP. Do not rename `Image` to `boot.img` or flash it to a phone.

## What is here

- **Pinned inputs:** upstream kernel, Android Clang, build utilities, KernelSU, and host OpenSSL are locked to exact Git commits in [`kernel.lock.json`](kernel.lock.json).
- **Two profiles:** `baseline` has no KernelSU; `kernelsu` opts into the pinned driver and its required configuration.
- **Isolated builds:** downloaded sources, staged trees, object files, and release artifacts stay outside Git under `.dinodev/` and `artifacts/`.
- **Configuration checks:** builds fail if requested fragment values do not survive Kconfig, KernelSU leaks into the baseline, or selected kernel hardening options are disabled.
- **Build provenance:** each collected Image includes its configuration, System.map, source/toolchain revisions, and SHA-256 checksums.
- **CI:** GitHub Actions runs workspace tests and builds both profiles independently. A passing CI build is not a device boot test.

Both profiles have completed local ARM64 compilation and artifact checks; see [docs/VALIDATION.md](docs/VALIDATION.md). No scheduler, overclock, undervolt, or battery-saving tweaks are claimed. Establishing a trustworthy build comes before performance tuning.

## Quick start

Use an **x86_64 Linux** host. Ubuntu 22.04 is the CI reference. Allow at least 20 GB of free disk space; 8 GB RAM is recommended. Source/toolchain downloads require access to GitHub.

```sh
sudo apt-get update
sudo apt-get install -y git python3 build-essential m4 cpio xz-utils perl libelf-dev file

./build.sh doctor
./build.sh fetch
python3 -m unittest discover -s tests -v

# Clean branded development kernel, without root support:
./build.sh build --profile baseline --jobs 2

# Separate, experimental built-in KernelSU development kernel:
./build.sh build --profile kernelsu --jobs 2
```

The wrapper selects the locked Clang/tool utilities and builds OpenSSL's static **host-only** crypto library for Kbuild helpers. That host library is not a crypto library shipped inside the Android kernel. The first run takes longer than incremental builds.

Results:

```text
artifacts/<profile>/
├── Image
├── System.map
├── .config
├── build-manifest.json
└── SHA256SUMS
```

Verify a collected build:

```sh
cd artifacts/baseline
sha256sum -c SHA256SUMS
file Image
```

Build logs are in `.dinodev/logs/`. `doctor` is informational; `fetch`, `config`, and `build` enforce their prerequisites and pinned revisions.

## Base and compatibility

| Input | Pinned source |
| --- | --- |
| Kernel | `MillenniumOSS/android_kernel_common_android12-5.10`, `millennium-base`, Linux **5.10.264** |
| Compiler | Android Clang **12.0.5 / r416183b**, from the LineageOS prebuilt mirror |
| KernelSU | Official `tiann/KernelSU` **v3.3.1**, experimental built-in integration |

The upstream repository is **archived**. Pinning makes inputs stable; it does not provide future security maintenance. Review upstream advisories and update the lock deliberately before distributing a release.

This is a source-overlay/build workspace, not a full vendored fork of all 70,000+ upstream kernel files. `fetch` obtains the exact base; `prepare` creates a separate source tree and applies DinoDev's small integration. This keeps the repository reviewable and avoids committing downloaded toolchains or build output.

The build invokes Kbuild directly rather than Android's complete `build.sh`/manifest workflow. **KMI/ABI certification, vendor-module compatibility, module packaging, boot-image packaging, AVB handling, and physical-device tests are not implemented.** The branded kernel release and thin-LTO development configuration are not a drop-in replacement for a stock vendor kernel.

## KernelSU status

KernelSU 3.x officially recommends its loadable-kernel-module distribution and no longer supports its former GKI image mode. DinoDev's built-in v3.3.1 variant is therefore **experimental**, even if it compiles. A successful build does not establish that manager authorization, SELinux interactions, syscall hooks, suspend/resume, or boot work on a particular phone.

Root support increases the device's attack surface. The baseline remains root-free. See [docs/KERNELSU.md](docs/KERNELSU.md) before proceeding, and use only an official, version-compatible KernelSU manager.

## Making it yours

- Branding and common development settings: `config/common.config`.
- Optional root configuration: `config/kernelsu.config`.
- Source integration and build policy: `scripts/dinodev.py`.
- Dependency updates: review and update full commit SHAs in `kernel.lock.json`, then fetch, test, build, and device-test again.

After changing locked sources or build orchestration, recreate the affected staged tree with `./build.sh prepare --profile <profile> --force`. This replaces only DinoDev's marked generated source directory, not your checkout under `.dinodev/downloads/`. Configuration-only changes are handled by `build`.

Do not edit `.dinodev/sources/` as the permanent home for a feature: those trees are generated. Keep reviewed changes in this workspace and add tests appropriate to the feature.

## Next: identify the actual phone

Before any device-specific build, provide the **exact model and codename**, installed ROM/build, Android version, and `uname -r` output. The matching stock boot image and kernel/vendor-module sources are also needed. Follow [docs/DEVICE_PORTING.md](docs/DEVICE_PORTING.md).

There are deliberately no flashing commands or bootloader-unlock/verified-boot bypass instructions here. Those steps depend on the device and must preserve a tested recovery path.

More detail: [building](docs/BUILDING.md) · [KernelSU](docs/KERNELSU.md) · [device porting](docs/DEVICE_PORTING.md) · [third-party notices](THIRD_PARTY_NOTICES.md).

Workspace orchestration is GPL-2.0-only; upstream components retain their own licenses.
