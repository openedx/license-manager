2. Introduction of a Customer Agreement Model
=============================================


Status
======

Accepted (circa November 2020)


Context
=======

Not all subscriptions sales are simple - there are some transactions that will occur in the subscription life cycle
such as renewals, additional "batches", or staggered starting times that we want to support.  We want the structure of
our data models to reflect, within reason, the nature of these business arrangements.


Decision
========

We introduced a new model, ``CustomerAgreement``::

  CREATE TABLE `subscriptions_customeragreement` (
    `created` datetime(6) NOT NULL,
    `modified` datetime(6) NOT NULL,
    `uuid` char(32) NOT NULL,
    `enterprise_customer_uuid` char(32) NOT NULL,
    `enterprise_customer_slug` varchar(128) NOT NULL,
    `default_enterprise_catalog_uuid` char(32) DEFAULT NULL,
    PRIMARY KEY (`uuid`),
    UNIQUE KEY `enterprise_customer_uuid` (`enterprise_customer_uuid`),
    UNIQUE KEY `enterprise_customer_slug` (`enterprise_customer_slug`)
  )

This model represents an agreement with a specific enterprise customer.  It records the customers ``uuid`` and ``slug``
fields from the edx-enterprise ``EnterpriseCustomer`` model.

The intention of the ``default_enterprise_catalog_uuid`` field is to provide the option
to not supply an ``enterprise_catalog_uuid`` on the ``SubscriptionPlan``, and instead use a default defined
in the agreement.  It should provide a small convenience for cases where a customer wants to keep renewing
a subscription for the same catalog multiple times.

The ``SubscriptionPlan`` model no longer contains a ``enterprise_customer_uuid`` field.  In it's place,
there is a non-null foreign key on ``CustomerAgreement.uuid``.

Here's an example of a ``CustomerAgreement`` record::

  +----------------------------------+----------------------------------+--------------------------+---------------------------------+
  | customer_agreement_uuid          | enterprise_customer_uuid         | enterprise_customer_slug | default_enterprise_catalog_uuid |
  +----------------------------------+----------------------------------+--------------------------+---------------------------------+
  | ea9683443e2148a8aa54dcb1733b80dc | 378d5bf0f67d4bf78b2acbbc53d0f772 | pied-piper               | NULL                            |
  +----------------------------------+----------------------------------+--------------------------+---------------------------------+

And an example of two "batches" of ``SubscriptionPlans`` that are defined under this agreement::

  +----------------------------------+----------------------------------+----------------------------------+------------+-----------------+----------------------------------+-----------+---------------------------+
  | customer_agreement_id            | plan_uuid                        | title                            | start_date | expiration_date | enterprise_catalog_uuid          | is_active | salesforce_opportunity_id |
  +----------------------------------+----------------------------------+----------------------------------+------------+-----------------+----------------------------------+-----------+---------------------------+
  | ea9683443e2148a8aa54dcb1733b80dc | b0c4d2820dd14ac7bafecf3bf2b38a93 | Pied Piper's Second Subscription | 2021-02-01 | 2022-01-31      | 7467c9d2433c4f7eba2ec5c7798527b2 |         0 | 100000000000000001        |
  | ea9683443e2148a8aa54dcb1733b80dc | fe9cc40e24a747a0b8009a11288b3ec2 | Pied Piper's First Subscription  | 2020-12-01 | 2021-11-30      | 7467c9d2433c4f7eba2ec5c7798527b2 |         1 | 100000000000000000        |
  +----------------------------------+----------------------------------+----------------------------------+------------+-----------------+----------------------------------+-----------+---------------------------+

Consequences
============

The most notable change is that a single customer, via a ``CustomerAgreement``, may now have multiple (active)
``SubscriptionPlans`` at any time.  This supports the example use case of rolling "batches" of subscriptions.

The Django Admin page for ``SubscriptionPlans`` will change:

* A ``CustomerAgreement`` instance must now be created during the creation of a ``SubscriptionPlan``.  The ``uuid``
  and ``slug`` fields should be copied from the ``EnterpriseCustomer`` model (see edx-enterprise).
* The ``enterprise_customer_uuid`` field is no longer directly accessible from this model.
  An administrator of license-manager must now access it from plan's related ``CustomerAgreement``.
