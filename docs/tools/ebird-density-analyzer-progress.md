# Progress Feedback in Two-Pass Mode

When running in `--two-pass` mode, the analyzer provides detailed progress feedback through three phases.

## TUI Mode (Terminal User Interface)

Add the `--tui` flag for an enhanced visual interface with:
- **Fixed progress bar at top** showing phase, metrics, and elapsed time
- **Scrollable log window** with color-coded messages (INFO=green, WARN=yellow, ERROR=red)
- **Real-time updates** every 1,000 records (Pass 1) / 10,000 lines (Pass 2)
- Press **'q'** to quit the TUI display

```bash
ebird-density-analyzer \
    --input sample.tsv \
    --resolutions 2,3,4,5 \
    --output results/ \
    --two-pass \
    --temp-dir /tmp/temp/ \
    --tui
```

When TUI mode is not enabled, progress is displayed as text logs (see below).

## Text Mode (Default)

When running in `--two-pass` mode without TUI, the analyzer provides detailed progress feedback through three phases:

## Phase 1: Extract Pairs (~40% of total time)

**What happens**: Reads input file, applies quality filters, converts to H3 cells, writes pairs to disk

**Progress display**:
```
⠋ [00:00:12] Pass 1:    100,000 records read |    340,740 pairs written |     14,815 filtered
```

- Updates every 1,000 records processed
- Shows total records read, pairs written (4× records for 4 resolutions), and filtered count
- Animated spinner indicates active processing

## Phase 2: Sort Pairs (~40% of total time)

**What happens**: External sort using system `sort` command with 4 cores and 2GB buffer

**Progress display**:
```
[INFO] Sorting pairs file (22.5 MB) - this may take several minutes...
[INFO] Note: System sort does not provide progress feedback
[INFO] Expected time: ~1-2 minutes per GB on network storage
```

- No progress bar (limitation of system sort command)
- Time estimates based on file size
- Typically ~1-2 minutes per GB on network storage
- Faster on local SSD (~10-20 seconds per GB)

## Phase 3: Aggregate (~20% of total time)

**What happens**: Streams through sorted pairs, counts unique checklists per cell

**Progress display**:
```
⠙ [00:00:03] [########################################] 22.5MB/22.5MB (100%) | 340,740 lines | 33,046 unique cells
```

- Progress bar based on bytes read from sorted file
- Updates every 100,000 lines
- Shows lines processed and unique cells discovered
- Animated spinner + percentage complete

## Example Full Run (100k records)

```bash
$ ebird-density-analyzer \
    --input sample_100k.tsv \
    --resolutions 2,3,4,5 \
    --output results/ \
    --two-pass \
    --temp-dir /Volumes/backup/ebird/temp/

[INFO] Analyzing eBird data from "sample_100k.tsv" at resolutions [2, 3, 4, 5]
[INFO] Sample rate: 100.0%
[INFO] Mode: Two-pass (memory-efficient)
[INFO] Temp directory: "/Volumes/backup/ebird/temp/"

[INFO] Pass 1: Extracting (resolution, cell, checklist_id) pairs
⠋ [00:00:12] Pass 1:    100,000 records read |    340,740 pairs written |     14,815 filtered
[INFO] Pass 1 complete: 100,000 records read, 340,740 pairs written, 14,815 filtered
[INFO] Pairs file: 22,500,184 bytes

[INFO] Sorting pairs file (22.5 MB) - this may take several minutes...
[INFO] Note: System sort does not provide progress feedback
[INFO] Expected time: ~1-2 minutes per GB on network storage
[INFO] Sorting complete: 22.5 MB → /Volumes/backup/ebird/temp/pairs_sorted.csv

[INFO] Pass 2: Aggregating sorted pairs
⠙ [00:00:03] [########################################] 22.5MB/22.5MB (100%) | 340,740 lines | 33,046 unique cells
[INFO] Pass 2 complete: 340,740 lines processed, 33,046 unique cells found

[INFO] Writing report for resolution 2 (1,139 cells with data)
[INFO]   Resolution 2: 1,139 cells, 83,304 total checklists, 73 avg/cell
...

[INFO] Done! Reports written to "results/"
```

## Full EBD Estimates (~1 billion records)

### Time Breakdown
- **Pass 1**: 2-3 hours (reading, filtering, writing pairs)
- **Sort**: 1-2 hours (external sort of ~225GB file)
- **Pass 2**: 1 hour (aggregating sorted data)
- **Total**: 5-6 hours

### Progress Updates
- Pass 1: Update every 1M records (visual feedback every 30-60 seconds)
- Sort: No progress (system limitation), but logs time estimate
- Pass 2: Update every 10M lines (visual feedback every 30-60 seconds)

### Disk Usage
- Pairs file: ~225 GB
- Sorted file: ~225 GB
- Peak usage: ~450 GB (during sort)
- Cleaned up automatically after completion

### Memory Usage
- Constant ~10-50 MB regardless of dataset size
- Sort uses 2GB buffer (configurable)

## Tips for Long Runs

1. **Use `nohup` or `tmux`** for long-running jobs:
   ```bash
   nohup ebird-density-analyzer --input /path/to/ebd.tar.gz --two-pass > output.log 2>&1 &
   ```

2. **Monitor progress** from another terminal:
   ```bash
   tail -f output.log
   ```

3. **Check temp directory** to see file growth:
   ```bash
   watch -n 10 'ls -lh /Volumes/backup/ebird/temp/'
   ```

4. **Network storage**: Expect slower speeds but same accuracy
   - Local SSD: ~5-10x faster
   - Network storage: More capacity, suitable for overnight runs
