"""Tests for process_ioc_data CLI."""

import tempfile
from pathlib import Path

import pytest
import requests
from click.testing import CliRunner

from ioc_reference_builder.process_ioc_data import cli


class TestDownloadCommand:
    """Tests for the download command."""

    @pytest.fixture
    def runner(self):
        """Create CLI test runner."""
        return CliRunner()

    def test_download_success(self, runner, mocker, http_response_factory):
        """Should successfully download all files."""
        # Mock requests.get to return successful response
        mock_get = mocker.patch(
            "ioc_reference_builder.process_ioc_data.requests.get",
            return_value=http_response_factory(content=b"test file content"),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(cli, ["download", "--version", "15.1", "--output-dir", tmpdir])

            # Check command succeeded
            assert result.exit_code == 0
            assert "✓ All files downloaded successfully" in result.output

            # Check all 4 files were attempted
            assert mock_get.call_count == 4

            # Check files were created
            output_dir = Path(tmpdir)
            assert (output_dir / "ioc_names_plus_red.xlsx").exists()
            assert (output_dir / "ioc_names_plus.xlsx").exists()
            assert (output_dir / "multilingual.xlsx").exists()
            assert (output_dir / "master_xml.xml").exists()

    def test_download_with_custom_version(self, runner, mocker, http_response_factory):
        """Should download with custom version number."""
        mock_get = mocker.patch(
            "ioc_reference_builder.process_ioc_data.requests.get",
            return_value=http_response_factory(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(cli, ["download", "--version", "14.2", "--output-dir", tmpdir])

            assert result.exit_code == 0

            # Check that version was used in URLs
            calls = mock_get.call_args_list
            assert any("14.2" in str(call) for call in calls)

    def test_download_creates_output_directory(self, runner, mocker, http_response_factory):
        """Should create output directory if it doesn't exist."""
        mocker.patch(
            "ioc_reference_builder.process_ioc_data.requests.get",
            return_value=http_response_factory(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "nested" / "directory"
            result = runner.invoke(
                cli,
                ["download", "--version", "15.1", "--output-dir", str(output_dir)],
            )

            assert result.exit_code == 0
            assert output_dir.exists()
            assert output_dir.is_dir()

    def test_download_partial_failure(self, runner, mocker, http_response_factory):
        """Should handle download when some files fail."""

        def mock_get_side_effect(url, headers=None, timeout=None):
            if "red" in url:
                # Fail for red file
                return http_response_factory(
                    raise_for_status_error=requests.exceptions.HTTPError("404 Not Found")
                )
            else:
                # Succeed for other files
                return http_response_factory(content=b"test content")

        mocker.patch(
            "ioc_reference_builder.process_ioc_data.requests.get",
            side_effect=mock_get_side_effect,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(cli, ["download", "--version", "15.1", "--output-dir", tmpdir])

            # Should exit with error code
            assert result.exit_code == 1

            # Should show both success and failure
            assert "✓ Downloaded" in result.output
            assert "✗ Failed to download" in result.output
            assert "Failed downloads:" in result.output

    def test_download_all_files_fail(self, runner, mocker, http_response_factory):
        """Should handle download when all files fail."""
        mocker.patch(
            "ioc_reference_builder.process_ioc_data.requests.get",
            return_value=http_response_factory(
                status_code=404,
                raise_for_status_error=requests.exceptions.HTTPError("404 Not Found"),
            ),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(cli, ["download", "--version", "15.1", "--output-dir", tmpdir])

            # Should exit with error code
            assert result.exit_code == 1

            # Check error messages
            assert "✗ Failed to download" in result.output
            assert "Downloaded: 0/4 files" in result.output

    def test_download_urls_format(self, runner, mocker, http_response_factory):
        """Should format URLs correctly."""
        mock_get = mocker.patch(
            "ioc_reference_builder.process_ioc_data.requests.get",
            return_value=http_response_factory(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            runner.invoke(cli, ["download", "--version", "15.1", "--output-dir", tmpdir])

            # Extract called URLs
            called_urls = [call[0][0] for call in mock_get.call_args_list]

            # Check expected URLs
            assert "https://www.worldbirdnames.org/IOC_Names_File_Plus-15.1_red.xlsx" in called_urls
            assert "https://www.worldbirdnames.org/IOC_Names_File_Plus-15.1.xlsx" in called_urls
            assert "https://www.worldbirdnames.org/Multiling%20IOC%2015.1_c.xlsx" in called_urls
            assert "https://www.worldbirdnames.org/master_ioc-names_xml.15.1.xml" in called_urls

    def test_download_default_output_directory(self, runner, mocker, http_response_factory):
        """Should use default output directory when not specified."""
        mocker.patch(
            "ioc_reference_builder.process_ioc_data.requests.get",
            return_value=http_response_factory(),
        )

        # Use isolated filesystem to prevent writing to actual data/ioc directory
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["download", "--version", "15.1"])

            # Check default directory was mentioned
            assert "data/ioc" in result.output

            # Verify files were created in the isolated data/ioc directory
            assert (Path("data/ioc/ioc_names_plus_red.xlsx")).exists()
            assert (Path("data/ioc/master_xml.xml")).exists()

    def test_download_file_size_reporting(self, runner, mocker, http_response_factory):
        """Should report file sizes correctly."""
        mocker.patch(
            "ioc_reference_builder.process_ioc_data.requests.get",
            return_value=http_response_factory(content=b"x" * (1024 * 1024)),  # 1 MB
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(cli, ["download", "--version", "15.1", "--output-dir", tmpdir])

            # Check that file size is reported
            assert "1.00 MB" in result.output


class TestDownloadCommandErrorPaths:
    """Tests for download command error handling."""

    @pytest.fixture
    def runner(self):
        """Create CLI test runner."""
        return CliRunner()

    def test_download_with_connection_timeout(self, runner, mocker):
        """Should handle connection timeouts gracefully."""
        mocker.patch(
            "ioc_reference_builder.process_ioc_data.requests.get",
            side_effect=requests.exceptions.Timeout("Connection timed out"),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(cli, ["download", "--version", "15.1", "--output-dir", tmpdir])

            # Should exit with error
            assert result.exit_code == 1
            assert "timed out" in result.output.lower() or "timeout" in result.output.lower()

    def test_download_with_connection_error(self, runner, mocker):
        """Should handle connection refused errors."""
        mocker.patch(
            "ioc_reference_builder.process_ioc_data.requests.get",
            side_effect=requests.exceptions.ConnectionError("Connection refused"),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(cli, ["download", "--version", "15.1", "--output-dir", tmpdir])

            # Should exit with error
            assert result.exit_code == 1
            assert "connection" in result.output.lower() or "failed" in result.output.lower()

    def test_download_with_ssl_error(self, runner, mocker):
        """Should handle SSL certificate errors."""
        mocker.patch(
            "ioc_reference_builder.process_ioc_data.requests.get",
            side_effect=requests.exceptions.SSLError("SSL certificate verify failed"),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(cli, ["download", "--version", "15.1", "--output-dir", tmpdir])

            # Should exit with error
            assert result.exit_code == 1
            assert (
                "ssl" in result.output.lower()
                or "certificate" in result.output.lower()
                or "failed" in result.output.lower()
            )

    def test_download_with_http_429_rate_limit(self, runner, mocker, http_response_factory):
        """Should handle HTTP 429 rate limiting."""
        mocker.patch(
            "ioc_reference_builder.process_ioc_data.requests.get",
            return_value=http_response_factory(
                status_code=429,
                raise_for_status_error=requests.exceptions.HTTPError("429 Too Many Requests"),
            ),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(cli, ["download", "--version", "15.1", "--output-dir", tmpdir])

            # Should exit with error
            assert result.exit_code == 1
            assert "failed" in result.output.lower()

    def test_download_with_http_503_service_unavailable(
        self, runner, mocker, http_response_factory
    ):
        """Should handle HTTP 503 service unavailable."""
        mocker.patch(
            "ioc_reference_builder.process_ioc_data.requests.get",
            return_value=http_response_factory(
                status_code=503,
                raise_for_status_error=requests.exceptions.HTTPError("503 Service Unavailable"),
            ),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(cli, ["download", "--version", "15.1", "--output-dir", tmpdir])

            # Should exit with error
            assert result.exit_code == 1
            assert "failed" in result.output.lower()

    def test_download_with_invalid_response_content(self, runner, mocker, http_response_factory):
        """Should handle corrupted/invalid file content."""
        # Return valid HTTP but corrupted file content
        mocker.patch(
            "ioc_reference_builder.process_ioc_data.requests.get",
            return_value=http_response_factory(content=b"Not a real XLSX/XML file"),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(cli, ["download", "--version", "15.1", "--output-dir", tmpdir])

            # Should complete download (corruption detected during processing, not download)
            assert result.exit_code == 0
            assert "Downloaded" in result.output

    def test_download_with_permission_denied(self, runner, mocker, http_response_factory):
        """Should handle permission denied errors."""
        mocker.patch(
            "ioc_reference_builder.process_ioc_data.requests.get",
            return_value=http_response_factory(),
        )

        # Mock mkdir to raise permission error
        def mock_mkdir(self, parents=False, exist_ok=False):
            raise PermissionError("[Errno 13] Permission denied")

        mocker.patch.object(Path, "mkdir", mock_mkdir)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "protected"
            result = runner.invoke(
                cli,
                ["download", "--version", "15.1", "--output-dir", str(output_dir)],
            )

            # Should exit with error
            assert result.exit_code == 1
