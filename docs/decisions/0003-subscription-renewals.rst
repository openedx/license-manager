3. Introduction of a Subscription Plan Renewal Model
====================================================

Status
======

Accepted (circa November 2020)

Context
=======

We'd like to allow subscriptions customers to schedule a renewal of their existing subscriptions prior to
their active subscription's expiration date.  For example, for a subscription with 100 licenses,
a start date of 2021-01-01, and an end date of 2021-12-31, we'd like to allow the customer to renew that subscription
for 150 on, say, 2021-06-17.  The renewed subscription would become active on 2022-01-01 and expire on 2022-12-31.
Our data schema should support this business arrangement, and the data models should align closely with the
different logical entities involved in this business arrangement.

Decision
========

We'll introduce a ``SubscriptionPlanRenewal`` model
---------------------------------------------------

A ``SubscriptionPlanRenewal`` is a model that records the intention to renew an existing ``SubscriptionPlan`` into
a new ``SubscriptionPlan``, on or after the expiration date of the original plan.

* It will record references to both the ``SubscriptionPlan`` it is renewed `from` (the "original" plan),
  and the plan it renews `into` (the "renewed" plan).
* It records the number of licenses to create in the renewed plan.  This number must be greater than or equal
  to the number of license allowed under the original plan.
* A renewal must specify a new Salesforce Opportunity ID associated with the renewal business transaction.
* A renewal records a date on or after the original plan's expiration date on which the renewal will be processed
  into a new plan.
* It will record a ``processed`` boolean field that indicates whether the renewal has been processed into a renewed plan.

Example
-------
Here's an example ``SubscriptionPlan`` for Pied Piper, set to expire on 2021-11-30::

  +----------------------------------+----------------------------------+---------------------------------+------------+-----------------+----------------------------------+-----------+---------------------------+
  | customer_agreement_id            | plan_uuid                        | title                           | start_date | expiration_date | enterprise_catalog_uuid          | is_active | salesforce_opportunity_id |
  +----------------------------------+----------------------------------+---------------------------------+------------+-----------------+----------------------------------+-----------+---------------------------+
  | ea9683443e2148a8aa54dcb1733b80dc | fe9cc40e24a747a0b8009a11288b3ec2 | Pied Piper's First Subscription | 2020-12-01 | 2021-11-30      | 7467c9d2433c4f7eba2ec5c7798527b2 |         1 | 100000000000000000        |
  +----------------------------------+----------------------------------+---------------------------------+------------+-----------------+----------------------------------+-----------+---------------------------+

But let's say that Pied Piper decides to renew this plan well in advance of expiration.  A ``SubscriptionPlanRenewal``
record should be created that looks like this::

  +----------------------------+----------------------------------+---------------------------+--------------------+----------------+-------------------------+-----------+------------------------------+
  | created                    | prior_subscription_plan_id       | salesforce_opportunity_id | number_of_licenses | effective_date | renewed_expiration_date | processed | renewed_subscription_plan_id |
  +----------------------------+----------------------------------+---------------------------+--------------------+----------------+-------------------------+-----------+------------------------------+
  | 2020-12-09 20:01:05.373989 | fe9cc40e24a747a0b8009a11288b3ec2 | 100000000000000002        |                100 | 2021-12-01     | 2022-11-30              |         0 | NULL                         |
  +----------------------------+----------------------------------+---------------------------+--------------------+----------------+-------------------------+-----------+------------------------------+

Note that the renewal has a different ``salesforce_opportunity_id``, because the renewal is a distinct business
transaction from the purchase of the original ``SubscriptionPlan``.  Note also that the renewal could be for
the same number of licenses as the original plan, or more licenses than the original plan.  When the renewal is
processed, the ``processed`` field will become ``true``, and a new ``SubscriptionPlan`` will be created, the ``uuid``
of which will be placed in the associated renewals ``renewed_subscription_plan_id`` field.

How is the renewal processed?
-----------------------------

The actual renewal process would should primarily be a scheduled daily job that looks at all renewals
and determines if any renewed plans should be created at the time the job is run:

* If there is 1 or fewer days between the current time and the ``effective_date`` of a renewal, the renewal should
  be processed into a renewed ``SubscriptionPlan``, whose ``start_date`` is the ``effective_date``.
* The licenses of the original subscription plan should be transferred to the renewed plan.  This means simply that
  the ``subscription_plan_uuid`` foreign key of each license is updated to point to the renewed plan.
* The original subscription plan should be set to inactive, number of remaining revocations reset, and its license count set to 0.

We will also expose a new API endpoint, which accepts only a ``POST`` request, that will trigger the processing
of a specific ``SubscriptionPlanRenewal``.  We want to have this (possibly manual) means of triggering a renewal process
in case of, for example, infrastructure problems related to our cron builds.

What happens to the licenses?
-----------------------------

* The ``subscription_plan_uuid`` foreign key of transferred licenses will be updated from the original plan
  to the renewed plan.
* django-simple-history seems to not create historical records from ``bulk_create()`` - the docs indicate that it
  only tracks changes on calls to ``create()``, ``update()``, or ``delete()`` by default. Recent versions of the package
  provide utility functions to track bulk creation/updates: https://django-simple-history.readthedocs.io/en/latest/common_issues.html#bulk-creating-and-queryset-updating
* We have merged code into license-manager that will ensure, going forward, bulk actions are recorded in the license
  history tables.
* Additionally, we will backfill missing creation historical license records, based on the creation date of the license.
  This needs to be done before we transfer any licenses to new subscription plans.
* Since we already have licenses in the wild without associated historical creation tracking, we'll
  introduce some defensive checking/snapshotting that should occur prior to the license transfer process.
  This can be as simple as assuring that a historical record reflecting the license's association with the original
  subscription plan exists.

Here's a sample historical sequence of events for a license that was transferred on plan renewal::

  *************************** 1. row ***************************
                created: 2020-12-10 21:25:27.288376
               modified: 2020-12-10 21:25:27.288376
                   uuid: fcc1e65833bd4d2b992ddd9a14599a37
                 status: unassigned
        activation_date: NULL
       last_remind_date: NULL
             user_email: NULL
            lms_user_id: NULL
             history_id: 180
           history_date: 2020-12-10 21:25:27.301247
  history_change_reason: NULL
           history_type: +
        history_user_id: NULL
   subscription_plan_id: e8f588c38bc040e495817a8eb124faac
         activation_key: NULL
          assigned_date: NULL
           revoked_date: NULL
  *************************** 2. row ***************************
                created: 2020-12-10 21:25:27.288376
               modified: 2020-12-14 16:53:41.699311
                   uuid: fcc1e65833bd4d2b992ddd9a14599a37
                 status: unassigned
        activation_date: NULL
       last_remind_date: NULL
             user_email: NULL
            lms_user_id: NULL
             history_id: 197
           history_date: 2020-12-14 16:53:41.702328
  history_change_reason: NULL
           history_type: ~
        history_user_id: NULL
   subscription_plan_id: f2e6236b434e4f15a336a5d41beb521c
         activation_key: NULL
          assigned_date: NULL
           revoked_date: NULL

Row 1 represents the creation of the license in the original plan.  Row 2 represents the later modification
of the license with a new ``subscription_plan_id`` value.

What happens to the licensed enrollments?
-----------------------------------------

* We will introduce a new field, ``plan_at_time_of_enrollment``, on the ``LicensedEnterpriseEnrollment`` records.
  This gives us an even faster way to tie enrollments to plans, plus, it give us a good way to reconcile history, if needed.
* We will backpopulate this field with each license record's current subscription plan UUID.  This is only permissible
  because we have not yet transferred any licenses between subscription plans.
* After these two steps are completed, licensed enrollment records do not need to be changed during the license transfer,
  because the license UUID does not change, nor does the UUID of the subscription plan associated
  with the license at the time of enrollment.

What happens if a license is assigned but not activated until after renewal?
----------------------------------------------------------------------------

License activation relies on the association of an activation key to a license UUID.  Since the license
will only transfer to a new plan, neither of those identifiers will change, and a user should not be hindered when
a license assigned to the original plan, but that is transferred to a renewed plan, prior to the user's
activation of such a license.

Non-injective renewals
----------------------

We will not support multiple "originating" plans renewing into a new, single future plan via renewal, because this
data model does not cleanly support such an action.

Definitional note: an `injective` function (also known as a `one-to-one` function) maps distinct elements
of its domain to distinct elements of its codomain.

Consequences
============

The consequences of the above decision on our customer learner and administrator user experiences, along with the
impact on our internal business reporting, are described below.

How does this impact the subscription learner experience?
---------------------------------------------------------

* It shouldn't.
* A user's existing license is transferred over to a new, active plan that should have the same catalog.
* Ther license UUID doesn't change.
* Nothing about their enrollment state should change.
* If we start tracking the subscription UUID at time of enrollment in the ``LicensedEnterpriseCourseEnrollment`` model,
  that won't change, and we'll have a good (and easy to access) source of truth about the learner's subscription state
  at the time of enrollment.

How does this impact the subscription customer admin. experience?
-----------------------------------------------------------------

These data models, and their associated modification logic, should provide us the flexibility we need to implement
whatever user experience we want in the enterprise admin portal.  It allows us to represent to the admin user
any of the following pieces of information:

* That there is a renewal scheduled for a current subscription plan.
* When the renewal will take place.
* That a renewed plan now exists and is active.
* How many licenses the renewed and original plans contain.
* When the original and renewed plans expire.

How does this impact our business reporting?
--------------------------------------------

Assuming that the license enrollment ``plan_at_time_of_enrollment`` field is in place and backpopulated,
and that renewed plans record their own ``salesforce_opportunity_id`` and ``netsuite_product_id`` fields (which they do),
then our internal and external business reporting can continue to function as expected,
while still representing the true state of the world.

Misc. Open Questions
--------------------
* Can you renew with a different catalog product?  What happens to enrollment/revenue allocation if that action
  occurs in the middle of a month?  Can we stipulate that all plans have to end at the end of a month, and that
  renewals cannot begin in the middle of a month?
* Can we make the product ID/catalog non-editable after licensed enrollments begin to occur?
