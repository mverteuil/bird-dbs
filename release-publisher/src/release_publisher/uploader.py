"""Concurrent release creation and asset upload logic using bundled releases."""

import json
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
)

from .attribution import EBirdAttribution, get_default_attribution
from .bundler import ReleaseBundle, RegionFile, build_release_bundles
from .github import GitHubClient, GitHubCLIError
from .manifest import PackManifest

console = Console()


class UploadStats:
    """Track upload statistics."""

    def __init__(self):
        self.releases_created = 0
        self.releases_skipped = 0
        self.assets_uploaded = 0
        self.assets_skipped = 0
        self.errors: list[str] = []


def process_bundle_release(
    bundle: ReleaseBundle,
    github: GitHubClient,
    attribution: EBirdAttribution,
    dry_run: bool,
    progress: Progress,
    task_id: TaskID,
) -> tuple[str, Dict[str, str], bool, str | None]:
    """Process a single bundle: create release and upload all region packs.

    Args:
        bundle: Release bundle containing region files
        github: GitHub client
        attribution: eBird attribution
        dry_run: If True, simulate operations
        progress: Rich progress instance
        task_id: Task ID for progress updates

    Returns:
        Tuple of (release_name, download_urls_map, success, error_message)
        download_urls_map: Dict mapping region_id -> download_url
    """
    release_name = bundle.release_name
    download_urls: Dict[str, str] = {}

    try:
        # Step 1: Create release if it doesn't exist
        if github.release_exists(release_name):
            progress.console.print(
                f"  [yellow]Release {release_name} already exists, skipping creation[/yellow]"
            )
            release_created = False
        else:
            # Create bundle description listing all regions
            region_list = "\n".join(f"- {r.region_id}" for r in bundle.regions)
            description = f"""eBird Species Pack Bundle

This release contains {len(bundle.regions)} regional species packs:

{region_list}

Total size: {bundle.total_size_mb:.1f} MB

## Attribution

{attribution.citation}

See ATTRIBUTION.txt in each release for complete terms.
"""
            github.create_release(
                release_name=release_name,
                title=f"Species Pack Bundle {bundle.bundle_id:03d}",
                notes=description,
                dry_run=dry_run,
            )
            progress.console.print(f"  [green]✓ Created release {release_name}[/green]")
            release_created = True

        # Step 2: Upload all .db.gz files in this bundle
        for region_file in bundle.regions:
            db_file = region_file.file_path

            if github.asset_exists(release_name, db_file.name):
                progress.console.print(
                    f"  [yellow]Asset {db_file.name} already exists, skipping[/yellow]"
                )
            else:
                github.upload_asset(release_name, db_file, dry_run=dry_run)
                progress.console.print(
                    f"  [green]✓ Uploaded {db_file.name} ({region_file.size_mb:.1f} MB)[/green]"
                )

            # Record download URL
            if not dry_run:
                download_url = f"https://github.com/{github.repo}/releases/download/{release_name}/{db_file.name}"
                download_urls[region_file.region_id] = download_url

        # Step 3: Upload ATTRIBUTION.txt if not exists
        attribution_content = attribution.attribution_file_content()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, prefix="ATTRIBUTION_"
        ) as f:
            f.write(attribution_content)
            attribution_file = Path(f.name)

        try:
            if github.asset_exists(release_name, "ATTRIBUTION.txt"):
                progress.console.print(
                    "  [yellow]ATTRIBUTION.txt already exists, skipping[/yellow]"
                )
            else:
                github.upload_asset(release_name, attribution_file, dry_run=dry_run)
                progress.console.print("  [green]✓ Uploaded ATTRIBUTION.txt[/green]")
        finally:
            attribution_file.unlink(missing_ok=True)

        progress.update(task_id, advance=1)
        return release_name, download_urls, True, None

    except (GitHubCLIError, FileNotFoundError) as e:
        error_msg = f"{release_name}: {str(e)}"
        progress.console.print(f"  [red]✗ Error: {error_msg}[/red]")
        progress.update(task_id, advance=1)
        return release_name, {}, False, error_msg


def upload_all_bundles(
    manifest: PackManifest,
    github: GitHubClient,
    db_dir: Path,
    workers: int = 8,
    dry_run: bool = False,
    max_bundle_mb: int = 1950,
    version: str = "2025.08",
) -> tuple[UploadStats, Dict[str, str]]:
    """Upload all region packs using bundled releases.

    Args:
        manifest: Pack manifest
        github: GitHub client
        db_dir: Directory containing .db.gz files
        workers: Number of concurrent workers
        dry_run: If True, simulate operations
        max_bundle_mb: Maximum bundle size in MB
        version: Version string for release names

    Returns:
        Tuple of (UploadStats, download_urls_map)
    """
    stats = UploadStats()
    attribution = get_default_attribution()
    all_download_urls: Dict[str, str] = {}

    # Build release bundles
    bundles, region_to_release = build_release_bundles(manifest, db_dir, max_bundle_mb, version)

    console.print(f"\n[bold]Uploading {len(bundles)} bundle releases[/bold]")
    console.print(f"  Workers: {workers}")
    console.print(f"  Dry run: {dry_run}\n")

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Uploading bundles...", total=len(bundles))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    process_bundle_release,
                    bundle,
                    github,
                    attribution,
                    dry_run,
                    progress,
                    task,
                ): bundle
                for bundle in bundles
            }

            for future in as_completed(futures):
                release_name, download_urls, success, error = future.result()
                if success:
                    stats.releases_created += 1
                    all_download_urls.update(download_urls)
                else:
                    if error:
                        stats.errors.append(error)

    return stats, all_download_urls


def update_manifest_with_urls(
    manifest: PackManifest, download_urls: Dict[str, str], output_path: Path
) -> None:
    """Update manifest with download URLs and save to file.

    Args:
        manifest: Pack manifest to update
        download_urls: Dict mapping region_id -> download_url
        output_path: Path to save updated manifest
    """
    console.print(f"\n[bold]Updating manifest with download URLs[/bold]")

    # Update regions with download URLs
    updated_count = 0
    for region in manifest.regions:
        if region.region_id in download_urls:
            region.download_url = download_urls[region.region_id]
            updated_count += 1

    console.print(f"  Updated {updated_count} of {len(manifest.regions)} regions")

    # Save updated manifest
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(manifest.model_dump(), f, indent=2)

    console.print(f"  [green]✓ Saved updated manifest to {output_path}[/green]")


def upload_manifest_release(
    manifest_path: Path,
    github: GitHubClient,
    attribution: EBirdAttribution,
    version: str = "2025.08",
    dry_run: bool = False,
) -> None:
    """Create special manifest release and upload manifest JSON.

    Args:
        manifest_path: Path to pack_manifest.json (updated with download URLs)
        github: GitHub client
        attribution: eBird attribution
        version: Version string
        dry_run: If True, simulate operations

    Raises:
        GitHubCLIError: If upload fails
    """
    release_name = f"manifest-{version}"
    console.print(f"\n[bold]Creating manifest release: {release_name}[/bold]")

    # Create release if doesn't exist
    if github.release_exists(release_name):
        console.print(f"  [yellow]Release {release_name} already exists[/yellow]")
    else:
        description = f"""Region Pack Manifest

This manifest contains the complete list of all regional species packs and their download URLs.

Use this to programmatically discover available regions and download the appropriate species pack.

Data derived from:
{attribution.citation}
"""
        github.create_release(
            release_name=release_name,
            title="Region Pack Manifest",
            notes=description,
            dry_run=dry_run,
        )
        console.print(f"  [green]✓ Created manifest release[/green]")

    # Upload manifest JSON (always overwrite with latest)
    if github.asset_exists(release_name, manifest_path.name):
        console.print(
            f"  [yellow]Deleting existing {manifest_path.name} to upload fresh version[/yellow]"
        )
        # Note: gh CLI doesn't have delete-asset, so we'd need to handle this via API
        # For now, just skip if exists
        console.print(
            f"  [yellow]{manifest_path.name} already exists, skipping (manual deletion required)[/yellow]"
        )
    else:
        github.upload_asset(release_name, manifest_path, dry_run=dry_run)
        console.print(f"  [green]✓ Uploaded {manifest_path.name}[/green]")
