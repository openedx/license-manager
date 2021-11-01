11. Product model
======================

Status
======

Accepted

Context
=======

It is critical that subscription plans be created with the correct Netsuite product id as it determines how our reporting and financial accounting systems interpret and treat a subscription license enrollment.
Currently the Netsuite product id is a numeric field that is manually entered during the creation of a subscription plan and errors have been common during this creation process.
The data team has a test for the validity of the Netsuite product id entered, but a failure in this test causes a disruption in all our normal data transformation steps
We want to eliminate the manual entry process and prevent errors in the future.

Decision
========

In order to represent the relationship between subscription plans and our backend business products, we will create a new model ``Product`` which
details the type of product that was sold to a customer to access a subscription plan.

The ``Product`` model will have the following fields:

* ``name``
    * short name as designated by Product/ECS, i.e. 'B2B', 'OC'
* ``description``
    * a description of the product
* ``netsuite_id``
    * The netsuite_id of the product that was sold to the customer
* ``plan_type``
    * The plan type that the product falls under (as of writing plan types include 'OCE', 'Trials', 'Standard Paid')

The transition to using the new Product model will be a multi-step process.

1. The ``Product`` model is created. The ``netsuite_product_id`` and ``plan_type`` fields on the ``SubscriptionPlan`` model will be marked as deprecated and
   a ``product`` field will be added to reference the new ``Product`` model.

2. Entries for current products will be created in all environments.

3. A migration will be applied to back-populate the ``product_id`` field (must be optional initially) on all subscription plans.

4. Remove references to the now deprecated ``netsuite_product_id`` and ``plan_type`` fields on subscription plans and use the fields
   on ``Product`` instead.

5. Notify the data team of these changes and how to adjust their queries.

6. Another migration will be applied to remove the deprecated columns and make ``product_id`` required on ``SubscriptionPlan``.

After these steps a product_id will have to be selected during the subscription plan creation process.