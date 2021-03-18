.DEFAULT_GOAL := venv

venv:
	virtualenv -p python3 venv
	venv/bin/pip install -r requirements-dev.txt -r requirements.txt

.PHONY: test
test: venv
	mypy
	flake8
	pylint main.py

.PHONY: clean
clean: ## Clean working directory
	find . -iname '*.pyc' | xargs rm -f
	rm -rf ./venv
