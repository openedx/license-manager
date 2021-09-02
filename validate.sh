#!/bin/bash
set -e

export DJANGO_SETTINGS_MODULE=license_manager.settings.test

source /edx/app/license-manager/venvs/license-manager/bin/activate
cd /edx/app/license_manager

make ci_requirements
pip install -r requirements/pip.txt
pip install -r requirements/travis.txt

make validate_translations

# TODO: enable pylint once we figure out mysterious AssignAttr attribute error.
# When that's fixed, we can replace all of the below with `make validate`
make test
make style
make isort_check
make pii_check
