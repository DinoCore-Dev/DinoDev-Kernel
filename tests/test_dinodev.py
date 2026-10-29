# SPDX-License-Identifier: GPL-2.0-only
"""Fast tests: no kernel/toolchain downloads and no device access."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dinodev", ROOT / "scripts/dinodev.py")
dino = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dino)


def valid_config(profile="baseline"):
    values = {key: "y" for key in dino.SECURITY_SYMBOLS}
    values.update({
        "CONFIG_ARM64": "y", "CONFIG_LTO_CLANG_THIN": "y",
        "CONFIG_LOCALVERSION": '"-DinoDev"', "CONFIG_KPROBES": "y",
        "CONFIG_HAVE_SYSCALL_TRACEPOINTS": "y", "CONFIG_OVERLAY_FS": "y",
        "CONFIG_EXT4_FS": "y",
    })
    if profile == "kernelsu":
        values["CONFIG_KSU"] = "y"
    return "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"


class LockTests(unittest.TestCase):
    def test_actual_lock_is_pinned(self):
        lock = dino.load_lock()
        self.assertEqual(lock["kernel"]["version"], "5.10.264")
        for name in dino.COMPONENTS:
            self.assertRegex(lock[name]["commit"], r"^[0-9a-f]{40}$")

    def test_rejects_moving_revision(self):
        lock = json.loads((ROOT / "kernel.lock.json").read_text())
        lock["kernel"]["commit"] = "millennium-base"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lock.json"
            path.write_text(json.dumps(lock))
            with self.assertRaises(dino.DinoError):
                dino.load_lock(path)

    def test_rejects_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lock.json"
            path.write_text('{"schema_version": 1, "schema_version": 1}')
            with self.assertRaises(ValueError):
                dino.load_lock(path)

    def test_rejects_double_counted_kernelsu_version(self):
        lock = json.loads((ROOT / "kernel.lock.json").read_text())
        lock["kernelsu"]["manager_version"] += 30000
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lock.json"
            path.write_text(json.dumps(lock))
            with self.assertRaises(dino.DinoError):
                dino.load_lock(path)

    def test_rejects_non_github_source(self):
        lock = json.loads((ROOT / "kernel.lock.json").read_text())
        lock["kernel"]["repository"] = "https://example.com/kernel.git"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lock.json"
            path.write_text(json.dumps(lock))
            with self.assertRaises(dino.DinoError):
                dino.load_lock(path)


class ConfigTests(unittest.TestCase):
    def test_parse_enabled_disabled_and_strings(self):
        result = dino.parse_config('CONFIG_A=y\n# CONFIG_B is not set\nCONFIG_C="hello"\n')
        self.assertEqual(result, {"CONFIG_A": "y", "CONFIG_B": "n", "CONFIG_C": '"hello"'})

    def test_merge_replaces_both_enabled_and_disabled(self):
        base = "CONFIG_A=y\n# CONFIG_B is not set\nCONFIG_C=y\n"
        result = dino.merge_fragment(base, "# CONFIG_A is not set\nCONFIG_B=y\n")
        self.assertEqual(dino.parse_config(result),
                         {"CONFIG_A": "n", "CONFIG_B": "y", "CONFIG_C": "y"})

    def test_baseline_passes(self):
        dino.validate_config(valid_config(), "baseline")

    def test_kernelsu_passes(self):
        dino.validate_config(valid_config("kernelsu"), "kernelsu")

    def test_root_cannot_leak_into_baseline(self):
        with self.assertRaises(dino.DinoError):
            dino.validate_config(valid_config("kernelsu"), "baseline")

    def test_root_cannot_be_missing_from_kernelsu(self):
        with self.assertRaises(dino.DinoError):
            dino.validate_config(valid_config(), "kernelsu")

    def test_security_regressions_fail(self):
        for key in dino.SECURITY_SYMBOLS:
            with self.subTest(key=key):
                text = valid_config().replace(f"{key}=y", f"# {key} is not set")
                with self.assertRaises(dino.DinoError):
                    dino.validate_config(text, "baseline")

    def test_debug_root_fails(self):
        with self.assertRaises(dino.DinoError):
            dino.validate_config(valid_config("kernelsu") + "CONFIG_KSU_DEBUG=y\n", "kernelsu")

    def test_actual_common_fragment_preserves_security(self):
        text = dino.merge_fragment(valid_config(), (ROOT / "config/common.config").read_text())
        dino.validate_config(text, "baseline")


class OutputTests(unittest.TestCase):
    def make_output(self, root: Path, profile: str, version: int = 32680) -> Path:
        out = root / profile
        (out / "include/config").mkdir(parents=True)
        (out / "arch/arm64/boot").mkdir(parents=True)
        (out / "include/config/kernel.release").write_text("5.10.264-DinoDev\n")
        header = bytearray(64)
        struct.pack_into("<I", header, 56, 0x644D5241)
        (out / "arch/arm64/boot/Image").write_bytes(header)
        symbols = "ffffffc000001000 T unrelated_symbol\n"
        if profile == "kernelsu":
            symbols += "ffffffc000002000 T kernelsu_init\nffffffc000003000 T ksu_handle_setresuid\n"
            command = out / "drivers/kernelsu/core/.init.o.cmd"
            command.parent.mkdir(parents=True)
            command.write_text(f"cmd := clang -DKSU_VERSION={version} -c init.c\n")
        (out / "System.map").write_text(symbols)
        return out

    def test_baseline_product_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.make_output(Path(tmp), "baseline")
            self.assertEqual(dino.validate_outputs(dino.load_lock(), "baseline", out),
                             "5.10.264-DinoDev")

    def test_kernelsu_product_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.make_output(Path(tmp), "kernelsu")
            dino.validate_outputs(dino.load_lock(), "kernelsu", out)

    def test_wrong_release_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.make_output(Path(tmp), "baseline")
            (out / "include/config/kernel.release").write_text("5.10.264-DinoDev+\n")
            with self.assertRaises(dino.DinoError):
                dino.validate_outputs(dino.load_lock(), "baseline", out)

    def test_wrong_architecture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.make_output(Path(tmp), "baseline")
            (out / "arch/arm64/boot/Image").write_bytes(b"x" * 64)
            with self.assertRaises(dino.DinoError):
                dino.validate_outputs(dino.load_lock(), "baseline", out)

    def test_missing_root_symbols_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.make_output(Path(tmp), "kernelsu")
            (out / "System.map").write_text("ffffffc000001000 T unrelated_symbol\n")
            with self.assertRaises(dino.DinoError):
                dino.validate_outputs(dino.load_lock(), "kernelsu", out)

    def test_wrong_compiled_root_version_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.make_output(Path(tmp), "kernelsu", version=62680)
            with self.assertRaises(dino.DinoError):
                dino.validate_outputs(dino.load_lock(), "kernelsu", out)

    def test_root_symbols_in_baseline_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.make_output(Path(tmp), "baseline")
            (out / "System.map").write_text("ffffffc000002000 T kernelsu_init\n")
            with self.assertRaises(dino.DinoError):
                dino.validate_outputs(dino.load_lock(), "baseline", out)


class IntegrationTests(unittest.TestCase):
    def test_kernelsu_integration_is_explicit_and_not_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree, ksu = root / "tree", root / "ksu"
            (tree / "drivers").mkdir(parents=True)
            (tree / "drivers/Makefile").write_text("obj-y += core/\n")
            (tree / "drivers/Kconfig").write_text('menu "Drivers"\nsource "drivers/core/Kconfig"\nendmenu\n')
            (ksu / "kernel").mkdir(parents=True)
            (ksu / "kernel/Kconfig").write_text("config KSU\n\tbool \"KernelSU\"\n")
            (ksu / "LICENSE").write_text("Upstream license\n")
            with patch.object(dino, "git", return_value="a" * 40):
                dino.integrate_kernelsu(tree, ksu, 32680)
                with self.assertRaises(dino.DinoError):
                    dino.integrate_kernelsu(tree, ksu, 32680)
            self.assertEqual((tree / "drivers/Makefile").read_text().count("CONFIG_KSU"), 1)
            self.assertEqual((tree / "drivers/Kconfig").read_text().count('source "drivers/kernelsu/Kconfig"'), 1)
            self.assertTrue((tree / "drivers/kernelsu/LICENSE.KernelSU").is_file())
            self.assertIn("Experimental", (tree / "drivers/kernelsu/DINODEV_PROVENANCE").read_text())

    def test_unknown_source_directory_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "source"
            tree.mkdir()
            sentinel = tree / "user-file"
            sentinel.write_text("keep")
            with patch.object(dino, "source_dir", return_value=tree), \
                 patch.object(dino, "verify_checkout"):
                with self.assertRaises(dino.DinoError):
                    dino.prepare(dino.load_lock(), "baseline", force=True)
            self.assertEqual(sentinel.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
