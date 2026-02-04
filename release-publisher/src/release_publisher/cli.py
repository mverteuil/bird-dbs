"""Command-line interface for release publisher."""

from pathlib import Path

import click
from rich.console import Console

from .attribution import get_default_attribution
from .github import GitHubClient, GitHubCLIError
from .manifest import load_registry
from .uploader import update_registry_with_urls, upload_all_bundles, upload_registry_release

console = Console()


@click.command()
@click.option(
    "--registry",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to pack_registry.json",
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
    "--skip-registry",
    is_flag=True,
    help="Skip uploading the global registry release",
)
def main(
    registry: Path,
    db_dir: Path,
    target_repo: str,
    workers: int,
    dry_run: bool,
    skip_registry: bool,
):
    """Publish eBird region packs to GitHub releases using bundled releases.

    This tool automates the process of:
    1. Grouping region packs into ≤1950MB bundles
    2. Creating GitHub releases for each bundle
    3. Uploading .db.gz files as release assets
    4. Updating registry with download URLs
    5. Uploading the updated registry release

    The tool is idempotent - it will skip releases and assets that already exist,
    making it safe to run multiple times and resume from failures.

    Examples:

        # Dry run to see what would happen
        release-publisher \\
            --registry pack_registry.json \\
            --db-dir ./region-packs/ \\
            --target-repo owner/birdnetpi-ebird-packs \\
            --dry-run

        # Actual upload with 16 workers
        release-publisher \\
            --registry pack_registry.json \\
            --db-dir ./region-packs/ \\
            --target-repo owner/birdnetpi-ebird-packs \\
            --workers 16
    """
    console.print("[bold cyan]eBird Region Pack Release Publisher[/bold cyan]\n")

    if dry_run:
        console.print("[yellow]🔍 DRY RUN MODE - No changes will be made[/yellow]\n")

    try:
        # Load and validate registry
        console.print(f"📄 Loading registry from {registry}")
        pack_registry = load_registry(registry)
        console.print(f"  Found {len(pack_registry.regions)} regions\n")

        # Initialize GitHub client
        console.print(f"🔧 Initializing GitHub client for {target_repo}")
        github = GitHubClient(target_repo)
        console.print("  ✓ gh CLI authenticated\n")

        # Upload bundled releases
        stats, download_urls = upload_all_bundles(
            registry=pack_registry,
            github=github,
            db_dir=db_dir,
            workers=workers,
            dry_run=dry_run,
        )

        # Update registry with download URLs
        if not dry_run:
            updated_registry_path = registry.parent / f"{registry.stem}_with_urls.json"
            update_registry_with_urls(pack_registry, download_urls, updated_registry_path)
        else:
            updated_registry_path = registry
            console.print("\n[yellow]Skipping registry update in dry-run mode[/yellow]")

        # Upload registry release
        if not skip_registry:
            attribution = get_default_attribution()
            upload_registry_release(
                registry_path=updated_registry_path,
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
