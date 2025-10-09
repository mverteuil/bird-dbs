# Environment variables for Homebrew LLVM tools on macOS
export LLVM_COV := /opt/homebrew/opt/llvm/bin/llvm-cov
export LLVM_PROFDATA := /opt/homebrew/opt/llvm/bin/llvm-profdata

.PHONY: help test coverage coverage-html coverage-lcov clean

help:
	@echo "Available targets:"
	@echo "  test          - Run all tests"
	@echo "  coverage      - Run tests with coverage report (terminal)"
	@echo "  coverage-html - Generate HTML coverage report"
	@echo "  coverage-lcov - Generate LCOV coverage report"
	@echo "  clean         - Clean coverage artifacts"

test:
	cargo test --all-features

coverage:
	cargo llvm-cov --all-features

coverage-html:
	cargo llvm-cov --all-features --html
	@echo "Coverage report generated at: target/llvm-cov/html/index.html"
	@open target/llvm-cov/html/index.html 2>/dev/null || echo "Open target/llvm-cov/html/index.html in your browser"

coverage-lcov:
	cargo llvm-cov --all-features --lcov --output-path lcov.info
	@echo "LCOV report generated at: lcov.info"

clean:
	cargo llvm-cov clean
	rm -rf target/llvm-cov lcov.info
