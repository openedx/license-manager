.DEFAULT_GOAL := help

.PHONY: help clean piptools requirements ci_requirements dev_requirements \
        validation_requirements doc_requirements production-requirements static shell \
        test coverage isort_check isort style lint quality pii_check validate \
        migrate html_coverage upgrade extract_translation dummy_translations \
        compile_translations fake_translations  pull_translations \
        push_translations start-devstack open-devstack  pkg-devstack \
        detect_changed_source_translations validate_translations

define BROWSER_PYSCRIPT
import os, webbrowser, sys
try:
	from urllib import pathname2url
except:
	from urllib.request import pathname2url

webbrowser.open("file://" + pathname2url(os.path.abspath(sys.argv[1])))
endef
export BROWSER_PYSCRIPT
BROWSER := python -c "$$BROWSER_PYSCRIPT"

# Generates a help message. Borrowed from https://github.com/pydanny/cookiecutter-djangopackage.
help: ## display this help message
	@echo "Please use \`make <target>\` where <target> is one of"
	@awk -F ':.*?## ' '/^[a-zA-Z]/ && NF==2 {printf "\033[36m  %-25s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST) | sort

clean: ## delete generated byte code and coverage reports
	find . -name '*.pyc' -delete
	coverage erase
	rm -rf assets
	rm -rf pii_report

clean_pycrypto: ## temporary (?) hack to deal with the pycrypto dep that's installed via setup-tools
	ls -d /usr/lib/python3/dist-packages/* | grep 'pycrypto\|pygobject\|pyxdg' | xargs rm -f

piptools: ## install pinned version of pip-compile and pip-sync
	pip install -r requirements/pip-tools.txt

requirements: clean_pycrypto piptools dev_requirements ## sync to default requirements

ci_requirements: piptools validation_requirements ## sync to requirements needed for CI checks

dev_requirements: ## sync to requirements for local development
	pip-sync -q requirements/dev.txt

validation_requirements: ## sync to requirements for testing & code quality checking
	pip-sync -q requirements/validation.txt

doc_requirements:
	pip-sync -q requirements/doc.txt

production-requirements: piptools ## install requirements for production
	pip-sync -q requirements/production.txt

static: ## generate static files
	python manage.py collectstatic --noinput

django_shell: ## run Django shell
	python manage.py shell

test: clean ## run tests and generate coverage report
	## ``--ds`` Has the highest settings precedence:
	## https://pytest-django.readthedocs.io/en/latest/configuring_django.html#order-of-choosing-settings
	pytest --ds=license_manager.settings.test

# To be run from CI context
coverage: clean
	pytest --cov-report html
	$(BROWSER) htmlcov/index.html

isort_check: ## check that isort has been run
	isort --check-only --diff -rc license_manager/

isort: ## run isort to sort imports in all Python files
	isort --recursive --atomic license_manager/

style: ## run Python style checker
	pycodestyle license_manager *.py

lint: ## run Python code linting
	edx_lint write pylintrc  # first, write pylintrc in case tweaks have changed
	DJANGO_SETTINGS_MODULE=license_manager.settings.test \
	pylint --rcfile=pylintrc license_manager *.py

quality: style isort_check lint ## check code style and import sorting, then lint

quality_fix: style isort lint ## Check code style, FIX any imports, then lint

pii_check: ## check for PII annotations on all Django models
	DJANGO_SETTINGS_MODULE=license_manager.settings.test \
	code_annotations django_find_annotations --config_file .pii_annotations.yml --lint --report --coverage

validate: test quality pii_check ## run tests, quality, and PII annotation checks

migrate: ## apply database migrations
	python manage.py migrate

app-migrate: ## apply database migrations without having to type `make app-shell` first
	docker exec -u 0 -it license_manager.app python manage.py migrate

html_coverage: ## generate and view HTML coverage report
	coverage html && open htmlcov/index.html

define COMMON_CONSTRAINTS_TEMP_COMMENT
# This is a temporary solution to override the real common_constraints.txt\n# In edx-lint, until the pyjwt constraint in edx-lint has been removed.\n# See BOM-2721 for more details.\n# Below is the copied and edited version of common_constraints\n
endef

COMMON_CONSTRAINTS_TXT=requirements/common_constraints.txt
.PHONY: $(COMMON_CONSTRAINTS_TXT)
$(COMMON_CONSTRAINTS_TXT):
	wget -O "$(@)" https://raw.githubusercontent.com/edx/edx-lint/master/edx_lint/files/common_constraints.txt || touch "$(@)"
	echo "$(COMMON_CONSTRAINTS_TEMP_COMMENT)" | cat - $(@) > temp && mv temp $(@)

upgrade: export CUSTOM_COMPILE_COMMAND=make upgrade
upgrade: piptools $(COMMON_CONSTRAINTS_TXT) ## update the requirements/*.txt files with the latest packages satisfying requirements/*.in
	sed 's/Django<2.3//g' requirements/common_constraints.txt > requirements/common_constraints.tmp
	mv requirements/common_constraints.tmp requirements/common_constraints.txt
	# This is a temporary solution to override the real common_constraints.txt
	# In edx-lint, until the pyjwt constraint in edx-lint has been removed.
	# See BOM-271 for more details.
	sed 's/pyjwt\[crypto\]<2.0.0//g' requirements/common_constraints.txt > requirements/common_constraints.tmp
	mv requirements/common_constraints.tmp requirements/common_constraints.txt
	sed 's/social-auth-core<4.0.3//g' requirements/common_constraints.txt > requirements/common_constraints.tmp
	mv requirements/common_constraints.tmp requirements/common_constraints.txt
	sed 's/edx-auth-backends<4.0.0//g' requirements/common_constraints.txt > requirements/common_constraints.tmp
	mv requirements/common_constraints.tmp requirements/common_constraints.txt
	sed 's/edx-drf-extensions<7.0.0//g' requirements/common_constraints.txt > requirements/common_constraints.tmp
	mv requirements/common_constraints.tmp requirements/common_constraints.txt
	sed 's/drf-jwt<1.19.1//g' requirements/common_constraints.txt > requirements/common_constraints.tmp
	mv requirements/common_constraints.tmp requirements/common_constraints.txt
	# Make sure to compile files after any other files they include!
	pip-compile --upgrade -o requirements/pip-tools.txt requirements/pip-tools.in
	pip-compile --upgrade -o requirements/base.txt requirements/base.in
	pip-compile --upgrade -o requirements/test.txt requirements/test.in
	pip-compile --upgrade -o requirements/doc.txt requirements/doc.in
	pip-compile --upgrade -o requirements/quality.txt requirements/quality.in
	pip-compile --upgrade -o requirements/validation.txt requirements/validation.in
	pip-compile --upgrade -o requirements/dev.txt requirements/dev.in
	pip-compile --upgrade -o requirements/production.txt requirements/production.in

extract_translations: ## extract strings to be translated, outputting .mo files
	python manage.py makemessages -l en -v1 -d django
	python manage.py makemessages -l en -v1 -d djangojs

dummy_translations: ## generate dummy translation (.po) files
	cd license_manager && i18n_tool dummy

compile_translations: # compile translation files, outputting .po files for each supported language
	python manage.py compilemessages

fake_translations: ## generate and compile dummy translation files

pull_translations: ## pull translations from Transifex
	tx pull -af --mode reviewed

push_translations: ## push source translation files (.po) from Transifex
	tx push -s

open-devstack: ## open a shell on the server started by start-devstack
	docker exec -it license_manager /edx/app/license_manager/devstack.sh open

pkg-devstack: ## build the license_manager image from the latest configuration and code
	docker build -t license_manager:latest -f docker/build/license_manager/Dockerfile git://github.com/edx/configuration

detect_changed_source_translations: ## check if translation files are up-to-date
	cd license_manager && i18n_tool changed

validate_translations: fake_translations detect_changed_source_translations ## install fake translations and check if translation files are up-to-date

# Docker dev commands below

dev.provision:
	bash ./provision-license-manager.sh

dev.up: dev.up.redis  # Starts all of the services, will bring up the devstack-defined redis container if not running.
	docker-compose up -d

dev.up.build:
	docker-compose up -d --build

dev.up.redis:
	docker-compose -f $(DEVSTACK_WORKSPACE)/devstack/docker-compose.yml up -d redis

dev.down: # Kills containers and all of their data that isn't in volumes
	docker-compose down

dev.stop: # Stops containers so they can be restarted
	docker-compose stop

%-shell: # Run a shell, as root, on the specified service container
	docker exec -u 0 -it license_manager.$* bash

mysql-client-shell: # Will drop you directly into a mysql client shell.
	docker exec -u 0 -it license_manager.mysql mysql license_manager

%-logs: # View the logs of the specified service container
	docker-compose logs -f --tail=500 $*

%-restart: # Restart the specified service container
	docker-compose restart $*

%-attach:
	docker attach license_manager.$*

app-restart-devserver: ## Kill the license-manager development server. Watcher should restart it.
	docker-compose exec app bash -c 'kill $$(ps aux | egrep "manage.py ?\w* runserver" | egrep -v "while|grep" | awk "{print \$$2}")'

dev.stats: ## Get per-container CPU and memory utilization data.
	docker stats --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"

docker_build:
	docker build . -f Dockerfile --target app -t openedx/license-manager
	docker build . -f Dockerfile --target devstack -t openedx/license-manager:latest-devstack

	docker build . -f Dockerfile --target app -t openedx/license-manager.worker
	docker build . -f Dockerfile --target devstack -t openedx/license-manager.worker:latest-devstack

	docker build . -f Dockerfile --target newrelic -t openedx/license-manager:latest-newrelic

docker_tag: docker_build
	docker tag openedx/license-manager openedx/license-manager:$$GITHUB_SHA
	docker tag openedx/license-manager:latest-devstack openedx/license-manager:$$GITHUB_SHA-devstack
	docker tag openedx/license-manager:latest-newrelic openedx/license-manager:$$GITHUB_SHA-newrelic

docker_auth:
	echo "$$DOCKERHUB_PASSWORD" | docker login -u "$$DOCKERHUB_USERNAME" --password-stdin

docker_push: docker_tag docker_auth ## push to docker hub
	docker push 'openedx/license-manager:latest'
	docker push "openedx/license-manager:$$GITHUB_SHA"
	docker push 'openedx/license-manager:latest-devstack'
	docker push "openedx/license-manager:$$GITHUB_SHA-devstack"
	docker push 'openedx/license-manager:latest-newrelic'
	docker push "openedx/license-manager:$$GITHUB_SHA-newrelic"
