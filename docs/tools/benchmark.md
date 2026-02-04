# Density Analyzer Benchmark

Compare Rust vs R/auk implementations for eBird density analysis.

## Setup

### R/auk Setup

```bash
# Install R packages
R -e "install.packages(c('auk', 'h3', 'data.table', 'jsonlite', 'argparse'))"

# Make script executable
chmod +x analyze_density.R
```

### Rust Setup

```bash
cd ../ebird-density-analyzer
cargo build --release
```

## Benchmark Test

Use a sample of the EBD for initial testing:

```bash
# Create sample data (first 100k records)
head -n 100000 /Volumes/backup/ebird/ebd_relAug-2025.txt > sample_100k.txt

# Run R/auk implementation
time Rscript analyze_density.R \
  --ebd sample_100k.txt \
  --output results_r/ \
  --resolutions 2,3,4,5

# Run Rust implementation
time ../ebird-density-analyzer/target/release/ebird-density-analyzer \
  --input sample_100k.txt \
  --resolutions 2,3,4,5 \
  --output results_rust/

# Compare results
diff -u results_r/global_density_res4.json results_rust/global_density_res4.json
```

## Memory Usage Test

```bash
# Monitor peak memory usage (macOS)
/usr/bin/time -l Rscript analyze_density.R \
  --ebd sample_100k.txt \
  --output results_r/

/usr/bin/time -l ../ebird-density-analyzer/target/release/ebird-density-analyzer \
  --input sample_100k.txt \
  --output results_rust/

# Look for "maximum resident set size" in output
```

## Full EBD Test

⚠️ **WARNING**: This will process ~200GB of data and take hours.

```bash
# R/auk (recommended approach)
time Rscript analyze_density.R \
  --ebd /Volumes/backup/ebird/ebd_relAug-2025.txt \
  --output results_r_full/ \
  --resolutions 2,3,4,5

# Rust (may require high RAM)
time ../ebird-density-analyzer/target/release/ebird-density-analyzer \
  --input /Volumes/backup/ebird/ebd_relAug-2025.tar.gz \
  --resolutions 2,3,4,5 \
  --output results_rust_full/
```

## Regional Test (Recommended)

Process regions separately to reduce memory:

```bash
# North America West Coast
time Rscript analyze_density.R \
  --ebd /Volumes/backup/ebird/ebd_relAug-2025.txt \
  --output results_na_west/ \
  --bbox 32.5,49.0,-125.0,-115.0 \
  --resolutions 2,3,4,5

# Compare with Rust
time ../ebird-density-analyzer/target/release/ebird-density-analyzer \
  --input /Volumes/backup/ebird/ebd_relAug-2025.tar.gz \
  --bbox 32.5,49.0,-125.0,-115.0 \
  --resolutions 2,3,4,5 \
  --output results_na_west_rust/
```

## Metrics to Compare

| Metric | R/auk | Rust | Winner |
|--------|-------|------|--------|
| **Time (100k records)** | ? | ? | ? |
| **Memory (100k records)** | ? | ? | ? |
| **Time (full EBD)** | ? | ? | ? |
| **Memory (full EBD)** | ? | ? | ? |
| **Setup complexity** | Medium (R packages) | Low (single binary) | Rust |
| **Code maintainability** | High (domain-specific) | Medium (custom) | R |
| **Deployment** | Medium (needs R runtime) | Easy (single binary) | Rust |

## Expected Results

**R/auk advantages:**
- Faster filtering (AWK-based)
- Mature, battle-tested on full EBD
- Memory-efficient with `data.table`

**Rust advantages:**
- Single binary deployment
- No R runtime dependency
- Type safety
- Potential for parallelization

## Decision Criteria

Keep Rust if:
- ✅ Performance within 2x of R/auk
- ✅ Memory usage reasonable (< 32GB for full EBD)
- ✅ Results match R/auk output

Switch to R/auk if:
- ❌ Rust is >3x slower
- ❌ Rust requires excessive memory
- ❌ Results don't match

Hybrid approach:
- Use R/auk for initial density analysis (one-time per EBD release)
- Keep Rust for pack generation and distribution tools
