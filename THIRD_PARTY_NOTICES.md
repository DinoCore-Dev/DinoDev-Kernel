# Third-party notices

DinoDev downloads dependencies instead of vendoring their complete trees. Exact repositories, refs, and commits are recorded in `kernel.lock.json`. Downloaded components retain their own copyright and license notices; inclusion in a build does not relicense them.

| Component | Use | License information |
| --- | --- | --- |
| MillenniumOSS Android 12 5.10 common kernel | Kernel base | Linux kernel notices: `COPYING`, `LICENSES/`, and per-file SPDX identifiers; GPL-2.0 with syscall exception where stated, plus other applicable upstream licenses |
| LineageOS Android Clang r416183b mirror | Compiler/LLVM toolchain | Upstream LLVM/Android notices and bundled third-party licenses in the checkout |
| LineageOS Android build-tools | Flex, Bison, m4, bc, Toybox, and related utilities | Per-tool notices in `common/`, `linux-x86/`, and upstream metadata; multiple licenses apply |
| tiann/KernelSU v3.3.1 | Optional experimental root driver | Repository `LICENSE` is copied into the staged driver as `LICENSE.KernelSU`; kernel source files also carry their own SPDX notices (including GPL-2.0-only). Preserve all applicable notices |
| OpenSSL 3.5.6 | Host-only Kbuild helper library | Apache-2.0 for this release, with upstream copyright/notice files; not packaged as an Android target library |
| GitHub Actions checkout/upload-artifact | CI | Their respective upstream MIT licenses; action refs are commit-pinned in the workflow |

The KernelSU repository contains more than its kernel driver. Only `kernel/` and the repository license are copied into the experimental staged kernel tree. No manager APK or userspace daemon is bundled by this workspace.

DinoDev's own orchestration, tests, configuration fragments, and documentation are provided under GPL-2.0-only unless a file states otherwise. See `LICENSE`.

Before distributing binaries, review the actual locked sources and satisfy all applicable source-offer, attribution, and notice obligations. This table is a guide, not a substitute for that review.
