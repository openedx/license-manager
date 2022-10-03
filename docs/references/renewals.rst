Subscription Plan Renewals
==========================

Background
----------

* A ``SubscriptionPlanRenewal`` is a type of record that relates prior and future ``SubscriptionPlan`` records.
* Renewal records can be "processed".  The processing can happen manually through a Django Admin action, or
  the processing will happen automatically, via a recurring cron job, based on the renewal record's effective date.

Defintions
----------
* **renewal** The record, or processing thereof, referring to the fact that an existing
  subscription plan will be renewed into a new plan in the future.
* **original plan** The original plan, which will become expired at the end of the expiration process.
* **future plan** The new plan, created during the renewal process, and becomes effective some time after
  the renewal process is completed.


The models involved
-------------------

.. |basic_models| image:: https://github.com/openedx/license-manager/blob/master/docs/diagrams/src/renewals/renewal-basic-models.svg

The basic models involved in subscription plan renewals are here: |basic_models|
Important things:

* A renewal record is **not** a subscription plan.
* A renewal record holds data about the intention for a future plan to exist, based on some prior plan and its
  associated licenses.
* A renewal record can be processed, either manually or via a cron job.
* Once a renewal record is marked as processed, it will not/cannot be processed again.
* When a future ``SubscriptionPlan`` record is created during renewal processing, new ``License`` records are
  created and associated with that future plan.  License record state is copied from the licenses in the prior plan.


How processing works
--------------------

.. |processing| image:: https://github.com/openedx/license-manager/blob/master/docs/diagrams/src/renewals/renewal-processing.svg

|processing|

When a ``SubscriptionPlanRenewal`` record is successfully processed, it results in the creation or updating
of the future ``SubscriptionPlan`` record, along with the creation of new licenses being created for the future plan.

During creation of the ``SubscriptionPlanRenewal``, a Django Admin user can specify which types of licenses from the prior
plan are replicated into the future plan:

* Both assigned and activated licenses (this is the default choice).
* Only activated licenses.
* None.  When none is chosen, the specified number of new licenses are created for the future plan, each of which will be unassigned.

The date fields
^^^^^^^^^^^^^^^

* The effective date field of the ``SubscriptionPlanRenewal`` becomes the start date of the future plan.
* The renewed expiration date is exactly what it sounds like: the expiration date of the future plan.

The title
^^^^^^^^^

If the Django Admin user does not specify the title of the future plan in the ``SubscriptionPlanRenewal`` record,
a title will be generated automatically for the future plan; it will look as follows:

* ``(the prior plan's title) - Renewal (the renewal effective date's year)``

For example, if the prior plan's title is "Acme's dogfood division subs", and the effective date of the renewal is June 1, 2022,
then the automatically generated title of the future plan would be "Acme's dogfood division subs - Renewal 2022".


Disallowed states
-----------------

There are various states of renewals and subscription plans that are not allowed, which are documented below:

* The first disallowed state in the table simply describes that we do not allow a plan to renew with a smaller
  number of licenses than the number of activated + assigned licenses in the prior plan.
* The second row in the table shows that we don't allow for two different renewal records to be associated
  with the same prior subscription plan record.
* The third row shows that we don't allow a single prior plan to be "split" into two different future plans
  via a renewal.
* The last two rows describe how we don't allow multiple plans to be "merged" into a single future plan via a renewal.

.. |disallowed_states| image:: https://github.com/openedx/license-manager/blob/master/docs/diagrams/src/renewals/renewal-disallowed-states.svg

|disallowed_states|

Chains of renewals
------------------

A future plan created as the result of a renewal may itself be renewed, as demonstrated in the picture below.

.. |renewal_chain| image:: https://github.com/openedx/license-manager/blob/master/docs/diagrams/src/renewals/renewal-chain.svg

|renewal_chain|
