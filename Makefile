VENV ?= .venv
BIN  := $(VENV)/bin
PY   := $(BIN)/python
PIP  := $(BIN)/pip
PROC := $(BIN)/procedura

.PHONY: dev install login init test env

dev:
	python3 -m venv $(VENV)
	$(PY) -m pip install -U pip setuptools wheel
	$(PY) -m pip install -e .

# optional: verify paths
env:
	@echo "PY=$(PY)"
	@echo "PROC=$(PROC)"
	@ls -1 $(BIN) | sed 's/^/.venv\/bin\//'

login:
	$(PROC) --url 'wss://latticeui.scorchednebraska.com:33000/' \
	  login 'admin@procedura.org:secret123' --ttl 7200

# or, if you prefer not to rely on the console script:
# login:
# 	$(PY) -m procedura_sdk.cli --url 'wss://latticeui.scorchednebraska.com:33000/' \
# 	  login 'admin@procedura.org:secret123' --ttl 7200

init:
	$(PY) -m procedura_sdk.modules.init_character \
	  --url 'wss://latticeui.scorchednebraska.com:33000/' \
	  --role-id explorer --sub-id cartographer

test:
	$(PY) -m pytest -q

