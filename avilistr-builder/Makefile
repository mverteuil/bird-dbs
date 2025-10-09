# Makefile for avilistr-builder
#
# Provides convenient targets for testing, coverage, and linting
# R package development tasks

.PHONY: help install test coverage lint format clean all

help:
	@echo "avilistr-builder - Avibase ID Mapping Extractor"
	@echo ""
	@echo "Available targets:"
	@echo "  make install    - Install R package and dependencies"
	@echo "  make test       - Run testthat unit tests"
	@echo "  make coverage   - Generate test coverage report"
	@echo "  make lint       - Run lintr code quality checks"
	@echo "  make format     - Format code with styler"
	@echo "  make clean      - Remove output files and coverage artifacts"
	@echo "  make all        - Run tests, coverage, and linting"

install:
	@echo "Installing avilistr-builder and dependencies..."
	Rscript -e "install.packages(c('devtools', 'testthat', 'covr', 'lintr', 'styler'), repos='https://cloud.r-project.org')"
	Rscript -e "install.packages('avilistr', repos='https://cloud.r-project.org')"
	Rscript -e "devtools::install('.', dependencies=TRUE)"

test:
	@echo "Running testthat tests..."
	Rscript -e "devtools::test()"

coverage:
	@echo "Generating test coverage report..."
	Rscript -e "covr::package_coverage(type='all', quiet=FALSE)"

coverage-html:
	@echo "Generating HTML coverage report..."
	Rscript -e "cov <- covr::package_coverage(type='all'); covr::report(cov, file='coverage.html'); browseURL('coverage.html')"

lint:
	@echo "Running lintr checks..."
	Rscript -e "lintr::lint_package()"

format:
	@echo "Formatting code with styler..."
	Rscript -e "styler::style_pkg()"

clean:
	@echo "Cleaning output files and coverage artifacts..."
	rm -rf output/*.csv
	rm -f coverage.html
	rm -f .coverage
	rm -rf tests/testthat/_snaps

all: test coverage lint
	@echo "All checks complete!"

# Build the R package
build:
	@echo "Building R package..."
	R CMD build .

# Check the R package
check:
	@echo "Checking R package..."
	R CMD check --as-cran *.tar.gz

# Run the extraction (requires avilistr to be installed)
extract:
	@echo "Running Avibase mapping extraction..."
	Rscript -e "library(avilistBuilder); extract_avilistr_mapping('../shared/avilistr/avilistr_mapping.csv')"

# Validate the output
validate:
	@echo "Validating output CSV..."
	Rscript -e "library(avilistBuilder); print(validate_mapping('../shared/avilistr/avilistr_mapping.csv'))"
