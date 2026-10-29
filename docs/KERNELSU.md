# KernelSU integration policy

## Current status

DinoDev pins official KernelSU **v3.3.1** to commit `0c0fdb960178fa12d80d6cbcfdcb6ad8be6a865d`. The `kernelsu` profile copies its `kernel/` directory into an isolated kernel tree, adds Kconfig/Kbuild references, and enables `CONFIG_KSU=y`. The clean profile contains neither the driver nor its configuration.

This is an **experimental built-in integration**. KernelSU's current documentation says:

- Since v1.0, non-GKI kernels are no longer officially supported; its archival non-GKI instructions reference v0.9.5.
- Since v3.0, the former built-in/GKI image mode is no longer supported; LKM distribution is recommended.

References at the pinned revision:

- [Build instructions and image-mode notice](https://github.com/tiann/KernelSU/blob/0c0fdb960178fa12d80d6cbcfdcb6ad8be6a865d/website/docs/guide/how-to-build.md)
- [Archival non-GKI instructions](https://github.com/tiann/KernelSU/blob/0c0fdb960178fa12d80d6cbcfdcb6ad8be6a865d/website/docs/guide/how-to-integrate-for-non-gki.md)
- [Installation and KMI discussion](https://github.com/tiann/KernelSU/blob/0c0fdb960178fa12d80d6cbcfdcb6ad8be6a865d/website/docs/guide/installation.md)

We do not silently substitute the old v0.9.5 release or run an upstream setup script that follows a moving branch. Nor do we claim that a modern manager is compatible with an old driver. A future device decision may select the official LKM route instead; that would be a separate, explicitly tested integration.

## Why compile it at all?

The separate profile provides a reviewable, pinned basis for evaluating built-in source compatibility with this particular Android 12 common kernel. Compilation can catch API mismatches. It cannot validate runtime privilege authorization, syscall hooks, kernel memory patching, SELinux policy interactions, or phone boot behavior.

The source is built with its official manager package/signature defaults. DinoDev does not weaken signature checks, grant every app root, enable debug root, or set SELinux permissive. Root is a deliberate security tradeoff even when those checks remain intact.

## Required before device use

1. Identify exact hardware, codename, ROM/build, kernel release/KMI, and boot-image format.
2. Establish that the unmodified device-specific kernel builds and boots.
3. Decide between a maintained device-specific KernelSU/LKM path and this experimental source integration. Do not assume either is compatible.
4. Validate the matching kernel and vendor modules together, including Wi-Fi, touch, display, charging, cameras, audio, suspend/resume, and reboot.
5. Test manager authentication and default-deny behavior for unapproved apps with a version-compatible official manager.
6. Verify runtime SELinux state and review root-induced policy changes.
7. Preserve the exact stock boot/vendor-boot/init-boot images as appropriate and test recovery on that device.
8. Test updates and rollback. Root support must not depend on disabling verified boot or signature verification.

No manager APK is downloaded or installed by this workspace. Obtain it from the official [KernelSU releases](https://github.com/tiann/KernelSU/releases), matching the chosen driver's version. Do not install unofficial APKs merely because their package name matches.

## Updating the pin

Review the upstream release, security policy, kernel API requirements, manager signature defaults, and license. Update the full commit, human-readable ref, and expected version metadata together in `kernel.lock.json`. Recreate the KernelSU staged tree, run tests, compile both profiles, and repeat device tests. Never point the build at `main` for a release.
