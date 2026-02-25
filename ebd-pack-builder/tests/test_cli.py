"""Tests for CLI commands."""

from click.testing import CliRunner

from ebd_pack_builder.cli import cli


class TestCLI:
    """Test CLI command structure."""

    def test_cli_help(self):
        """Should show help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "eBird Basic Dataset pack builder" in result.output

    def test_cli_version(self):
        """Should show version."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_convert_help(self):
        """Should show convert command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["convert", "--help"])
        assert result.exit_code == 0
        assert "--input" in result.output
        assert "--output-dir" in result.output

    def test_sort_help(self):
        """Should show sort command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["sort", "--help"])
        assert result.exit_code == 0
        assert "--input-dir" in result.output
        assert "--sort-order" in result.output

    def test_partition_help(self):
        """Should show partition command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["partition", "--help"])
        assert result.exit_code == 0
        assert "--boundary-resolution" in result.output
        assert "--discover-only" in result.output

    def test_density_report_help(self):
        """Should show density-report command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["density-report", "--help"])
        assert result.exit_code == 0
        assert "--boundary-cells" in result.output

    def test_size_manifest_help(self):
        """Should show size-manifest command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["size-manifest", "--help"])
        assert result.exit_code == 0
        assert "--packs-dir" in result.output
        assert "--pack-manifest" in result.output

    def test_build_help(self):
        """Should show build command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["build", "--help"])
        assert result.exit_code == 0
        assert "--partitioned-dir" in result.output
        assert "--worker" in result.output
        assert "--skip-existing" in result.output

    def test_verify_help(self):
        """Should show verify command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["verify", "--help"])
        assert result.exit_code == 0
        assert "DIRECTORIES" in result.output

    def test_status_help(self):
        """Should show status command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--help"])
        assert result.exit_code == 0
        assert "--state-dir" in result.output

    def test_run_all_help(self):
        """Should show run-all command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["run-all", "--help"])
        assert result.exit_code == 0
        assert "--from-step" in result.output
        assert "--force" in result.output
