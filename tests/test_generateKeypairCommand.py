"""Tests for the generate-keypair console command."""

import json
import os
import stat
from pathlib import Path

import pytest

from lti1p3.console import GenerateKeypairCommand, main


class TestGenerateKeypairCommand:
    def test_helpFlagPrintsUsageAndReturnsZero(self):
        result = GenerateKeypairCommand().run(["--help"])
        assert result.exitCode == 0
        assert "Usage: lti1p3-generate-keypair" in result.stdout
        assert result.stderr == ""

    def test_missingKidReturnsErrorExitCode(self):
        result = GenerateKeypairCommand().run([])
        assert result.exitCode == 1
        assert "--kid is required" in result.stderr

    def test_blankKidReturnsErrorExitCode(self):
        result = GenerateKeypairCommand().run(["--kid=   "])
        assert result.exitCode == 1
        assert "--kid is required" in result.stderr

    def test_bitsBelowMinimumReturnsErrorExitCode(self):
        result = GenerateKeypairCommand().run(["--kid=kid-1", "--bits=512"])
        assert result.exitCode == 1
        assert "--bits must be at least 2048" in result.stderr

    def test_nonNumericBitsReturnsErrorExitCode(self):
        result = GenerateKeypairCommand().run(["--kid=kid-1", "--bits=lots"])
        assert result.exitCode == 1
        assert "--bits must be a whole number" in result.stderr

    def test_unknownArgumentReturnsErrorExitCode(self):
        result = GenerateKeypairCommand().run(["--kid=kid-1", "--verbose"])
        assert result.exitCode == 1
        assert 'Unknown argument "--verbose"' in result.stderr

    def test_generatesRealKeyPairAndWritesPemFilesToOutDir(self, tmp_path: Path):
        outDir = tmp_path / "keys"
        result = GenerateKeypairCommand().run(["--kid=kid-1", f"--out-dir={outDir}"])

        assert result.exitCode == 0, result.stderr
        assert "BEGIN PRIVATE KEY" in (outDir / "kid-1.private.pem").read_text()
        assert "BEGIN PUBLIC KEY" in (outDir / "kid-1.public.pem").read_text()
        jwk = json.loads(result.stdout.split("\n\n", 2)[2])
        assert jwk["kid"] == "kid-1"
        assert jwk["kty"] == "RSA"

    def test_privateKeyFileIsWrittenWithRestrictivePermissions(self, tmp_path: Path):
        outDir = tmp_path / "keys"
        GenerateKeypairCommand().run(["--kid=kid-1", f"--out-dir={outDir}"])
        mode = stat.S_IMODE(os.stat(outDir / "kid-1.private.pem").st_mode)
        assert mode == 0o600

    def test_createsOutputDirectoryWhenMissing(self, tmp_path: Path):
        outDir = tmp_path / "nested" / "keys"
        result = GenerateKeypairCommand().run(["--kid=kid-1", f"--out-dir={outDir}"])
        assert result.exitCode == 0
        assert outDir.is_dir()

    def test_defaultsToWorkingKeysUnderTheCurrentWorkingDirectory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)
        result = GenerateKeypairCommand().run(["--kid=kid-1"])
        assert result.exitCode == 0
        assert (tmp_path / "working" / "keys" / "kid-1.private.pem").is_file()

    def test_reportsWhenTheOutputDirectoryCannotBeCreated(self, tmp_path: Path):
        blocker = tmp_path / "file"
        blocker.write_text("not a directory")
        result = GenerateKeypairCommand().run(["--kid=kid-1", f"--out-dir={blocker / 'keys'}"])
        assert result.exitCode == 1
        assert "could not create output directory" in result.stderr


class TestMain:
    def test_writesOutputAndExitsWithTheCommandsCode(self, capsys: pytest.CaptureFixture[str]):
        with pytest.raises(SystemExit) as exited:
            main(["--help"])
        assert exited.value.code == 0
        captured = capsys.readouterr()
        assert "Usage:" in captured.out
        assert captured.err == ""

    def test_errorsGoToStderr(self, capsys: pytest.CaptureFixture[str]):
        with pytest.raises(SystemExit) as exited:
            main([])
        assert exited.value.code == 1
        assert "--kid is required" in capsys.readouterr().err
