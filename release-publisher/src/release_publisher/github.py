"""GitHub CLI wrapper for release and asset management."""

import json
import subprocess
from pathlib import Path
from typing import Any


class GitHubCLIError(Exception):
    """Error executing gh CLI command."""

    pass


class GitHubClient:
    """Wrapper around gh CLI for release management."""

    def __init__(self, target_repo: str):
        """Initialize GitHub client.

        Args:
            target_repo: Target repository in owner/repo format

        Raises:
            GitHubCLIError: If gh CLI is not installed or not authenticated
        """
        self.target_repo = target_repo
        self._verify_gh_cli()

    def _verify_gh_cli(self) -> None:
        """Verify gh CLI is installed and authenticated.

        Raises:
            GitHubCLIError: If gh is not available or not authenticated
        """
        # Check if gh is installed
        try:
            subprocess.run(
                ["gh", "--version"],
                capture_output=True,
                check=True,
                text=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            raise GitHubCLIError("gh CLI not found. Install from https://cli.github.com/") from e

        # Check authentication status
        try:
            result = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True,
                check=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            raise GitHubCLIError(
                f"gh CLI not authenticated. Run 'gh auth login'\n{e.stderr}"
            ) from e

    def release_exists(self, release_name: str) -> bool:
        """Check if a release exists.

        Args:
            release_name: Release tag name

        Returns:
            True if release exists, False otherwise
        """
        result = subprocess.run(
            [
                "gh",
                "release",
                "view",
                release_name,
                "--repo",
                self.target_repo,
                "--json",
                "name",
            ],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def create_release(
        self, release_name: str, title: str, notes: str, dry_run: bool = False
    ) -> None:
        """Create a GitHub release.

        Args:
            release_name: Release tag name
            title: Release title
            notes: Release description
            dry_run: If True, print command instead of executing

        Raises:
            GitHubCLIError: If release creation fails
        """
        cmd = [
            "gh",
            "release",
            "create",
            release_name,
            "--repo",
            self.target_repo,
            "--title",
            title,
            "--notes",
            notes,
        ]

        if dry_run:
            print(f"[DRY RUN] Would execute: {' '.join(cmd)}")
            return

        try:
            subprocess.run(cmd, capture_output=True, check=True, text=True)
        except subprocess.CalledProcessError as e:
            raise GitHubCLIError(f"Failed to create release {release_name}: {e.stderr}") from e

    def get_release_assets(self, release_name: str) -> list[str]:
        """Get list of asset names for a release.

        Args:
            release_name: Release tag name

        Returns:
            List of asset filenames

        Raises:
            GitHubCLIError: If release doesn't exist or query fails
        """
        try:
            result = subprocess.run(
                [
                    "gh",
                    "release",
                    "view",
                    release_name,
                    "--repo",
                    self.target_repo,
                    "--json",
                    "assets",
                ],
                capture_output=True,
                check=True,
                text=True,
            )
            data = json.loads(result.stdout)
            return [asset["name"] for asset in data.get("assets", [])]
        except subprocess.CalledProcessError as e:
            raise GitHubCLIError(f"Failed to get assets for {release_name}: {e.stderr}") from e
        except (json.JSONDecodeError, KeyError) as e:
            raise GitHubCLIError(f"Failed to parse release assets: {e}") from e

    def upload_asset(self, release_name: str, asset_path: Path, dry_run: bool = False) -> None:
        """Upload an asset to a release.

        Args:
            release_name: Release tag name
            asset_path: Path to asset file
            dry_run: If True, print command instead of executing

        Raises:
            GitHubCLIError: If upload fails
            FileNotFoundError: If asset file doesn't exist
        """
        if not asset_path.exists():
            raise FileNotFoundError(f"Asset not found: {asset_path}")

        cmd = [
            "gh",
            "release",
            "upload",
            release_name,
            str(asset_path),
            "--repo",
            self.target_repo,
            "--clobber",  # Replace if exists
        ]

        if dry_run:
            print(f"[DRY RUN] Would execute: {' '.join(cmd)}")
            return

        try:
            subprocess.run(cmd, capture_output=True, check=True, text=True)
        except subprocess.CalledProcessError as e:
            raise GitHubCLIError(
                f"Failed to upload {asset_path.name} to {release_name}: {e.stderr}"
            ) from e

    def asset_exists(self, release_name: str, asset_name: str) -> bool:
        """Check if an asset exists on a release.

        Args:
            release_name: Release tag name
            asset_name: Asset filename

        Returns:
            True if asset exists, False otherwise
        """
        try:
            assets = self.get_release_assets(release_name)
            return asset_name in assets
        except GitHubCLIError:
            return False
