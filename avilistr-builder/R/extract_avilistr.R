#' Extract Avibase ID Mappings
#'
#' Extracts the avilistr mapping data and exports to CSV format.
#' The avilistr package (v2025) provides the AviList Global Avian Checklist
#' with stable Avibase IDs and cross-references to major authorities.
#'
#' @param output_path Character. Path to output CSV file.
#' @param include_urls Logical. Include Birds of the World URLs. Default: TRUE
#' @param verbose Logical. Print progress messages. Default: TRUE
#'
#' @return Invisible. Writes CSV file to output_path.
#' @export
#'
#' @examples
#' \dontrun{
#' extract_avilistr_mapping("../shared/avilistr/avilistr_mapping.csv")
#' }
extract_avilistr_mapping <- function(
    output_path = "../shared/avilistr/avilistr_mapping.csv",
    include_urls = TRUE,
    verbose = TRUE) {
  # Check if avilistr is installed
  if (!requireNamespace("avilistr", quietly = TRUE)) {
    stop(
      "Package 'avilistr' is required but not installed.\n",
      "Install it with: install.packages('avilistr')",
      call. = FALSE
    )
  }

  if (verbose) {
    message("Loading avilistr package...")
  }

  # Load the AviList 2025 dataset
  data("avilist_2025", package = "avilistr", envir = environment())

  if (!exists("avilist_2025")) {
    stop("Could not load 'avilist_2025' dataset from avilistr package", call. = FALSE)
  }

  if (verbose) {
    message(sprintf("Loaded %d records from AviList 2025", nrow(avilist_2025)))
  }

  # Convert to tibble for better handling
  mapping_data <- tibble::as_tibble(avilist_2025)

  # Filter to species level only (exclude orders, families, genera)
  mapping_data <- dplyr::filter(mapping_data, Taxon_rank == "species")

  if (verbose) {
    message(sprintf("Filtered to %d species-level records", nrow(mapping_data)))
  }

  # Select relevant columns
  base_cols <- c(
    "Scientific_name",
    "AvibaseID",
    "English_name_AviList",
    "English_name_Clements_v2024",
    "Species_code_Cornell_Lab"
  )

  # Add URLs if requested
  if (include_urls) {
    base_cols <- c(base_cols, "Birds_of_the_World_URL")
  }

  # Select columns (only those that exist in the data)
  available_cols <- base_cols[base_cols %in% names(mapping_data)]

  mapping_export <- dplyr::select(mapping_data, dplyr::all_of(available_cols))

  # Remove rows with missing AvibaseID (critical field)
  mapping_export <- dplyr::filter(mapping_export, !is.na(AvibaseID))

  if (verbose) {
    message(sprintf("Filtered to %d species with valid Avibase IDs", nrow(mapping_export)))
  }

  # Create output directory if it doesn't exist
  output_dir <- dirname(output_path)
  if (!dir.exists(output_dir)) {
    if (verbose) {
      message(sprintf("Creating directory: %s", output_dir))
    }
    dir.create(output_dir, recursive = TRUE)
  }

  # Write to CSV
  if (verbose) {
    message(sprintf("Writing to: %s", output_path))
  }

  readr::write_csv(mapping_export, output_path)

  if (verbose) {
    message("✓ Export complete!")
  }

  invisible(mapping_export)
}


#' Get Avilistr Package Information
#'
#' Returns version and metadata about the installed avilistr package.
#'
#' @return List with package information
#' @export
get_avilistr_info <- function() {
  if (!requireNamespace("avilistr", quietly = TRUE)) {
    return(list(
      installed = FALSE,
      version = NA,
      message = "avilistr package not installed"
    ))
  }

  pkg_version <- as.character(packageVersion("avilistr"))

  list(
    installed = TRUE,
    version = pkg_version,
    description = utils::packageDescription("avilistr")$Description
  )
}


#' Validate Avilistr Mapping Data
#'
#' Checks the extracted mapping data for completeness and quality.
#'
#' @param csv_path Character. Path to CSV file to validate.
#' @param min_species Integer. Minimum expected number of species. Default: 10000
#'
#' @return List with validation results
#' @export
validate_mapping <- function(csv_path, min_species = 10000) {
  if (!file.exists(csv_path)) {
    stop(sprintf("File not found: %s", csv_path), call. = FALSE)
  }

  data <- readr::read_csv(csv_path, show_col_types = FALSE)

  # Check for required columns
  has_avibase_id <- "AvibaseID" %in% names(data)
  has_scientific_name <- "Scientific_name" %in% names(data)
  has_bow_url <- "Birds_of_the_World_URL" %in% names(data)

  # Validation checks
  checks <- list(
    file_exists = TRUE,
    row_count = nrow(data),
    has_avibase_id = has_avibase_id,
    has_scientific_name = has_scientific_name,
    has_bow_url = has_bow_url,
    missing_avibase = if (has_avibase_id) sum(is.na(data$AvibaseID)) else NA,
    unique_avibase = if (has_avibase_id) length(unique(data$AvibaseID)) else 0,
    meets_minimum = nrow(data) >= min_species
  )

  # Overall validation
  checks$valid <- all(
    checks$has_avibase_id,
    checks$has_scientific_name,
    checks$missing_avibase == 0,
    checks$meets_minimum
  )

  class(checks) <- c("avilistr_validation", "list")
  checks
}


#' Print Validation Results
#'
#' @param x A validation object from validate_mapping()
#' @param ... Additional arguments (unused)
#'
#' @export
print.avilistr_validation <- function(x, ...) {
  cat("Avilistr Mapping Validation (AviList 2025)\n")
  cat("==========================================\n\n")

  cat(sprintf("✓ File exists: %s\n", x$file_exists))
  cat(sprintf("✓ Row count: %d\n", x$row_count))
  cat(sprintf("✓ Has AvibaseID column: %s\n", x$has_avibase_id))
  cat(sprintf("✓ Has Scientific_name column: %s\n", x$has_scientific_name))
  cat(sprintf("✓ Has Birds of the World URL: %s\n", x$has_bow_url))
  cat(sprintf("✓ Missing Avibase IDs: %d\n", x$missing_avibase))
  cat(sprintf("✓ Unique Avibase IDs: %d\n", x$unique_avibase))
  cat(sprintf("✓ Meets minimum species count: %s\n", x$meets_minimum))

  cat(sprintf(
    "\nOverall validation: %s\n",
    if (x$valid) "PASSED ✓" else "FAILED ✗"
  ))

  invisible(x)
}
