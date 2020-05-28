1. Purpose of the license manager service
=========================================


Status
======

Accepted


Context
=======

edX would like to offer a subscriptions payment option, where a plan is purchased that grants unlimited enrollment to
courses in the subscription catalog. We are initially considering this from the enterprise point of view, where an
enterprise purchases a subscription plan with a number of licenses to assign to their learners. For this initial
enterprise approach, licenses will have a fixed price per learner and will be valid for a minimum of one-year after
payment. The subscriptions feature may eventually support non-enterprise use cases, where individual learners can
purchase subscription plans for themselves, but this is out of scope for the MVP.


Decision
========

This service was created to manage the creation and assignment of licenses, which we see as the center point of the
enterprise subscriptions feature. A license is what entitles an individual learner to enroll in as many courses as they
want out of the subscription's course catalog for a set period of time. When enterprises purchases a subscription plan,
ECS (the Enterprise Customer Support team) will create that subscription plan in Django Admin, which will in turn create
the individual licenses for the subscription plan. From there, the service's purpose is to serve APIs that allow for
managing licenses through actions such as creating, assigning, and deactivating licenses, as well as determining the
validity of a learner's license for accessing a certain piece of content.

We considered using an existing third-party subscription billing service such as Recurly_ to handle the majority of the
work around managing subscriptions. However, even with a third party service for subscription management we would need
a service to handle managing individual licenses and the edX business logic around the access a license grants.
Our initial goal is to release an MVP where we do not intend to introduce all of the functionality that a subscription
management service would provide (i.e. recurring billing, self-service purchase). Because of this, we decided to build 
basic subscription management functionality into this service for the MVP. When we reach the point of introducing
those features that are best handled by a third-party subscription management software, this service will become the
integration point between that system and our edX systems.

.. _Recurly: https://recurly.com/


Consequences
============

As this service was created to support a minimally viable subscriptions offering, we are not directly supporting all use
cases such as allowing learners to purchase subscription plans for themselves. While we aim to build the service so
that we can support future use cases such as B2C subscriptions, there will likely be certain constraints specific to the
non-enterprise use case that will need to be addressed in future work.

Our decision to forgo integrating with a third-party subscription management service for the MVP also has a few
consequences. There will be additional manual work for ECS in creating and managing subscriptions through the service's
Django admin. There will also be additional work on coordinating the billing of subscription plans as our service will
not have any billing management functionality. However, these decisions were intentional in order to get the product to
market faster, and we plan to address these gaps in future iterations of the product.
