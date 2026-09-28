.PHONY: setup pipeline app test clean

setup:
	python -m venv .venv
	.venv/bin/pip install -r requirements-dev.txt

pipeline:
	python scripts/run_pipeline.py

app:
	streamlit run app.py

test:
	pytest

clean:
	rm -f data/education.db data/education.db-shm data/education.db-wal models/*.joblib models/metrics.json
	rm -f data/processed/*.csv data/processed/*.json reports/figures/*.png
