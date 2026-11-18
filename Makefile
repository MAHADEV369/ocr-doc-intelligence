.PHONY: test lint compile regen benchmark clean

test:
	python3 -m pytest

lint:
	ruff check src benchmark tests

compile:
	python3 -m compileall -q src benchmark tests

regen:
	python3 -m src.bank_ratios
	python3 -m src.statements
	python3 -m src.quarterly
	python3 -m src.export
	python3 -m src.verify_gt
	python3 -m src.master_summary
	python3 -m src.company_financials
	python3 -m src.dashboard
	python3 -m src.report

benchmark:
	python3 -m benchmark.metrics
	python3 -m benchmark.reports

clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
