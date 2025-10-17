#!/bin/bash
#
# Install R dependencies for density analyzer benchmark
#

set -e

echo "Installing R packages for eBird density analysis..."

# Check if R is installed
if ! command -v R &> /dev/null; then
    echo "ERROR: R is not installed"
    echo ""
    echo "Install R:"
    echo "  macOS: brew install r"
    echo "  Ubuntu: sudo apt-get install r-base"
    exit 1
fi

# Install packages
R -e "
# Set CRAN mirror
options(repos = c(CRAN = 'https://cloud.r-project.org'))

# Required packages
packages <- c('auk', 'h3r', 'data.table', 'jsonlite', 'argparse')

# Install missing packages
new_packages <- packages[!(packages %in% installed.packages()[,'Package'])]

if(length(new_packages) > 0) {
  cat('Installing:', paste(new_packages, collapse=', '), '\n')
  install.packages(new_packages, dependencies = TRUE)
} else {
  cat('All packages already installed\n')
}

# Verify installation
cat('\nVerifying installation:\n')
for(pkg in packages) {
  if(require(pkg, character.only = TRUE, quietly = TRUE)) {
    cat('  ✓', pkg, '\n')
  } else {
    cat('  ✗', pkg, 'FAILED\n')
  }
}
"

echo ""
echo "✅ R dependencies installed"
echo ""
echo "Test with:"
echo "  Rscript analyze_density.R --help"
