7. Plan Type and its behaviour on data reporting and subscription plans
=======================================================================

Status
======
?

Context
=======

For the Trials v1 project, we needed a new way to distinguish between Trials, paid subscriptions and other non-paid subscription plans (primarily OCE).
Previous data reporting used a Netsuite product id of 0 to distinguish OCE and remove it from reporting on paid plans.
We can't also use 0 for Trials, so either we would make up another netsuite id or we approach it differently.

Decision
========

Terms ahead:

* Salesforce Opportunity id
    * This is a unique id generated when the sales team saves a customer transaction in Salesforce.
* Netsuite Product id
    * This is an id used to designate paid edX products. Each id is unique per plan type, but is not unique per subscription plan.
* Internal [use] only
    * This designates plans used by developers and ECS for testing. It should never refer to a real customer's subscription plan.

To support both individual reporting on different types of subscription plans and exclusion by types and flags, we implemented a new model that would be a foreign key on SubscriptionPlan and be a dropdown selection in the ``SubscriptionPlan`` Django Admin form.

The ``PlanType`` model will have the following fields:

* ``label``
    * short name as designated by Product/ECS (as of writing these include 'OCE', 'Trials', 'Standard Paid', and 'Test' (This is being removed))
* ``description``
* ``is_paid_subscription``
    * Boolean flag to designate paid plan types
* ``ns_id_required``
    * Boolean flag to designate whether a plan requires a Netsuite id
* ``sf_id_required``
    * Boolean flag to designate whether a plan requires a Salesforce opportunity id.

All of these fields allow for customization of logic (currently we utilize Plan Type in determining which email templates to use) as well as allowing Data Engineering to customize and group reports based on particular plan types.

The fields will be used in the ``SubscriptionPlan`` Django Admin form to conditionally require fields on the form.
Specifically:

* If not internal, the ``ns_id_required`` and ``sf_id_required`` fields are used in validation of the ``SubscriptionPlan`` Salesforce Opportunity id and Netsuite id form fields. If these are required and not filled in, the form will fail validation and highlight the errors.
* When using the ``for_internal_use_only`` flag on the ``SubscriptionPlan`` form, id requirements are ignored.

Developers who are testing should use a subscription plan most relevant to their tests, but use the ``for_internal_use_only`` flag to filter it from DE reports.

Consequences
============

For the bulk of these changes, the biggest consequence is that Data Engineering now has multiple ways to distinguish subscription plan data.

Some other important consequences to note is that this decision does mark a change in the currently implemented structure. As of this writing PlanTypes are already implemented, however as documented it requires changes.

* ``Test`` plan type will be removed.
* ``internal_use_only`` boolean field will be removed from ``PlanType`` model.
* ``SubscriptionPlan`` Django Admin form will need updates to use ns/sf ids conditionally on the ``for_internal_use_only`` flag.

