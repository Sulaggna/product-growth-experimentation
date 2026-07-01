PYTHON ?= python

.PHONY: help install data warehouse analysis validate notebook dashboard test all clean

help:  ## list targets
	@grep -E '^[a-z]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-11s %s\n", $$1, $$2}'

install:  ## install the package + dev dependencies (editable)
	$(PYTHON) -m pip install -e ".[dev]"

data:  ## simulate the raw event data into data/raw/
	$(PYTHON) -m growth_analytics.simulate

warehouse:  ## build the DuckDB warehouse from sql/*.sql
	$(PYTHON) -m growth_analytics.warehouse

analysis:  ## run every analysis; writes reports/figures, reports/tables, reports/metrics.json
	$(PYTHON) -m growth_analytics.pipeline

validate:  ## re-run the 40-seed coverage study (about 4 minutes)
	$(PYTHON) -m growth_analytics.validation --seeds 40

notebook:  ## rebuild and execute the walkthrough notebook
	$(PYTHON) notebooks/build_notebook.py

dashboard:  ## launch the Streamlit dashboard
	$(PYTHON) -m streamlit run dashboard/app.py

test:  ## run the test-suite
	$(PYTHON) -m pytest

all: data warehouse analysis notebook test  ## full rebuild

clean:  ## delete generated data (figures and reports are kept)
	rm -rf data/
