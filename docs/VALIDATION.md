# Build validation — 2026-10-29

This records local checks of the initial DinoDev workspace. It is not a device certification or a security audit.

## Environment and inputs

- Host: x86_64 Linux, Debian 12 userland, approximately 3.8 GiB RAM.
- Compiler: Android Clang 12.0.5 / r416183b, exact revision in `kernel.lock.json`.
- Base: MillenniumOSS `millennium-base`, Linux 5.10.264, exact revision in the lock.
- Configuration: ARM64 `gki_defconfig` plus DinoDev's thin-LTO and profile fragments.
- Both profiles built sequentially with `--jobs 2`.

## Results

| Check | Baseline | Experimental KernelSU |
| --- | --- | --- |
| Full ARM64 Image compile/link | Passed | Passed |
| Exact release `5.10.264-DinoDev` | Passed | Passed |
| ARM64 Image header | Passed | Passed |
| AArch64 ELF machine type | Passed | Passed |
| Requested Kconfig values retained | Passed | Passed |
| Selected hardening configuration retained | Passed | Passed |
| KernelSU built-in symbols | Absent, as required | Present |
| Compiled KernelSU manager version | Not applicable | `32680` |
| Collected SHA-256 checks | Passed | Passed |
| Physical phone boot/root test | Not performed | Not performed |

The workspace suite passed **23 tests**, covering lock validation, configuration merging/policy, root-profile isolation, source-tree replacement safety, product architecture/release checks, and KernelSU version/symbol checks. Shell and Python syntax checks also passed.

## Final local Image fingerprints

| Profile | Bytes | SHA-256 |
| --- | ---: | --- |
| `baseline` | 39,326,228 | `dfd142b2398b83fadad1cf6ae6ba037c632352ec5d8cbac1a978852fb10ebce4` |
| `kernelsu` | 39,654,052 | `0bfea5fe482b6489a881a589d29b3bbc58a2a9349ab91caac923164c0b4bb779` |

These fingerprints identify the local validation products, not a promise that every future build on another host is byte-identical. Each collected profile contains its own authoritative `build-manifest.json` and `SHA256SUMS`.

## Not validated

No target phone or ROM has been identified. There is no device-specific boot image, matching vendor-module package, KMI/ABI certification, AVB/signing integration, runtime SELinux validation, suspend/resume test, hardware test, or KernelSU manager authorization test.

KernelSU v3.3.1 built-in/GKI-image mode is unsupported upstream and remains experimental here. **Neither Image is ready to flash.** Follow `DEVICE_PORTING.md` before making a device-specific release.
