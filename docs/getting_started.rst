Getting Started
===============
First, make sure your devstack is up and running as license-manager currently depends on the edx devstack.
Next, run the following commands:

.. code-block:: bash

    $ make docker_build
    $ make dev.up
    $ make dev.provision
    $ make app-shell
    $ make requirements

At this point, the license_manager app should be ready to go.

Viewing License Manager 
------------------------
Once the server is up and running you can view the app admin at http://localhost:18170/admin.

You can login with the username *edx* and password *edx*.

Makefile Commands
--------------------
The `Makefile <../Makefile>`_ includes numerous commands to start the service, but the basic commands are the following:

Start the Docker containers to run the license manager servers

.. code-block:: bash

    $ make dev.up

Open the shell to the license manager container for manual commands

.. code-block:: bash

    $ make app-shell

Once inside an application container, there's a particularly useful tool called `django-extensions_` that allows
you to run ``./manage.py shell_plus``, which is superior to the built-in Django ``shell`` because it automatically
imports all of the models from the app, along with some helpful Django imports.
``django-extensions`` is only installed via dev requirements and will only work when run with the ``devstack.py``
settings, because that's where it is installed into ``INSTALLED_APPS``.  The ``./manage.py show_urls`` is also helpful.

.. _django-extensions: https://github.com/django-extensions/django-extensions#using-it


Local/Private Settings
----------------------
When developing locally, it may be useful to have settings overrides that you do not wish to commit to the repository.
If you need such overrides, create a file :file:`license-manager/settings/private.py`. This file's values are
read by :file:`license-manager/settings/local.py`, but ignored by Git.


Advanced Setup Outside Docker
=============================
The following is provided for informational purposes only. You can likely ignore this section.

If you have not already done so, create/activate a `virtualenv`_. Unless otherwise stated, assume all terminal code
below is executed within the virtualenv.

.. _virtualenv: https://virtualenvwrapper.readthedocs.org/en/latest/


Install dependencies
--------------------
Dependencies can be installed via the command below.

.. code-block:: bash

    $ make requirements


Configure edX OAuth (Optional)
-------------------------------

OAuth only needs to be configured if the IDA would like to use the LMS's authentication functionality in place of managing its own.

This functionality relies on the LMS server as the OAuth 2.0 authentication provider.

Configuring License Manager to communicate with other IDAs using OAuth requires registering a new client with the authentication
provider (LMS) and updating the Django settings for this project with the generated client credentials.

A new OAuth 2.0 client can be created when using Devstack by visiting ``http://127.0.0.1:18000/admin/oauth2_provider/application/``.
    1. Click the :guilabel:`Add Application` button.
    2. Leave the user field blank.
    3. Specify the name of this service, ``License Manager``, as the client name.
    4. Set the :guilabel:`URL` to the root path of this service: ``http://127.0.0.1:18170/``.
    5. Set the :guilabel:`Redirect URL` to the complete endpoint: ``http://127.0.0.1:18170/complete/edx-oauth2/``.
    6. Copy the :guilabel:`Client ID` and :guilabel:`Client Secret` values. They will be used later.
    7. Select :guilabel:`Confidential` as the client type.
    8. Select :guilabel:`Authorization code` as the authorization grant type.
    9. Click :guilabel:`Save`.



Now that you have the client credentials, you can update your settings (ideally in
:file:`license-manager/settings/local.py`). The table below describes the relevant settings.

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


