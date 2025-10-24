"""Command-line interface for release publisher."""

from pathlib import Path

import click
from rich.console import Console

from .attribution import get_default_attribution
from .github import GitHubClient, GitHubCLIError
from .manifest import load_manifest
from .uploader import upload_all_bundles, update_manifest_with_urls, upload_manifest_release

console = Console()


@click.command()
@click.option(
    "--manifest",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to pack_manifest.json",
)
@click.option(
    "--db-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Directory containing .db files",
)
@click.option(
    "--target-repo",
    type=str,
    required=True,
    help="Target GitHub repository (owner/repo)",
)
@click.option(
    "--workers",
    type=int,
    default=8,
    help="Number of concurrent upload workers (default: 8)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be done without actually doing it",
)
@click.option(
    "--skip-manifest",
    is_flag=True,
    help="Skip uploading the global manifest release",
)
def main(
    manifest: Path,
    db_dir: Path,
    target_repo: str,
    workers: int,
    dry_run: bool,
    skip_manifest: bool,
):
    """Publish eBird region packs to GitHub releases using bundled releases.

    This tool automates the process of:
    1. Grouping region packs into ≤1950MB bundles
    2. Creating GitHub releases for each bundle
    3. Uploading .db.gz files as release assets
    4. Updating manifest with download URLs
    5. Uploading the updated manifest release

    The tool is idempotent - it will skip releases and assets that already exist,
    making it safe to run multiple times and resume from failures.

    Examples:

        # Dry run to see what would happen
        release-publisher \\
            --manifest pack_manifest.json \\
            --db-dir ./region-packs/ \\
            --target-repo owner/birdnetpi-ebird-packs \\
            --dry-run

        # Actual upload with 16 workers
        release-publisher \\
            --manifest pack_manifest.json \\
            --db-dir ./region-packs/ \\
            --target-repo owner/birdnetpi-ebird-packs \\
            --workers 16
    """
    console.print("[bold cyan]eBird Region Pack Release Publisher[/bold cyan]\n")

    if dry_run:
        console.print("[yellow]🔍 DRY RUN MODE - No changes will be made[/yellow]\n")

    try:
        # Load and validate manifest
        console.print(f"📄 Loading manifest from {manifest}")
        pack_manifest = load_manifest(manifest)
        console.print(f"  Found {len(pack_manifest.regions)} regions\n")

        # Initialize GitHub client
        console.print(f"🔧 Initializing GitHub client for {target_repo}")
        github = GitHubClient(target_repo)
        console.print("  ✓ gh CLI authenticated\n")

        # Upload bundled releases
        stats, download_urls = upload_all_bundles(
            manifest=pack_manifest,
            github=github,
            db_dir=db_dir,
            workers=workers,
            dry_run=dry_run,
        )

        # Update manifest with download URLs
        if not dry_run:
            updated_manifest_path = manifest.parent / f"{manifest.stem}_with_urls.json"
            update_manifest_with_urls(pack_manifest, download_urls, updated_manifest_path)
        else:
            updated_manifest_path = manifest
            console.print("\n[yellow]Skipping manifest update in dry-run mode[/yellow]")

        # Upload manifest release
        if not skip_manifest:
            attribution = get_default_attribution()
            upload_manifest_release(
                manifest_path=updated_manifest_path,
                github=github,
                attribution=attribution,
                dry_run=dry_run,
            )

        # Print summary
        console.print("\n[bold]📊 Summary[/bold]")
        console.print(f"  Bundles created: {stats.releases_created}")
        console.print(f"  Bundles skipped: {stats.releases_skipped}")
        if not dry_run:
            console.print(f"  Regions with download URLs: {len(download_urls)}")

        if stats.errors:
            console.print(f"\n[bold red]❌ {len(stats.errors)} errors occurred:[/bold red]")
            for error in stats.errors:
                console.print(f"  • {error}")
            raise click.ClickException("Upload completed with errors")

        console.print("\n[bold green]✅ Upload complete![/bold green]")

    except FileNotFoundError as e:
        raise click.ClickException(f"File not found: {e}")
    except GitHubCLIError as e:
        raise click.ClickException(f"GitHub CLI error: {e}")
    except Exception as e:
        raise click.ClickException(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
