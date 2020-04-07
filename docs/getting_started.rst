Getting Started
===============

If you have not already done so, create/activate a `virtualenv`_. Unless otherwise stated, assume all terminal code
below is executed within the virtualenv.

.. _virtualenv: https://virtualenvwrapper.readthedocs.org/en/latest/


Initialize and Provision
------------------------
    1. Start and provision the edX `devstack <https://github.com/edx/devstack>`_, as license-manager currently relies on devstack
    2. Verify that your virtual environment is active before proceeding
    3. Clone the license-manager repo and cd into that directory
    4. Run *make dev.provision* to provision a new license manager environment
    5. Run *make dev.init* to start the license manager app and run migrations

Viewing License Manager 
------------------------
Once the server is up and running you can view the license manager at http://localhost:18170/admin.

You can login with the username *edx@example.com* and password *edx*.

Makefile Commands
--------------------
The `Makefile <../Makefile>`_ includes numerous commands to start the service, but the basic commands are the following:

Start the Docker containers to run the license manager servers

.. code-block:: bash

    $ make dev.up

Open the shell to the license manager container for manual commands

.. code-block:: bash

    $ make app-shell

Open the logs in the license manager container

.. code-block:: bash

    $ make license-manager-logs

Advanced Setup Outside Docker
=============================
The following is provided for informational purposes only. You can likely ignore this section.

Local/Private Settings
----------------------
When developing locally, it may be useful to have settings overrides that you do not wish to commit to the repository.
If you need such overrides, create a file :file:`license_manager/settings/private.py`. This file's values are
read by :file:`license_manager/settings/local.py`, but ignored by Git.

Configure edX OAuth
-------------------
This service relies on the LMS server as the OAuth 2.0 authentication provider.

Configuring License Manager service to communicate with other IDAs using OAuth requires registering a new client with the authentication
provider (LMS) and updating the Django settings for this project with the generated client credentials.

A new OAuth 2.0 client can be created when using Devstack by visiting ``http://127.0.0.1:18000/admin/oauth2_provider/application/``.
    1. Click the :guilabel:`Add Application` button.
    2. Leave the user field blank.
    3. Specify the name of this service, ``License Manager service``, as the client name.
    4. Set the :guilabel:`URL` to the root path of this service: ``http://127.0.0.1:8003/``.
    5. Set the :guilabel:`Redirect URL` to the complete endpoint: ``http://127.0.0.1:18150/complete/edx-oauth2/``.
    6. Copy the :guilabel:`Client ID` and :guilabel:`Client Secret` values. They will be used later.
    7. Select :guilabel:`Confidential` as the client type.
    8. Select :guilabel:`Authorization code` as the authorization grant type.
    9. Click :guilabel:`Save`.



Now that you have the client credentials, you can update your settings (ideally in
:file:`license_manager/settings/local.py`). The table below describes the relevant settings.

+-----------------------------------+----------------------------------+--------------------------------------------------------------------------+
| Setting                           | Description                      | Value                                                                    |
+===================================+==================================+==========================================================================+
| SOCIAL_AUTH_EDX_OAUTH2_KEY        | SSO OAuth 2.0 client key         | (This should be set to the value generated when the client was created.) |
+-----------------------------------+----------------------------------+--------------------------------------------------------------------------+
| SOCIAL_AUTH_EDX_OAUTH2_SECRET     | SSO OAuth 2.0 client secret      | (This should be set to the value generated when the client was created.) |
+-----------------------------------+----------------------------------+--------------------------------------------------------------------------+
| SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT   | OAuth 2.0 authentication URL     | http://127.0.0.1:18000/oauth2                                            |
+-----------------------------------+----------------------------------+--------------------------------------------------------------------------+
| BACKEND_SERVICE_EDX_OAUTH2_KEY    | IDA<->IDA OAuth 2.0 client key   | (This should be set to the value generated when the client was created.) |
+-----------------------------------+----------------------------------+--------------------------------------------------------------------------+
| BACKEND_SERVICE_EDX_OAUTH2_SECRET | IDA<->IDA OAuth 2.0 client secret| (This should be set to the value generated when the client was created.) |
+-----------------------------------+----------------------------------+--------------------------------------------------------------------------+


Run migrations
--------------
Local installations use SQLite by default. If you choose to use another database backend, make sure you have updated
your settings and created the database (if necessary). Migrations can be run with `Django's migrate command`_.

.. code-block:: bash

    $ python manage.py migrate

.. _Django's migrate command: https://docs.djangoproject.com/en/1.11/ref/django-admin/#django-admin-migrate


Run the server
--------------
The server can be run with `Django's runserver command`_. If you opt to run on a different port, make sure you update
OAuth2 client via LMS admin.

.. code-block:: bash

    $ python manage.py runserver 8003

.. _Django's runserver command: https://docs.djangoproject.com/en/1.11/ref/django-admin/#runserver-port-or-address-port


