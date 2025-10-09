# Tests for extract_avilistr.R

test_that("extract_avilistr_mapping creates output file", {
  skip_if_not_installed("avilistr")

  output_file <- tempfile(fileext = ".csv")

  result <- extract_avilistr_mapping(
    output_path = output_file,
    verbose = FALSE
  )

  expect_true(file.exists(output_file))
  expect_s3_class(result, "tbl_df")
  expect_true("AvibaseID" %in% names(result))
  expect_true(nrow(result) > 0)

  unlink(output_file)
})


test_that("extract_avilistr_mapping includes expected columns", {
  skip_if_not_installed("avilistr")

  output_file <- tempfile(fileext = ".csv")

  # Extract with default settings
  result <- extract_avilistr_mapping(
    output_path = output_file,
    verbose = FALSE
  )

  # Should have AvibaseID and Scientific_name at minimum
  expect_true("AvibaseID" %in% names(result))
  expect_true("Scientific_name" %in% names(result))
  expect_true("English_name_AviList" %in% names(result))

  unlink(output_file)
})


test_that("extract_avilistr_mapping removes NA avibase_id rows", {
  skip_if_not_installed("avilistr")

  output_file <- tempfile(fileext = ".csv")

  result <- extract_avilistr_mapping(
    output_path = output_file,
    verbose = FALSE
  )

  # Check that no NA AvibaseIDs remain
  expect_true(all(!is.na(result$AvibaseID)))

  unlink(output_file)
})


test_that("extract_avilistr_mapping creates output directory if needed", {
  skip_if_not_installed("avilistr")

  temp_dir <- tempfile()
  output_file <- file.path(temp_dir, "nested", "output.csv")

  expect_false(dir.exists(dirname(output_file)))

  result <- extract_avilistr_mapping(
    output_path = output_file,
    verbose = FALSE
  )

  expect_true(file.exists(output_file))
  expect_true(dir.exists(dirname(output_file)))

  unlink(temp_dir, recursive = TRUE)
})


test_that("extract_avilistr_mapping verbose mode works", {
  skip_if_not_installed("avilistr")

  output_file <- tempfile(fileext = ".csv")

  # Capture messages with verbose = TRUE
  expect_message(
    extract_avilistr_mapping(
      output_path = output_file,
      verbose = TRUE
    ),
    "Loading avilistr package"
  )

  unlink(output_file)
})


test_that("get_avilistr_info returns correct structure when installed", {
  skip_if_not_installed("avilistr")

  info <- get_avilistr_info()

  expect_type(info, "list")
  expect_true(info$installed)
  expect_type(info$version, "character")
  expect_true(nchar(info$version) > 0)
  expect_true(!is.null(info$description))
})


test_that("validate_mapping detects valid CSV file", {
  skip_if_not_installed("avilistr")

  # Create a valid test CSV
  test_data <- data.frame(
    AvibaseID = paste0("avibase-", 1:15000),
    Scientific_name = paste("Species", 1:15000),
    English_name_AviList = paste("Common Name", 1:15000),
    stringsAsFactors = FALSE
  )

  temp_file <- tempfile(fileext = ".csv")
  readr::write_csv(test_data, temp_file)

  validation <- validate_mapping(temp_file, min_species = 10000)

  expect_s3_class(validation, "avilistr_validation")
  expect_true(validation$valid)
  expect_true(validation$file_exists)
  expect_equal(validation$row_count, 15000)
  expect_true(validation$has_avibase_id)
  expect_true(validation$has_scientific_name)
  expect_equal(validation$missing_avibase, 0)
  expect_equal(validation$unique_avibase, 15000)
  expect_true(validation$meets_minimum)

  unlink(temp_file)
})


test_that("validate_mapping detects invalid CSV (missing columns)", {
  skip_if_not_installed("avilistr")

  # Create invalid test CSV (missing AvibaseID column)
  test_data <- data.frame(
    Scientific_name = paste("Species", 1:100),
    stringsAsFactors = FALSE
  )

  temp_file <- tempfile(fileext = ".csv")
  readr::write_csv(test_data, temp_file)

  validation <- validate_mapping(temp_file, min_species = 10)

  expect_false(validation$valid)
  expect_false(validation$has_avibase_id)

  unlink(temp_file)
})


test_that("validate_mapping detects invalid CSV (too few species)", {
  skip_if_not_installed("avilistr")

  # Create valid but small test CSV
  test_data <- data.frame(
    AvibaseID = paste0("avibase-", 1:50),
    Scientific_name = paste("Species", 1:50),
    stringsAsFactors = FALSE
  )

  temp_file <- tempfile(fileext = ".csv")
  readr::write_csv(test_data, temp_file)

  validation <- validate_mapping(temp_file, min_species = 10000)

  expect_false(validation$valid)
  expect_false(validation$meets_minimum)
  expect_equal(validation$row_count, 50)

  unlink(temp_file)
})


test_that("validate_mapping detects missing avibase_id values", {
  skip_if_not_installed("avilistr")

  # Create test CSV with some NA AvibaseIDs
  test_data <- data.frame(
    AvibaseID = c(paste0("avibase-", 1:9990), rep(NA, 10)),
    Scientific_name = paste("Species", 1:10000),
    stringsAsFactors = FALSE
  )

  temp_file <- tempfile(fileext = ".csv")
  readr::write_csv(test_data, temp_file)

  validation <- validate_mapping(temp_file, min_species = 9990)

  expect_false(validation$valid)
  expect_equal(validation$missing_avibase, 10)

  unlink(temp_file)
})


test_that("validate_mapping fails on non-existent file", {
  expect_error(
    validate_mapping("/path/that/does/not/exist.csv"),
    "File not found"
  )
})


test_that("print.avilistr_validation produces output", {
  skip_if_not_installed("avilistr")

  # Create a validation object manually
  validation <- list(
    file_exists = TRUE,
    row_count = 15000,
    has_avibase_id = TRUE,
    has_scientific_name = TRUE,
    has_bow_url = TRUE,
    missing_avibase = 0,
    unique_avibase = 15000,
    meets_minimum = TRUE,
    valid = TRUE
  )
  class(validation) <- c("avilistr_validation", "list")

  # Capture the print output
  output <- capture.output(print(validation))

  expect_true(length(output) > 0)
  expect_true(any(grepl("Avilistr Mapping Validation", output)))
  expect_true(any(grepl("PASSED", output)))
})


test_that("print.avilistr_validation shows failure correctly", {
  skip_if_not_installed("avilistr")

  # Create a failed validation object
  validation <- list(
    file_exists = TRUE,
    row_count = 50,
    has_avibase_id = TRUE,
    has_scientific_name = TRUE,
    has_bow_url = FALSE,
    missing_avibase = 5,
    unique_avibase = 45,
    meets_minimum = FALSE,
    valid = FALSE
  )
  class(validation) <- c("avilistr_validation", "list")

  # Capture the print output
  output <- capture.output(print(validation))

  expect_true(any(grepl("FAILED", output)))
})
