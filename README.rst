License Manager  |Codecov|_
===================================================
.. |Codecov| image:: http://codecov.io/github/edx/license-manager/coverage.svg?branch=master
.. _Codecov: http://codecov.io/github/edx/license-manager?branch=master

Django backend for managing licenses and subscriptions.

Setting up license-manager
--------------------------

Prerequisites
^^^^^^^^^^^^^
- Set the ``DEVSTACK_WORKSPACE`` env variable (either locally or in your shell config file: ``.bash_rc``, ``.zshrc``, or equivalent) to the folder which contains this repo and the `devstack` repo.
  e.g ``export DEVSTACK_WORKSPACE=/home/<your_user>/edx``
- Set up `devstack <https://github.com/openedx/devstack>`_

Quick Setup
^^^^^^^^^^^
`More detailed setup instructions <https://github.com/openedx/license-manager/blob/master/docs/getting_started.rst>`_

::

  $ make docker_build
  $ make dev.provision
  $ make dev.up
  $ make app-shell
  # make requirements
  # make validate  # to run full test suite

The server will run on ``localhost:18170``

Running migrations
------------------

::

  $ make app-shell
  # ./manage.py migrate

Running backup/restore to switch mysql volumes
----------------------------------------------
Sometimes the names of volumes must change due to upgrades, etc.
To dump data from an old mysql volume to the new mysql8 volume:

- Temporarily modify docker-compose.yml to switch the mysql volume name from mysql8 to just mysql
- Create a backup directory in your license-manager repo: ``mkdir -p .dev/backups``
  (although the next steps might actually do this for you)

Then::

  make dev.down
  make dev.backup
  make dev.down

Next:

- Remove your temp changes from above in docker-compose.yml
- ``make dev.restore``
- ``make dev.down dev.up`` - might be necessary if you lost connection between the app container and the mysql container.

Documentation
-------------
.. |ReadtheDocs| image:: https://readthedocs.org/projects/license-manager/badge/?version=latest
.. _ReadtheDocs: http://license-manager.readthedocs.io/en/latest/

`Documentation <https://license-manager.readthedocs.io/en/latest/>`_ is hosted on Read the Docs. The source is hosted in this repo's `docs <https://github.com/openedx/license-manager/tree/master/docs>`_ directory. To contribute, please open a PR against this repo.

For instructions on starting local development, see `Getting Started <https://github.com/openedx/license-manager/blob/master/docs/getting_started.rst>`_.

License
-------

The code in this repository is licensed under version 3 of the AGPL unless otherwise noted. Please see the LICENSE_ file for details.

.. _LICENSE: https://github.com/openedx/license-manager/blob/master/LICENSE

How To Contribute
-----------------

Contributions are welcome. Please read `How To Contribute <https://github.com/openedx/edx-platform/blob/master/CONTRIBUTING.rst>`_ for details. Even though it was written with ``edx-platform`` in mind, these guidelines should be followed for Open edX code in general.

Reporting Security Issues
-------------------------

Please do not report security issues in public. Please email security@edx.org.

Get Help
--------

Ask questions and discuss this project on `Slack <https://openedx.slack.com/messages/general/>`_ or in the `edx-code Google Group <https://groups.google.com/forum/#!forum/edx-code>`_.
