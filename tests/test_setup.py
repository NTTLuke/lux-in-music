"""Exercise first-run scripts using local fake installation tools, without downloads."""

import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        scripts = self.root / "scripts"; scripts.mkdir()
        for name in ("setup.sh", "build_cpu.sh"):
            shutil.copyfile(ROOT / "scripts" / name, scripts / name)
            (scripts / name).chmod(0o755)
        shutil.copyfile(ROOT / "studio.sh", self.root / "studio.sh")
        self.bin = self.root / "bin"; self.bin.mkdir()
        self.log = self.root / "commands.txt"
        self.env = {**os.environ, "PATH": f"{self.bin}:/usr/bin:/bin", "NO_OPEN": "1", "TEST_LOG": str(self.log)}
        self.tool("uname", 'echo Linux')
        self.tool("uv", '''echo "uv $*" >> "$TEST_LOG"
if [ "$1" = sync ]; then
 case " $* " in
  *" --inexact "*) ;;
  *) rm -f .venv/vibe-runtime-installed ;;
 esac
 mkdir -p .venv/bin
 printf '#!/bin/sh\\nif [ "$*" = "-m studio.bootstrap families" ]; then echo test_family; else echo "launch $*" >> "$TEST_LOG"; fi\\n' > .venv/bin/python
 printf '#!/bin/sh\\nexit 0\\n' > .venv/bin/studio-gen
 chmod +x .venv/bin/python .venv/bin/studio-gen
fi''')
        self.tool("git", '''echo "git $*" >> "$TEST_LOG"
if [ "$1" = clone ]; then mkdir -p vendor/audio.cpp; fi''')
        self.tool("cmake", '''echo "cmake $*" >> "$TEST_LOG"
mkdir -p build/cpu-release/bin
printf '#!/bin/sh\\nexit 0\\n' > build/cpu-release/bin/audiocpp_server
chmod +x build/cpu-release/bin/audiocpp_server''')
        self.tool("curl", 'echo "Unexpected network access" >&2; exit 99')

    def tool(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\nset -eu\n" + body + "\n"); path.chmod(0o755)

    def run_studio(self):
        return subprocess.run(["/bin/bash", "studio.sh", "--port", "18000"], cwd=self.root, env=self.env,
                              capture_output=True, text=True, timeout=10)

    def test_first_run_installs_software_then_launches_without_model_weights(self):
        result = self.run_studio()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.log.read_text()
        self.assertIn("uv sync --frozen --python 3.12", calls)
        self.assertIn("git clone --no-checkout", calls)
        self.assertIn("cmake --build", calls)
        self.assertIn("launch -m studio.launch --no-open --port 18000", calls)
        self.assertIn("[1/4]", result.stdout)
        self.assertIn("[3/4]", result.stdout)
        self.assertFalse((self.root / "models").exists())
        self.assertNotIn("huggingface", calls)

    def test_second_run_reuses_runtime_and_does_not_clone_or_rebuild(self):
        self.assertEqual(self.run_studio().returncode, 0)
        self.log.write_text("")
        result = self.run_studio()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("git clone", self.log.read_text())
        self.assertNotIn("cmake --build", self.log.read_text())
        self.assertIn("build skipped", result.stdout)

    def test_startup_preserves_explicitly_installed_optional_runtime(self):
        runtime = self.root / ".venv" / "vibe-runtime-installed"
        runtime.parent.mkdir()
        runtime.write_text("installed through Settings")
        for _ in range(2):
            result = self.run_studio()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(runtime.is_file(), "startup removed the optional Vibe runtime")
        self.assertNotIn("--extra", self.log.read_text())
        self.assertFalse((self.root / "models").exists())

    def test_missing_uv_uses_the_local_installer_before_dependency_setup(self):
        stub = (self.bin / "uv").read_text()
        (self.bin / "uv").unlink()
        installer = self.root / "installer.sh"
        installer.write_text("#!/bin/sh\nmkdir -p \"$UV_INSTALL_DIR\"\ncat > \"$UV_INSTALL_DIR/uv\" <<'UV'\n" + stub + "UV\nchmod +x \"$UV_INSTALL_DIR/uv\"\n")
        self.env["TEST_INSTALLER"] = str(installer)
        self.tool("curl", '''echo "curl $*" >> "$TEST_LOG"
while [ "$1" != -o ]; do shift; done
cp "$TEST_INSTALLER" "$2"''')
        result = self.run_studio()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("astral.sh/uv/0.10.10/install.sh", self.log.read_text())
        self.assertFalse((self.root / "models").exists())

    def test_missing_apple_compiler_tools_explains_how_to_continue(self):
        self.tool("uname", "echo Darwin")
        self.tool("xcode-select", "exit 1")
        result = self.run_studio()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("xcode-select --install", result.stderr)
        self.assertNotIn("git clone", self.log.read_text())
        self.assertNotIn("launch -m studio.launch", self.log.read_text())

    def test_retry_of_existing_checkout_rewrites_ssh_submodule_urls_without_network(self):
        real_git = shutil.which("git")
        self.assertIsNotNone(real_git, "Git is a software setup prerequisite")
        global_config = self.root / "global.gitconfig"
        global_config.write_text("[user]\n\tname = Test only\n")
        original_config = global_config.read_bytes()
        self.env.update(GIT_CONFIG_GLOBAL=str(global_config), GIT_CONFIG_NOSYSTEM="1")
        checkout = self.root / "vendor/audio.cpp"
        checkout.mkdir(parents=True)
        def git(*args):
            return subprocess.run([real_git, "-C", str(checkout), *args], env=self.env,
                                  capture_output=True, text=True, check=True)
        git("init")
        submodule = "external/audio.cpp-server-frontends"
        # A real submodule index entry; no external repository or commit is fetched.
        git("update-index", "--add", "--cacheinfo", "160000," + "1" * 40 + "," + submodule)
        self.tool("git", '''echo "git $*" >> "$TEST_LOG"
case "$*" in
  *"submodule update"*) exec ''' + shlex.quote(real_git) + ''' -c protocol.https.allow=never -c protocol.ssh.allow=never "$@" ;;
  *"rev-parse HEAD"*) echo 6c3ab9ad4e599a44d287697863b4f8846ef658be ;;
esac''')
        for url in ("git@github.com:0xShug0/audio.cpp-server-frontends.git",
                    "ssh://git@github.com/0xShug0/audio.cpp-server-frontends.git"):
            with self.subTest(url=url):
                (checkout / ".gitmodules").write_text(f'[submodule "{submodule}"]\n\tpath = {submodule}\n\turl = {url}\n')
                git("add", ".gitmodules")
                # A previous failed --init already saved the original SSH URL here.
                git("config", f"submodule.{submodule}.url", url)
                result = self.run_studio()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("transport 'https' not allowed", result.stderr)
                self.assertNotIn("transport 'ssh' not allowed", result.stderr)
                self.assertNotIn("git clone", self.log.read_text())
                self.assertEqual(global_config.read_bytes(), original_config)
