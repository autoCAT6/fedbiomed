# This file is originally part of Fed-BioMed
# SPDX-License-Identifier: Apache-2.0

"""Shell component checks for the GUI entrypoint's certificate selection."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ENTRYPOINT = (
    Path(__file__).resolve().parents[1]
    / "envs/vpn/docker/gui/build_files/entrypoint.bash"
)

# Run the entrypoint's selection block against a temporary mounted directory.
# Only the /certs root and OpenSSL generation are substituted. Translate the
# GNU find -printf form and wc count output so these component checks run with
# BSD command-line tools.
SHELL_HELPERS = r"""
find() {
    local root="$1"
    shift
    if [ "$root" = /certs ]; then
        root="$TEST_CERTS_DIR"
    fi
    local -a args=()
    while [ "$#" -gt 0 ]; do
        if [ "$1" = -printf ]; then
            [ "$2" = x ] || return 2
            args+=(-exec printf x ';')
            shift 2
        else
            args+=("$1")
            shift
        fi
    done
    command find "$root" "${args[@]}"
}
openssl() {
    printf 'generation requested\n' > "$TEST_GENERATION_MARKER"
}
wc() {
    if [ "$#" = 1 ] && [ "$1" = -c ]; then
        command wc -c | tr -d '[:space:]'
        printf '\n'
    else
        command wc "$@"
    fi
}
"""


class TestGuiEntrypointCertificates(unittest.TestCase):
    """Exercise the real shell branch, without starting Docker or nginx."""

    @classmethod
    def setUpClass(cls):
        source = ENTRYPOINT.read_text()
        start = source.index("# Find number of files in /certs")
        end = source.index('if [ "$SSL_ON"', start)
        cls.selection = source[start:end]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.mount = self.root / "mounted certificates"
        self.mount.mkdir()
        self.cwd = self.root / "unrelated working directory"
        self.cwd.mkdir()
        self.generated = self.root / "generated"

    def run_selection(self):
        env = os.environ.copy()
        env.update(
            TEST_CERTS_DIR=str(self.mount),
            TEST_GENERATION_MARKER=str(self.generated),
            SETUSER="",
            SSL_CERTIFICATE="",
            SSL_KEY="",
        )
        script = (
            SHELL_HELPERS
            + self.selection
            + (
                '\nprintf "SELECTED_CERT=%s\\nSELECTED_KEY=%s\\n" '
                '"$SSL_CERTIFICATE" "$SSL_KEY"'
            )
        )
        return subprocess.run(
            ["/bin/bash", "-c", script],
            cwd=self.cwd,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def assert_generated(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.generated.exists())
        self.assertIn("SELECTED_CERT=/certs/fedbiomed-node-gui.crt", result.stdout)
        self.assertIn("SELECTED_KEY=/certs/fedbiomed-node-gui.key", result.stdout)

    def test_mounted_pair_is_selected_without_generation(self):
        cert = self.mount / "provided.crt"
        key = self.mount / "provided.key"
        cert.write_text("provided certificate")
        key.write_text("provided key")
        result = self.run_selection()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.generated.exists())
        self.assertIn(f"SELECTED_CERT={cert}", result.stdout)
        self.assertIn(f"SELECTED_KEY={key}", result.stdout)
        self.assertEqual(cert.read_text(), "provided certificate")
        self.assertEqual(key.read_text(), "provided key")

    def test_empty_mount_uses_generation(self):
        self.assert_generated(self.run_selection())

    def test_placeholder_only_mount_uses_generation(self):
        (self.mount / ".gitkeep").touch()
        self.assert_generated(self.run_selection())

    def test_unrelated_relative_directory_does_not_replace_empty_mount(self):
        decoy = self.cwd / "gui/run_mounts/certs"
        decoy.mkdir(parents=True)
        (decoy / "unrelated.crt").touch()
        (decoy / "unrelated.key").touch()
        self.assert_generated(self.run_selection())

    def test_incomplete_mounted_pair_is_rejected_without_generation(self):
        (self.mount / "provided.crt").touch()
        result = self.run_selection()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertFalse(self.generated.exists())
        self.assertIn("only one of them", result.stdout)


if __name__ == "__main__":
    unittest.main()
