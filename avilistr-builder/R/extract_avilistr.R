#' Extract Avibase ID Mappings
#'
#' Extracts the avilistr mapping data and exports to CSV format.
#' The avilistr package provides mappings between different taxonomic
#' authorities (IOC, Clements, eBird, etc.) via stable Avibase IDs.
#'
#' @param output_path Character. Path to output CSV file.
#' @param authorities Character vector. Which taxonomic authorities to include.
#'   Default: c("ioc", "clements", "ebird")
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
    authorities = c("ioc", "clements", "ebird"),
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

  # Load the package and get the mapping data
  # The avilistr package provides the 'birdlist' dataset
  data("birdlist", package = "avilistr", envir = environment())

  if (!exists("birdlist")) {
    stop("Could not load 'birdlist' dataset from avilistr package", call. = FALSE)
  }

  if (verbose) {
    message(sprintf("Loaded %d species records", nrow(birdlist)))
  }

  # Convert to tibble for better handling
  mapping_data <- tibble::as_tibble(birdlist)

  # Select relevant columns based on authorities requested
  # Standard columns: scientific_name, avibase_id
  # Authority-specific columns: ioc_scientific_name, clements_scientific_name, etc.

  base_cols <- c("scientific_name", "avibase_id")

  # Build column selection based on authorities
  authority_cols <- character(0)
  if ("ioc" %in% authorities && "ioc_scientific_name" %in% names(mapping_data)) {
    authority_cols <- c(authority_cols, "ioc_scientific_name")
  }
  if ("clements" %in% authorities && "clements_scientific_name" %in% names(mapping_data)) {
    authority_cols <- c(authority_cols, "clements_scientific_name")
  }
  if ("ebird" %in% authorities && "ebird_scientific_name" %in% names(mapping_data)) {
    authority_cols <- c(authority_cols, "ebird_scientific_name")
  }

  # Select columns (only those that exist in the data)
  available_cols <- c(base_cols, authority_cols)
  available_cols <- available_cols[available_cols %in% names(mapping_data)]

  mapping_export <- dplyr::select(mapping_data, dplyr::all_of(available_cols))

  # Remove rows with missing avibase_id (critical field)
  mapping_export <- dplyr::filter(mapping_export, !is.na(avibase_id))

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

  # Validation checks
  checks <- list(
    file_exists = TRUE,
    row_count = nrow(data),
    has_avibase_id = "avibase_id" %in% names(data),
    has_scientific_name = "scientific_name" %in% names(data),
    has_ioc = "ioc_scientific_name" %in% names(data),
    missing_avibase = sum(is.na(data$avibase_id)),
    unique_avibase = length(unique(data$avibase_id)),
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
  cat("Avilistr Mapping Validation\n")
  cat("===========================\n\n")

  cat(sprintf("✓ File exists: %s\n", x$file_exists))
  cat(sprintf("✓ Row count: %d\n", x$row_count))
  cat(sprintf("✓ Has avibase_id column: %s\n", x$has_avibase_id))
  cat(sprintf("✓ Has scientific_name column: %s\n", x$has_scientific_name))
  cat(sprintf("✓ Has IOC mapping: %s\n", x$has_ioc))
  cat(sprintf("✓ Missing Avibase IDs: %d\n", x$missing_avibase))
  cat(sprintf("✓ Unique Avibase IDs: %d\n", x$unique_avibase))
  cat(sprintf("✓ Meets minimum species count: %s\n", x$meets_minimum))

  cat(sprintf(
    "\nOverall validation: %s\n",
    if (x$valid) "PASSED ✓" else "FAILED ✗"
  ))

  invisible(x)
}
