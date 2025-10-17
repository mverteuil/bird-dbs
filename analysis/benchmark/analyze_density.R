#!/usr/bin/env Rscript
#
# eBird Density Analyzer - R/auk implementation
# Benchmark against Rust implementation
#
# Usage:
#   Rscript analyze_density.R --ebd /path/to/ebd.txt --output density_reports/
#

library(auk)
library(h3r)
library(data.table)
library(jsonlite)
library(argparse)

# Parse command-line arguments
parser <- ArgumentParser(description = "Analyze eBird density using auk")
parser$add_argument("--ebd", required = TRUE, help = "Path to eBird Basic Dataset file")
parser$add_argument("--output", required = TRUE, help = "Output directory for reports")
parser$add_argument("--resolutions", default = "2,3,4,5", help = "H3 resolutions (comma-separated)")
parser$add_argument("--sample-rate", type = "double", default = 1.0, help = "Sample rate (0.0-1.0)")
parser$add_argument("--bbox", default = NULL, help = "Bounding box: min_lat,max_lat,min_lon,max_lon")

args <- parser$parse_args()

# Parse resolutions
resolutions <- as.integer(strsplit(args$resolutions, ",")[[1]])

# Parse bounding box if provided
bbox <- NULL
if (!is.null(args$bbox)) {
  bbox_values <- as.numeric(strsplit(args$bbox, ",")[[1]])
  if (length(bbox_values) != 4) {
    stop("Bounding box must have 4 values: min_lat,max_lat,min_lon,max_lon")
  }
  bbox <- list(
    min_lat = bbox_values[1],
    max_lat = bbox_values[2],
    min_lon = bbox_values[3],
    max_lon = bbox_values[4]
  )
}

# Create output directory
dir.create(args$output, showWarnings = FALSE, recursive = TRUE)

# Start timing
start_time <- Sys.time()

cat("eBird Density Analyzer (R/auk)\n")
cat("==============================\n")
cat(sprintf("Input: %s\n", args$ebd))
cat(sprintf("Resolutions: %s\n", paste(resolutions, collapse = ", ")))
cat(sprintf("Sample rate: %.1f%%\n", args$sample_rate * 100))

# Step 1: Filter EBD with auk (AWK-based, very fast)
cat("\n[1/3] Filtering EBD with auk...\n")

ebd <- auk_ebd(args$ebd)

# Apply filters
ebd_filtered <- ebd %>%
  auk_complete() %>%  # Complete checklists only
  auk_filter(
    file = tempfile(fileext = ".txt"),
    overwrite = TRUE
  )

filter_time <- Sys.time()
cat(sprintf("  Filtering completed in %.1f seconds\n",
            as.numeric(difftime(filter_time, start_time, units = "secs"))))

# Step 2: Read filtered data
cat("\n[2/3] Reading filtered data...\n")

# Read with data.table (fast)
dt <- fread(ebd_filtered$output,
            select = c("SCIENTIFIC NAME", "LATITUDE", "LONGITUDE",
                       "OBSERVATION DATE", "SAMPLING EVENT IDENTIFIER",
                       "GROUP IDENTIFIER", "ALL SPECIES REPORTED",
                       "APPROVED", "CATEGORY", "EXOTIC CODE"),
            na.strings = "")

read_time <- Sys.time()
cat(sprintf("  Read %s records in %.1f seconds\n",
            format(nrow(dt), big.mark = ","),
            as.numeric(difftime(read_time, filter_time, units = "secs"))))

# Apply additional filters
dt <- dt[APPROVED == 1 &
         (is.na(CATEGORY) | CATEGORY == "species") &
         (is.na(`EXOTIC CODE`) | `EXOTIC CODE` == "")]

# Apply bounding box if provided
if (!is.null(bbox)) {
  dt <- dt[LATITUDE >= bbox$min_lat & LATITUDE <= bbox$max_lat &
           LONGITUDE >= bbox$min_lon & LONGITUDE <= bbox$max_lon]
  cat(sprintf("  Bounding box filter: %s records remaining\n",
              format(nrow(dt), big.mark = ",")))
}

# Sampling
if (args$sample_rate < 1.0) {
  dt <- dt[sample(.N, size = .N * args$sample_rate)]
  cat(sprintf("  Sampling at %.1f%%: %s records\n",
              args$sample_rate * 100,
              format(nrow(dt), big.mark = ",")))
}

# Step 3: Aggregate by H3 cells
cat("\n[3/3] Aggregating by H3 cells...\n")

for (res in resolutions) {
  cat(sprintf("\n  Processing resolution %d...\n", res))

  # Convert to H3 cells
  dt_res <- copy(dt)
  dt_res[, h3_cell := latLngToCell(LATITUDE, LONGITUDE, res)]

  # Get checklist ID (prefer GROUP IDENTIFIER, fallback to SAMPLING EVENT)
  dt_res[, checklist_id := ifelse(is.na(`GROUP IDENTIFIER`) | `GROUP IDENTIFIER` == "",
                                   `SAMPLING EVENT IDENTIFIER`,
                                   `GROUP IDENTIFIER`)]

  # Aggregate by cell
  density <- dt_res[, .(
    unique_checklists = uniqueN(checklist_id),
    complete_checklists = sum(`ALL SPECIES REPORTED` == 1, na.rm = TRUE),
    total_observations = .N,
    date_range_start = min(`OBSERVATION DATE`, na.rm = TRUE),
    date_range_end = max(`OBSERVATION DATE`, na.rm = TRUE),
    center_lat = mean(LATITUDE),
    center_lon = mean(LONGITUDE)
  ), by = h3_cell]

  # Estimate pack size (same formula as Rust)
  estimate_pack_size <- function(complete_checklists) {
    BYTES_PER_SPECIES_RECORD <- 400
    AVG_SPECIES_PER_HEX <- 150
    COMPRESSION_RATIO <- 0.7

    # Determine data resolution
    data_res <- ifelse(complete_checklists >= 10000, 7,
                      ifelse(complete_checklists >= 5000, 6,
                            ifelse(complete_checklists >= 2000, 5, 5)))

    # Calculate size
    resolution_diff <- data_res - res
    num_data_hexagons <- 7^resolution_diff
    total_species_records <- num_data_hexagons * AVG_SPECIES_PER_HEX
    raw_size_bytes <- total_species_records * BYTES_PER_SPECIES_RECORD
    compressed_size_mb <- (raw_size_bytes * COMPRESSION_RATIO) / 1000000

    list(size_mb = compressed_size_mb, data_res = data_res)
  }

  # Add pack size estimates
  density[, c("estimated_pack_size_mb", "recommended_data_resolution") := {
    results <- lapply(complete_checklists, estimate_pack_size)
    list(
      sapply(results, function(x) x$size_mb),
      sapply(results, function(x) x$data_res)
    )
  }]

  # Convert to JSON format matching Rust output
  report <- list(
    resolution = res,
    cells = lapply(1:nrow(density), function(i) {
      list(
        h3_cell = as.character(density$h3_cell[i]),
        center_lat = density$center_lat[i],
        center_lon = density$center_lon[i],
        unique_checklists = density$unique_checklists[i],
        complete_checklists = density$complete_checklists[i],
        total_observations = density$total_observations[i],
        date_range_start = density$date_range_start[i],
        date_range_end = density$date_range_end[i],
        estimated_pack_size_mb = density$estimated_pack_size_mb[i],
        recommended_data_resolution = density$recommended_data_resolution[i]
      )
    })
  )

  # Write JSON report
  output_file <- file.path(args$output, sprintf("global_density_res%d.json", res))
  write_json(report, output_file, pretty = TRUE, auto_unbox = TRUE)

  cat(sprintf("    Resolution %d: %s cells, %s total checklists\n",
              res,
              format(nrow(density), big.mark = ","),
              format(sum(density$unique_checklists), big.mark = ",")))
}

# Summary
end_time <- Sys.time()
total_time <- as.numeric(difftime(end_time, start_time, units = "secs"))

cat("\n==============================\n")
cat(sprintf("Total time: %.1f seconds (%.1f minutes)\n", total_time, total_time / 60))
cat(sprintf("Output directory: %s\n", args$output))
cat("\nDone!\n")
