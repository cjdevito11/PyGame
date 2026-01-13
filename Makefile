PYTHON=python

.PHONY: install test demo-list demo-show demo-validate

install:
$(PYTHON) -m pip install -r requirements.txt

test:
$(PYTHON) -m unittest

demo-list:
$(PYTHON) -m ui.cli list appearances

demo-show:
$(PYTHON) -m ui.cli show classes adventurer

demo-validate:
$(PYTHON) -m ui.cli validate
