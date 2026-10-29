#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Pinned, out-of-tree build orchestration for the DinoDev kernel workspace."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".dinodev"
DOWNLOADS = WORK / "downloads"
PROFILES = ("baseline", "kernelsu")
COMPONENTS = ("kernel", "toolchain", "build_tools", "kernelsu", "host_crypto")
CONFIG_LINE = re.compile(r"^(?:CONFIG_([A-Za-z0-9_]+)=(.*)|# CONFIG_([A-Za-z0-9_]+) is not set)$")
SECURITY_SYMBOLS = (
    "CONFIG_CFI_CLANG",
    "CONFIG_SHADOW_CALL_STACK",
    "CONFIG_SECURITY_SELINUX",
    "CONFIG_STRICT_KERNEL_RWX",
    "CONFIG_STRICT_MODULE_RWX",
)


class DinoError(RuntimeError):
    """An actionable build error, without an internal traceback."""


def load_lock(path: Path = ROOT / "kernel.lock.json") -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate lock key: {key}")
            result[key] = value
        return result

    lock = json.loads(path.read_text(), object_pairs_hook=unique)
    if lock.get("schema_version") != 1:
        raise DinoError("Unsupported kernel.lock.json schema")
    for name in COMPONENTS:
        item = lock.get(name, {})
        if not re.fullmatch(r"[0-9a-f]{40}", item.get("commit", "")):
            raise DinoError(f"{name}: a full lowercase commit SHA is required")
        if not item.get("repository", "").startswith("https://github.com/"):
            raise DinoError(f"{name}: only HTTPS GitHub sources are supported")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", item.get("directory", "")):
            raise DinoError(f"{name}: invalid checkout directory")
    if len({lock[n]["directory"] for n in COMPONENTS}) != len(COMPONENTS):
        raise DinoError("Lock checkout directories must be unique")
    ksu = lock["kernelsu"]
    if (not isinstance(ksu.get("git_commit_count"), int) or ksu["git_commit_count"] < 1
            or ksu.get("manager_version") != 30000 + ksu["git_commit_count"]):
        raise DinoError("KernelSU version must equal 30000 + the pinned commit count")
    return lock


def run(args: list[str], *, cwd: Path = ROOT, env: dict | None = None,
        log: Path | None = None, capture: bool = False) -> str:
    printable = " ".join(str(a) for a in args)
    print(f"+ {printable}", flush=True)
    if log:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w") as stream:
            stream.write(f"+ {printable}\n")
            stream.flush()
            proc = subprocess.Popen(args, cwd=cwd, env=env, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            assert proc.stdout is not None
            for line in proc.stdout:
                stream.write(line)
                stream.flush()
                sys.stdout.write(line)
                sys.stdout.flush()
            code = proc.wait()
        if code:
            raise DinoError(f"Command exited {code}; see {log.relative_to(ROOT)}")
        return ""
    result = subprocess.run(args, cwd=cwd, env=env, text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None)
    if result.returncode:
        detail = (result.stderr or "") if capture else ""
        raise DinoError(f"Command exited {result.returncode}: {printable}\n{detail}")
    return result.stdout.strip() if capture else ""


def git(repo: Path, *args: str, capture: bool = True) -> str:
    return run(["git", "-C", str(repo), *args], capture=capture)


def checkout(lock: dict, name: str) -> Path:
    return DOWNLOADS / lock[name]["directory"]


def verify_checkout(repo: Path, commit: str) -> None:
    if not (repo / ".git").exists():
        raise DinoError(f"Missing checkout: {repo}; run ./build.sh fetch")
    if git(repo, "rev-parse", "HEAD") != commit:
        raise DinoError(f"{repo.name}: expected {commit}, found a different revision")
    if git(repo, "status", "--porcelain", "--untracked-files=all"):
        raise DinoError(f"{repo.name}: checkout is dirty; refusing to overwrite it")


def fetch_component(lock: dict, name: str) -> None:
    item = lock[name]
    repo, commit = checkout(lock, name), item["commit"]
    if (repo / ".git").exists():
        verify_checkout(repo, commit)
        print(f"{name}: pinned checkout already present")
        return
    if repo.exists():
        raise DinoError(f"Refusing to replace non-Git directory: {repo}")
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    args = ["git", "clone", "--depth=1", "--single-branch", "--branch", item["ref"]]
    if item.get("sparse_paths"):
        args.append("--sparse")
    args += [item["repository"], str(repo)]
    run(args)
    if item.get("sparse_paths"):
        git(repo, "sparse-checkout", "set", *item["sparse_paths"], capture=False)
    if git(repo, "rev-parse", "HEAD") != commit:
        # A moved upstream branch is never silently accepted. Fetch the exact lock.
        git(repo, "fetch", "--depth=1", "origin", commit, capture=False)
        if git(repo, "rev-parse", "FETCH_HEAD") != commit:
            raise DinoError(f"{name}: fetched revision does not match lock")
        git(repo, "-c", "advice.detachedHead=false", "checkout", "--detach", commit,
            capture=False)
    verify_checkout(repo, commit)


def parse_config(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        match = CONFIG_LINE.match(line)
        if match:
            key = match.group(1) or match.group(3)
            values[f"CONFIG_{key}"] = match.group(2) if match.group(1) else "n"
    return values


def merge_fragment(base: str, fragment: str) -> str:
    requested = parse_config(fragment)
    lines = []
    for line in base.splitlines():
        match = CONFIG_LINE.match(line)
        key = "CONFIG_" + (match.group(1) or match.group(3)) if match else None
        if key not in requested:
            lines.append(line)
    return "\n".join(lines) + "\n" + fragment.rstrip() + "\n"


def validate_config(text: str, profile: str) -> None:
    values = parse_config(text)
    required = {s: "y" for s in SECURITY_SYMBOLS}
    required.update({
        "CONFIG_ARM64": "y",
        "CONFIG_LTO_CLANG_THIN": "y",
        "CONFIG_LOCALVERSION": '"-DinoDev"',
    })
    if profile == "kernelsu":
        required.update({"CONFIG_KSU": "y", "CONFIG_KPROBES": "y",
                         "CONFIG_HAVE_SYSCALL_TRACEPOINTS": "y",
                         "CONFIG_OVERLAY_FS": "y", "CONFIG_EXT4_FS": "y"})
    else:
        required["CONFIG_KSU"] = "n"
    errors = [f"{key}: expected {want}, got {values.get(key, 'n')}"
              for key, want in required.items() if values.get(key, "n") != want]
    if values.get("CONFIG_KSU_DEBUG", "n") != "n":
        errors.append("KernelSU debug mode must not be enabled")
    if errors:
        raise DinoError("Configuration policy failed:\n" + "\n".join(errors))


def source_dir(profile: str) -> Path:
    return WORK / "sources" / profile


def output_dir(profile: str) -> Path:
    return WORK / "output" / profile


def artifact_dir(profile: str) -> Path:
    return ROOT / "artifacts" / profile


def fingerprint(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(ROOT)).encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def source_fingerprint(lock: dict, profile: str) -> str:
    paths = [ROOT / "kernel.lock.json", ROOT / "scripts/dinodev.py",
             ROOT / "config/common.config", ROOT / f"config/{profile}.config"]
    return fingerprint(paths)


def integrate_kernelsu(tree: Path, ksu: Path, version: int) -> None:
    """Copy the pinned driver and add exactly one Kbuild/Kconfig reference."""
    driver = tree / "drivers/kernelsu"
    makefile, kconfig = tree / "drivers/Makefile", tree / "drivers/Kconfig"
    obj = "obj-$(CONFIG_KSU) += kernelsu/"
    source = 'source "drivers/kernelsu/Kconfig"'
    if driver.exists() or obj in makefile.read_text() or source in kconfig.read_text():
        raise DinoError("KernelSU integration already exists; use a clean staged tree")
    shutil.copytree(ksu / "kernel", driver)
    shutil.copy2(ksu / "LICENSE", driver / "LICENSE.KernelSU")
    (driver / "DINODEV_PROVENANCE").write_text(
        f"Source: https://github.com/tiann/KernelSU\n"
        f"Ref: v3.3.1\nCommit: {git(ksu, 'rev-parse', 'HEAD')}\n"
        "Only kernel/ is integrated. See LICENSE.KernelSU and per-file SPDX notices.\n"
        "Experimental built-in mode; not an upstream-supported GKI image.\n")
    with makefile.open("a") as stream:
        stream.write(f"\n# DinoDev: opt-in KernelSU\n{obj}\n")
    text = kconfig.read_text()
    pos = text.rfind("endmenu")
    if pos < 0:
        raise DinoError("drivers/Kconfig has no endmenu insertion point")
    kconfig.write_text(text[:pos] + f"\n# DinoDev: opt-in KernelSU\n{source}\n\n" + text[pos:])
    if not isinstance(version, int) or not 30000 < version < 100000:
        raise DinoError("Invalid pinned KernelSU version")


def prepare(lock: dict, profile: str, force: bool = False) -> None:
    verify_checkout(checkout(lock, "kernel"), lock["kernel"]["commit"])
    if profile == "kernelsu":
        verify_checkout(checkout(lock, "kernelsu"), lock["kernelsu"]["commit"])
    tree = source_dir(profile)
    marker = tree / ".dinodev-source.json"
    expected = {"profile": profile, "kernel": lock["kernel"]["commit"],
                "fingerprint": source_fingerprint(lock, profile)}
    if tree.exists():
        if not marker.is_file():
            raise DinoError(f"Unrecognized source directory: {tree}; not deleting it")
        actual = json.loads(marker.read_text())
        if actual == expected and (tree / "Makefile").is_file():
            print(f"{profile}: staged source already matches the lock")
            return
        if not force:
            raise DinoError("Staged source is stale; run prepare --force for this profile")
        # Only a directory carrying our ownership marker can be replaced.
        shutil.rmtree(tree)
    tree.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{profile}-", dir=tree.parent) as tmp:
        staging = Path(tmp) / "kernel"
        staging.mkdir()
        archive = Path(tmp) / "source.tar"
        with archive.open("wb") as stream:
            result = subprocess.run(["git", "-C", str(checkout(lock, "kernel")),
                                     "archive", "--format=tar", lock["kernel"]["commit"]],
                                    stdout=stream, stderr=subprocess.PIPE)
            if result.returncode:
                raise DinoError(result.stderr.decode(errors="replace"))
        run(["tar", "-xf", str(archive), "-C", str(staging), "--no-same-owner"])
        if profile == "kernelsu":
            integrate_kernelsu(staging, checkout(lock, "kernelsu"), lock["kernelsu"]["manager_version"])
        (staging / ".dinodev-source.json").write_text(json.dumps(expected, indent=2) + "\n")
        os.replace(staging, tree)
    print(f"Prepared {tree.relative_to(ROOT)}")


def host_crypto(lock: dict) -> Path:
    prefix = WORK / "host-crypto"
    marker = prefix / ".dinodev-commit"
    if marker.is_file() and marker.read_text().strip() == lock["host_crypto"]["commit"]:
        if (prefix / "lib/libcrypto.a").is_file() and (prefix / "include/openssl/evp.h").is_file():
            return prefix
    repo = checkout(lock, "host_crypto")
    verify_checkout(repo, lock["host_crypto"]["commit"])
    if not (repo / "Configure").is_file():
        raise DinoError("Host crypto source missing; run ./build.sh fetch")
    # Generated files are ignored by OpenSSL. Do not reset a user's source edits.
    env = os.environ.copy()
    env.update({"LC_ALL": "C", "TZ": "UTC"})
    run(["./Configure", "linux-x86_64", "no-shared", "no-module", "no-apps",
         "no-docs", "no-tests", "--libdir=lib", f"--prefix={prefix}"], cwd=repo, env=env,
        log=WORK / "logs/openssl-configure.log")
    run(["make", "-j2", "build_sw"], cwd=repo, env=env,
        log=WORK / "logs/openssl-build.log")
    run(["make", "install_dev"], cwd=repo, env=env,
        log=WORK / "logs/openssl-install.log")
    marker.write_text(lock["host_crypto"]["commit"] + "\n")
    return prefix


def build_env(lock: dict, profile: str) -> dict:
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise DinoError("The pinned prebuilts require an x86_64 Linux build host")
    for name in ("toolchain", "build_tools"):
        verify_checkout(checkout(lock, name), lock[name]["commit"])
    clang = checkout(lock, "toolchain") / "bin"
    tools = checkout(lock, "build_tools") / "linux-x86/bin"
    for executable in (clang / "clang", clang / "ld.lld", tools / "flex", tools / "bison"):
        if not os.access(executable, os.X_OK):
            raise DinoError(f"Missing build executable: {executable}")
    wrappers = WORK / "bin"
    wrappers.mkdir(parents=True, exist_ok=True)
    for name, target in (("bc", tools / "gavinhoward-bc"),
                         ("cpio", tools / "toybox")):
        wrapper = wrappers / name
        if wrapper.is_symlink():
            if wrapper.resolve() != target.resolve():
                raise DinoError(f"Unexpected generated wrapper: {wrapper}")
        elif wrapper.exists():
            raise DinoError(f"Refusing to replace existing wrapper: {wrapper}")
        else:
            wrapper.symlink_to(target)
    # AOSP's prebuilt bison invokes this absolute path, not PATH.
    if not os.access("/usr/bin/m4", os.X_OK):
        raise DinoError("Install host m4 at /usr/bin/m4 (Debian/Ubuntu: apt install m4)")
    prefix = host_crypto(lock)
    epoch = int(git(checkout(lock, "kernel"), "show", "-s", "--format=%ct",
                    lock["kernel"]["commit"]))
    stamp = datetime.fromtimestamp(epoch, timezone.utc).strftime("%a %b %d %H:%M:%S UTC %Y")
    env = os.environ.copy()
    for key in ("ARCH", "LLVM", "LLVM_IAS", "CROSS_COMPILE", "KCFLAGS",
                "KBUILD_BUILD_TIMESTAMP", "KBUILD_BUILD_USER", "KBUILD_BUILD_HOST",
                "HOSTCFLAGS", "HOSTLDFLAGS", "KCONFIG_CONFIG"):
        env.pop(key, None)
    env.update({
        "PATH": f"{clang}:{tools}:{wrappers}:{env.get('PATH', '')}",
        "LC_ALL": "C", "TZ": "UTC", "SOURCE_DATE_EPOCH": str(epoch),
        "HOSTCFLAGS": f"-I{prefix / 'include'}",
        "HOSTLDFLAGS": f"-L{prefix / 'lib'}",
        # These are build metadata, not the kernel's security configuration.
        "KBUILD_BUILD_USER": "DinoDev", "KBUILD_BUILD_HOST": "DinoDev",
        "KBUILD_BUILD_TIMESTAMP": stamp,
    })
    return env


def make_args(profile: str) -> list[str]:
    return ["ARCH=arm64", "LLVM=1", "LLVM_IAS=1", "CROSS_COMPILE=aarch64-linux-gnu-",
            f"O={output_dir(profile)}", "KCFLAGS=-D__ANDROID_COMMON_KERNEL__",
            "LOCALVERSION="]


def configure(lock: dict, profile: str) -> None:
    tree, out = source_dir(profile), output_dir(profile)
    if not (tree / ".dinodev-source.json").is_file():
        raise DinoError("Source is not prepared; run ./build.sh prepare")
    out.mkdir(parents=True, exist_ok=True)
    env = build_env(lock, profile)
    make = shutil.which("make")
    if not make:
        raise DinoError("GNU make is required")
    args = [make, "-C", str(tree), *make_args(profile)]
    run([*args, "gki_defconfig"], env=env, log=WORK / f"logs/{profile}-defconfig.log")
    config = out / ".config"
    merged = config.read_text()
    fragments = [ROOT / "config/common.config", ROOT / f"config/{profile}.config"]
    for fragment in fragments:
        merged = merge_fragment(merged, fragment.read_text())
    (out / ".config.merged").write_text(merged)
    os.replace(out / ".config.merged", config)
    run([*args, "olddefconfig"], env=env, log=WORK / f"logs/{profile}-olddefconfig.log")
    resolved = config.read_text()
    validate_config(resolved, profile)
    for fragment in fragments:
        for key, want in parse_config(fragment.read_text()).items():
            actual = parse_config(resolved).get(key, "n")
            if actual != want:
                raise DinoError(f"Fragment did not apply: {key}={want}, resolved to {actual}")
    # Record only after Kconfig and policy checks succeed.
    (out / ".dinodev-config.sha256").write_text(
        fingerprint(fragments) + " " + sha256(config) + "\n")
    print(f"{profile}: configuration and security-policy checks passed")


def default_jobs() -> int:
    try:
        memory = int(re.search(r"MemTotal:\s+(\d+)", Path("/proc/meminfo").read_text()).group(1))
        memory_jobs = max(1, memory // (1536 * 1024))
    except (OSError, AttributeError, ValueError):
        memory_jobs = 2
    return max(1, min(os.cpu_count() or 1, memory_jobs, 4))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_outputs(lock: dict, profile: str, out: Path) -> str:
    """Check the actual products, not just the requested configuration."""
    release = (out / "include/config/kernel.release").read_text().strip()
    expected = lock["kernel"]["version"] + "-DinoDev"
    if release != expected:
        raise DinoError(f"Unexpected kernel release: {release!r}; expected {expected!r}")
    image = out / "arch/arm64/boot/Image"
    with image.open("rb") as stream:
        header = stream.read(64)
    if len(header) != 64 or int.from_bytes(header[56:60], "little") != 0x644D5241:
        raise DinoError("Image does not have the ARM64 Linux boot header")
    symbols = {line.split()[-1] for line in (out / "System.map").read_text().splitlines()
               if len(line.split()) == 3}
    root_symbols = {"kernelsu_init", "ksu_handle_setresuid"}
    if profile == "kernelsu":
        if not root_symbols.issubset(symbols):
            raise DinoError("KernelSU was requested but its built-in symbols are missing")
        command = (out / "drivers/kernelsu/core/.init.o.cmd").read_text()
        versions = set(re.findall(r"-DKSU_VERSION=(\d+)(?:\s|$)", command))
        if versions != {str(lock["kernelsu"]["manager_version"])}:
            raise DinoError(f"KernelSU compiled version mismatch: {versions}")
    elif root_symbols.intersection(symbols):
        raise DinoError("KernelSU symbols leaked into the baseline Image")
    return release


def collect(lock: dict, profile: str) -> None:
    out, dest = output_dir(profile), artifact_dir(profile)
    files = {"Image": out / "arch/arm64/boot/Image",
             "System.map": out / "System.map", ".config": out / ".config"}
    for name, path in files.items():
        if not path.is_file() or path.stat().st_size == 0:
            raise DinoError(f"Missing build output: {path}")
    validate_config(files[".config"].read_text(), profile)
    release = validate_outputs(lock, profile, out)
    dest.mkdir(parents=True, exist_ok=True)
    for name, path in files.items():
        shutil.copy2(path, dest / name)
    manifest = {
        "product": "DinoDev", "profile": profile, "kernel_release": release,
        "kernelsu_manager_version": lock["kernelsu"]["manager_version"] if profile == "kernelsu" else None,
        "classification": "ARM64 development Image — NOT a flashable boot image",
        "kernel": lock["kernel"], "toolchain": lock["toolchain"],
        "build_tools": lock["build_tools"], "host_crypto": lock["host_crypto"],
        "kernelsu": lock["kernelsu"] if profile == "kernelsu" else None,
        "workspace_fingerprint": source_fingerprint(lock, profile),
        "device_validated": False, "boot_image_created": False,
        "kmi_abi_validated": False, "modules_packaged": False,
        "artifacts": {name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
                      for name, path in files.items()},
    }
    (dest / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    sums = [f"{sha256(dest / name)}  {name}" for name in files]
    sums.append(f"{sha256(dest / 'build-manifest.json')}  build-manifest.json")
    (dest / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    print(f"\nDevelopment artifacts: {dest.relative_to(ROOT)}\n"
          "Do not flash this Image: device packaging and boot validation are not complete.")


def build(lock: dict, profile: str, jobs: int) -> None:
    if jobs < 1:
        raise DinoError("--jobs must be positive")
    prepare(lock, profile)
    out = output_dir(profile)
    fragments = [ROOT / "config/common.config", ROOT / f"config/{profile}.config"]
    marker = out / ".dinodev-config.sha256"
    expected_config = fingerprint(fragments) + " " + sha256(out / ".config") if (out / ".config").is_file() else ""
    if not marker.is_file() or marker.read_text().strip() != expected_config:
        configure(lock, profile)
    validate_config((out / ".config").read_text(), profile)
    env = build_env(lock, profile)
    make = shutil.which("make")
    if not make:
        raise DinoError("GNU make is required")
    args = [make, "-C", str(source_dir(profile)), *make_args(profile), f"-j{jobs}"]
    if profile == "kernelsu":
        args += ["KSU_GIT_VERSION_VALID=1",
                 f"KSU_GIT_VERSION={lock['kernelsu']['git_commit_count']}",
                 f"KSU_VERSION={lock['kernelsu']['manager_version']}"]
    run([*args, "Image"], env=env, log=WORK / f"logs/{profile}-image.log")
    collect(lock, profile)


def doctor(lock: dict) -> None:
    print("DinoDev doctor — local checks only; no network and no device flashing")
    print(f"Host: {platform.system()} {platform.machine()}; Python {platform.python_version()}")
    for tool in ("git", "make", "gcc", "tar", "perl", "python3", "m4", "cpio", "xz"):
        print(f"{tool}: {shutil.which(tool) or 'MISSING'}")
    for name in COMPONENTS:
        repo = checkout(lock, name)
        state = "not fetched"
        if (repo / ".git").exists():
            state = "pinned" if git(repo, "rev-parse", "HEAD") == lock[name]["commit"] else "WRONG REVISION"
            if git(repo, "status", "--porcelain", "--untracked-files=all"):
                state += ", dirty (build-host outputs may be ignored)"
        print(f"{name}: {state} ({lock[name]['ref']} @ {lock[name]['commit'][:12]})")
    print(f"Suggested parallel jobs on this host: {default_jobs()}")
    print("No target device is configured. Both profiles produce development Images only.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Inspect local prerequisites and pinned sources")
    fetch = commands.add_parser("fetch", help="Fetch exact locked revisions; never update the lock")
    fetch.add_argument("--component", choices=(*COMPONENTS, "all"), default="all")
    for name in ("prepare", "config", "build"):
        cmd = commands.add_parser(name, help={
            "prepare": "Create an isolated source tree with optional KernelSU",
            "config": "Resolve gki_defconfig plus DinoDev fragments and check policy",
            "build": "Build an ARM64 development Image and checksummed metadata",
        }[name])
        cmd.add_argument("--profile", choices=PROFILES, default="baseline")
        if name == "prepare":
            cmd.add_argument("--force", action="store_true",
                             help="Replace only this profile's marked, generated source tree")
        if name == "build":
            cmd.add_argument("--jobs", type=int, default=default_jobs())
    args = parser.parse_args()
    try:
        lock = load_lock()
        if args.command == "doctor":
            doctor(lock)
        elif args.command == "fetch":
            for name in COMPONENTS if args.component == "all" else (args.component,):
                fetch_component(lock, name)
        elif args.command == "prepare":
            prepare(lock, args.profile, args.force)
        elif args.command == "config":
            prepare(lock, args.profile)
            configure(lock, args.profile)
        elif args.command == "build":
            build(lock, args.profile, args.jobs)
        return 0
    except (DinoError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"DinoDev: {error}", file=sys.stderr)
        return 1
    except subprocess.SubprocessError as error:
        print(f"DinoDev: subprocess failure: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
