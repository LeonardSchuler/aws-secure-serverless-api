.PHONY: all .venv clean install api delete request

all: .env .venv install

api:
	source .venv/bin/activate && python3 create.py

request: .env
	source .env && echo "Username: Testuser" && echo "Password: $$PASSWORD"
	source .venv/bin/activate && python3 tokens.py

delete:
	source .venv/bin/activate && python3 delete.py 2>/dev/null

.env:
	@read -p "Enter AWS_DEFAULT_REGION (e.g. us-east-1, eu-central-1): " AWS_DEFAULT_REGION; \
	read -p "Enter AWS_PROFILE (as defined in your .aws/config): " AWS_PROFILE; \
	echo 'export AWS_DEFAULT_REGION="'$$AWS_DEFAULT_REGION'"' > .env; \
	echo 'export AWS_PROFILE="'$$AWS_PROFILE'"' >> .env; \
	echo 'export PASSWORD="'"$$(openssl rand -base64 10)"'"' >> .env; \
	echo 'export DOMAIN_PREFIX="'"$$(tr -dc 'a-z' </dev/urandom | head -c 16)"'"' >> .env; \
	echo ".env file created."

.venv:
	python3 -m venv .venv
	source .venv/bin/activate && pip install --upgrade pip
	@echo "Virtual environment (.venv) created."
	@echo "Activating virtual environment (.venv)..."
	@echo "Run 'source .venv/bin/activate' to activate it."
	@echo "Then run 'make install' to install dependencies."

requirements.txt: requirements.in .venv
	source .venv/bin/activate && pip install pip-tools && pip-compile --strip-extras --output-file=requirements.txt requirements.in

install: .venv requirements.txt
	source .venv/bin/activate && pip install -r requirements.txt
	@echo "Python environment successfully set up"
	@echo "Run 'source .venv/bin/activate' to activate it."

clean:
	-rm state.json
	-rm requirements.txt
	-rm .env
	-rm -rf .venv 2>/dev/null
	-rm -rf __pycache__ 2>/dev/null
	@echo "Virtual environment removed."