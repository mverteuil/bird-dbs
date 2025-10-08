#!/usr/bin/env bash
set -euo pipefail

# BirdNET-Pi Database Extractors - Data Collection Script
#
# This script helps you collect the required source data for building
# reference databases. Some data sources require manual download due to
# licensing restrictions.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$PROJECT_ROOT/data"
SHARED_DIR="$PROJECT_ROOT/shared"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print functions
print_header() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

# Create directory structure
create_directories() {
    print_header "Creating Directory Structure"

    mkdir -p "$SHARED_DIR/avilistr"
    mkdir -p "$DATA_DIR/ioc"
    mkdir -p "$DATA_DIR/ebird"
    mkdir -p "$PROJECT_ROOT/output"
    mkdir -p "$PROJECT_ROOT/output/ebird_regions"

    print_success "Created directories:"
    print_info "  - $SHARED_DIR/avilistr (Avilistr world bird list)"
    print_info "  - $DATA_DIR/ioc (IOC Excel files)"
    print_info "  - $DATA_DIR/ebird (eBird EBD data)"
    print_info "  - $PROJECT_ROOT/output (Output databases)"
}

# Download Avilistr world bird list
download_avilistr() {
    print_header "Downloading Avilistr World Bird List"

    local today=$(date +%Y-%m-%d)
    local output_file="$SHARED_DIR/avilistr/world_birds_${today}.csv"

    print_info "Downloading from Avibase..."
    print_info "This may take several minutes (file is ~30-40 MB)"

    # Avibase checklist download URL
    # Parameters: World, All taxonomies, CSV export
    local avibase_url="https://avibase.bsc-eoc.org/checklist.jsp?region=wrld&list=clements2023&synlang=&lang=EN&format=2"

    if command -v wget &> /dev/null; then
        wget -O "$output_file" "$avibase_url" || {
            print_error "Download failed. You may need to download manually."
            print_manual_avilistr_instructions
            return 1
        }
    elif command -v curl &> /dev/null; then
        curl -L -o "$output_file" "$avibase_url" || {
            print_error "Download failed. You may need to download manually."
            print_manual_avilistr_instructions
            return 1
        }
    else
        print_error "Neither wget nor curl found. Please download manually."
        print_manual_avilistr_instructions
        return 1
    fi

    # Verify download
    if [ -f "$output_file" ] && [ -s "$output_file" ]; then
        local file_size=$(du -h "$output_file" | cut -f1)
        print_success "Downloaded Avilistr data: $output_file ($file_size)"

        # Quick validation
        local line_count=$(wc -l < "$output_file")
        if [ "$line_count" -gt 10000 ]; then
            print_success "Validation: File contains $line_count species entries"
        else
            print_warning "File seems too small ($line_count lines). Please verify manually."
        fi
    else
        print_error "Download verification failed"
        return 1
    fi
}

print_manual_avilistr_instructions() {
    echo ""
    print_info "Manual download instructions:"
    echo "  1. Visit: https://avibase.bsc-eoc.org/checklist.jsp"
    echo "  2. Select: Region = World"
    echo "  3. Select: Taxonomy = Clements 2023 (or latest)"
    echo "  4. Select: Format = CSV"
    echo "  5. Click 'Get List'"
    echo "  6. Save to: $SHARED_DIR/avilistr/world_birds_$(date +%Y-%m-%d).csv"
    echo ""
}

# IOC file instructions
check_ioc_files() {
    print_header "Checking IOC World Bird List Files"

    local ioc_files=$(find "$DATA_DIR/ioc" -name "IOC_*.xlsx" 2>/dev/null | wc -l)

    if [ "$ioc_files" -ge 2 ]; then
        print_success "Found IOC files:"
        find "$DATA_DIR/ioc" -name "IOC_*.xlsx" -exec basename {} \;
    else
        print_warning "IOC files not found. Manual download required."
        echo ""
        print_info "Download instructions:"
        echo "  1. Visit: https://www.worldbirdnames.org/"
        echo "  2. Download latest version Excel files:"
        echo "     - IOC_Names_File_Plus-XX.X.xlsx"
        echo "     - IOC_Multiling_Names_File-XX.X.xlsx"
        echo "  3. Save to: $DATA_DIR/ioc/"
        echo ""
        echo "  License: CC-BY-4.0 (attribution required)"
        echo "  Citation: Gill F, D Donsker & P Rasmussen (Eds). 2024. IOC World Bird List"
        echo ""
    fi
}

# eBird data instructions
check_ebird_data() {
    print_header "Checking eBird Basic Dataset (EBD)"

    local ebd_files=$(find "$DATA_DIR/ebird" -name "ebd_rel*.tar" 2>/dev/null | wc -l)

    if [ "$ebd_files" -ge 1 ]; then
        print_success "Found eBird EBD files:"
        find "$DATA_DIR/ebird" -name "ebd_rel*.tar" -exec basename {} \;
    else
        print_warning "eBird EBD not found. Restricted access required."
        echo ""
        print_info "eBird EBD Access Requirements:"
        echo "  ⚠️  RESTRICTED ACCESS: Requires Cornell Lab research license"
        echo ""
        echo "  1. Visit: https://ebird.org/data/download"
        echo "  2. Request access (requires research justification)"
        echo "  3. Wait for approval (may take several days)"
        echo "  4. Download eBird Basic Dataset (EBD)"
        echo "     - File: ebd_relAug-2025.tar (or latest)"
        echo "     - Size: 200GB+ compressed, 500GB+ uncompressed"
        echo "  5. Save to: $DATA_DIR/ebird/"
        echo ""
        echo "  License: eBird Basic Dataset Terms of Use"
        echo "  - Research use only"
        echo "  - Citation required"
        echo "  - Cannot redistribute raw EBD data"
        echo ""
        print_warning "Note: eBird data is ONLY required for building region packs"
        print_info "IOC and Wikidata reference databases can be built without it"
        echo ""
    fi
}

# Summary
print_summary() {
    print_header "Data Collection Summary"

    local avilistr_exists=false
    local ioc_exists=false
    local ebd_exists=false

    # Check Avilistr
    if find "$SHARED_DIR/avilistr" -name "world_birds_*.csv" -type f 2>/dev/null | grep -q .; then
        print_success "Avilistr: Ready"
        avilistr_exists=true
    else
        print_error "Avilistr: Missing"
    fi

    # Check IOC
    if [ "$(find "$DATA_DIR/ioc" -name "IOC_*.xlsx" 2>/dev/null | wc -l)" -ge 2 ]; then
        print_success "IOC: Ready"
        ioc_exists=true
    else
        print_error "IOC: Missing"
    fi

    # Check eBird
    if find "$DATA_DIR/ebird" -name "ebd_rel*.tar" -type f 2>/dev/null | grep -q .; then
        print_success "eBird EBD: Ready"
        ebd_exists=true
    else
        print_warning "eBird EBD: Missing (optional for IOC/Wikidata builds)"
    fi

    echo ""
    print_info "Next Steps:"

    if [ "$avilistr_exists" = true ] && [ "$ioc_exists" = true ]; then
        echo "  ✓ You can build IOC reference database"
        echo "    cd ioc-builder && python3 ioc_database_builder.py --help"
    fi

    if [ "$avilistr_exists" = true ]; then
        echo "  ✓ You can build Wikidata reference database"
        echo "    cd wikidata-builder && python3 run_wikidata_poc.py --help"
    fi

    if [ "$avilistr_exists" = true ] && [ "$ebd_exists" = true ]; then
        echo "  ✓ You can build eBird region packs"
        echo "    cd ebird-builder && cargo build --release"
    fi

    echo ""
    print_info "See README.md for detailed build instructions"
}

# Main execution
main() {
    echo ""
    print_header "BirdNET-Pi Database Extractors - Data Collection"
    echo ""

    create_directories
    echo ""

    download_avilistr || true
    echo ""

    check_ioc_files
    echo ""

    check_ebird_data
    echo ""

    print_summary
}

main "$@"
