#!/bin/bash
# Convert eBird tarball to Parquet using named pipe (no disk space needed)

set -euo pipefail

TARBALL="/Volumes/backup/ebird/ebd_relAug-2025.tar"
OUTPUT="/Volumes/Lightroom/ebird.parquet"
FIFO="/tmp/ebird_stream.txt.gz"

# Clean up on exit
cleanup() {
    rm -f "$FIFO"
}
trap cleanup EXIT

# Create named pipe
mkfifo "$FIFO"

echo "Creating named pipe: $FIFO"
echo "Input tarball: $TARBALL"
echo "Output: $OUTPUT"
echo ""
echo "Starting conversion..."
echo "This will stream: tar -> gzip -> DuckDB -> Parquet"
echo ""

# Start DuckDB in background reading from pipe
uv run "$(dirname "$0")/convert_ebird_duckdb.py" --input "$FIFO" --output "$OUTPUT" &
DUCKDB_PID=$!

# Extract from tarball to pipe (blocks until DuckDB reads)
tar -xOf "$TARBALL" > "$FIFO"

# Wait for DuckDB to finish
wait $DUCKDB_PID

echo "✓ Done!"
