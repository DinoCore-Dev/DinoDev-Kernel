# Building DinoDev

## Scope

The supported output at this stage is an **ARM64 development Image**, not a bootable phone image. There is no device profile yet. Both variants use the same pinned Linux 5.10.264 base and Android Clang r416183b.

- `baseline`: DinoDev branding and a thin-LTO development configuration; no KernelSU driver.
- `kernelsu`: the same base plus an explicitly pinned, experimental built-in KernelSU driver.

## Host requirements

The pinned compiler and utility binaries target x86_64 Linux. The CI reference is Ubuntu 22.04. A Linux ARM host or macOS cannot run these particular prebuilts natively; use a Linux x86_64 machine or CI instead. Emulation is not a supported build path.

```sh
sudo apt-get update
sudo apt-get install -y git python3 build-essential m4 cpio xz-utils perl libelf-dev file
```

Python 3.10+ is recommended; CI uses the system Python on Ubuntu 22.04. No Python packages are required for the workspace tests. GNU make, a host C compiler, GNU tar, Perl, and `/usr/bin/m4` are needed. The AOSP Bison prebuilt expects m4 at that absolute path.

The wrapper supplies locked Clang, LLD, LLVM utilities, Flex, Bison, bc, and a Toybox cpio wrapper. A host cpio is still useful for diagnostics. Host OpenSSL is built from the locked source as a static development dependency when needed.

Allow at least 20 GB free disk for downloads, two staged source trees, and build products. 8 GB RAM is a practical target; `--jobs 2` is a conservative choice on smaller machines. Thin LTO still needs substantial memory during linking. Do not run two full kernel links concurrently on a 4 GB host.

## Commands

```sh
./build.sh doctor                         # Inspect host and source state
./build.sh fetch                          # All locked inputs
./build.sh fetch --component kernel       # One input
./build.sh prepare --profile baseline     # Isolate upstream source
./build.sh config --profile baseline      # Resolve and validate configuration
./build.sh build --profile baseline --jobs 2
./build.sh build --profile kernelsu --jobs 2
```

`build` prepares missing inputs' source trees and configures when necessary, but it **does not download missing repositories automatically**. Run `fetch` first. Existing exact, clean checkouts are reused; an unexpected revision or dirty source checkout is an error, not an invitation to overwrite local work.

Generated paths:

```text
.dinodev/downloads/    # Exact Git checkouts and host-tool sources
.dinodev/sources/      # Disposable profile-specific source trees
.dinodev/output/       # Kbuild O= directories
.dinodev/host-crypto/  # Static host OpenSSL headers/library
.dinodev/logs/         # Last operation's logs
artifacts/<profile>/  # Collected Image, config, map, manifest, checksums
```

All are ignored by Git. Do not commit private signing keys, stock firmware, or downloaded binary toolchains.

## Configuration policy

The starting point is upstream `arch/arm64/configs/gki_defconfig`. DinoDev applies:

1. `config/common.config`: `-DinoDev` local version and thin rather than full LTO.
2. The selected profile fragment.
3. `olddefconfig` to resolve dependencies.
4. Exact checks for every requested fragment setting and selected security invariants.

CFI, shadow call stacks, SELinux support, and strict kernel/module RWX must remain enabled. This is a **configuration check**, not proof that the resulting kernel is secure or that SELinux is enforcing at runtime. Kernel root support itself changes the security model.

KernelSU is built in only in its profile. Debug root mode is rejected. A missing or silently demoted KernelSU setting fails configuration rather than producing a misleading root-enabled artifact.

Before collection, DinoDev also checks the ARM64 Image header, exact `5.10.264-DinoDev` release, presence of KernelSU symbols and its expected compiled version in the root profile, and absence of those symbols in the baseline. An explicit empty `LOCALVERSION=` prevents the surrounding workspace's Git state from adding a stray `+` to the release. These are build checks, not runtime or device-compatibility tests.

The configuration marker records both fragment contents and the resolved `.config` hash. If either changes, `build` regenerates the configuration. After changing locks or orchestration, explicitly run:

```sh
./build.sh prepare --profile baseline --force
./build.sh prepare --profile kernelsu --force
```

The force operation only replaces a generated tree carrying DinoDev's ownership marker. It does not reset downloaded checkouts. Object directories are separate from source trees.

## Reproducibility and limitations

Exact commits, fixed build labels, normalized build time, and published checksums make builds traceable. They are **not a claim of bit-for-bit reproducibility across arbitrary host distributions**. Host compilers, filesystems, and installed utilities can still affect output. Compare builds on the same reference host if byte reproducibility is required.

The kernel is built directly with Kbuild. This workspace does not run Android's full hermetic manifest build or KMI enforcement. It does not build/collect a matching vendor-module set or validate an ABI surface. `build-manifest.json` explicitly reports these limitations.

`Image` contains a kernel, not the complete Android boot partition. It lacks the device's boot header, ramdisk, command line, DTB placement, signature layout, and other packaging requirements. Renaming it cannot supply those fields.

## CI

`.github/workflows/build.yml` runs on relevant pushes, pull requests, and manual dispatch. It runs unit tests, fetches pinned sources, builds each profile in a separate job, verifies checksums, and uploads logs/artifacts. The KernelSU job is labeled experimental by its profile; neither job's artifact is a flashable boot image.

The workflow pins third-party actions by commit and grants read-only repository permissions. It does not sign releases, unlock bootloaders, or publish a GitHub Release automatically.

## Troubleshooting

- **Missing checkout / wrong revision:** run `doctor`, then `fetch`. Do not silently replace a checkout containing your work.
- **Stale staged source:** run `prepare --profile <name> --force` after reviewing the changed lock/orchestration.
- **m4 or parser generation failure:** install the host `m4` package; check `/usr/bin/m4`.
- **Out of memory / killed link:** lower `--jobs`, close other applications, and build one profile at a time. Do not disable CFI merely to make a small host link succeed.
- **Configuration policy failure:** inspect `.dinodev/logs/<profile>-olddefconfig.log` and the relevant Kconfig dependencies. Do not remove the check to hide a missing feature.
- **KernelSU compile failure:** keep the baseline separate. Record the first compiler error and review version compatibility; do not label the artifact root-enabled.
- **Everything compiles but the phone is untested:** expected at this stage. Complete device porting and recovery planning before attempting a device boot.
