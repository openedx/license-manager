Request and approve license assignment
======================================

Status
======

Proposed December 2021

Context
=======

Learners who can browse the Enterprise Learner Portal without a subsidy should be able to
request a license from their enterprise administrator.  In the Enterprise Admin Portal, an
enterprise admin should be able to see which learners have requested a license, and then
either assign those learners a license, or deny the request.

Note that, in a separate workstream, we'd also like allow learners to request an
Enterprise Coupon Code and have admins approve/deny those requests.  Though very similar,
this ADR deals only with the requesting and assignment of subscription plan licenses.

Decision
========

License Request learner experience
----------------------------------
An enterprise learner must have access to the learner portal
with a customer that has at least one current, active Subscription Plan.
Somewhere in the user interface, it is made clear to the learner
what a license is, and that they may request a license from their learning administrator.
The learner must be linked to the enterprise customer,
that is, an ``EnterpriseCustomerUser`` record must exist for this (user, customer)
association.
We'll display a request button in the UI even if there are no unassigned
licenses available for this customer. In the future, displaying such unfulfillable requests
to the customer admin could act as a "nudge" to the admin to procure more licenses.

License Request data model
--------------------------
We'll store the following data related to the license request:

* A UUID to uniquely identify the request record.
* The learner making the request, in the form of their email address.
* The associated ``CustomerAgreement`` (i.e. the associated enterprise customer)
* When the request was made.
* When the request was fulfilled.
* The assigned license UUID which fulfilled the request.  Note that the license record contains an assignment datetime.
* The admin who assigned the license.
* Whether/when the request was denied (mutually exclusive with the license UUID field).
* The admin who denied the request.
* A history table

License Request admin experience
--------------------------------
There will be a new user interface in the admin portal displaying
a data table of license requests.  From this data table, an admin
is able to either approve (assign licenses) requests, or deny them.
Either action may be made in bulk.

If the customer has only one Subscription Plan
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
This case is almost functionally equivalent to the current experience
of assigning licenses to one or more learners by email address.  We'll allow
for bulk assignment as long as the Subscription Plan has enough
unassigned licenses to assign to the number of selected requesting users.

If the customer has multiple Subscription Plans
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
For this case, the administrator must indicate from which plan
they'd like to allocate unassigned licenses to the requesting users.
We will only allow licenses from a single plan to be assigned to a set
of selected requesting users; an admin may not assign licenses from
multiple plans amongst multiple requesting learners in a single bulk action request.

Denying a License Request
^^^^^^^^^^^^^^^^^^^^^^^^^
In this case, no license will be assigned to the requesting learner.
The License Request record should be updated to reflect the denial.

New License Request API endpoints
---------------------------------
We'll create a new Viewset to deal with License Request CRUD operations.

* ``GET`` (retrieve) A learner should be able to see their own License Request records.
* ``GET`` (list) An admin should be able to list all License Request records
  associated with their CustomerAgreement.
* ``POST`` (create) A learner should be able to create a new License Request record.
* ``PUT`` An admin should be able to update a License Request record as denied.
* ``DELETE`` A learner should be able to delete their own request record.

Modify the license assignment endpoint
--------------------------------------
We already expose an ``assign`` endpoint to assign licenses from a single
plan to one or more learners by email address, via a POST request.
The endpoint should begin to accept an optional list of License Request UUIDs
in the request payload, call it ``request_uuids``.
The ``user_emails`` key would not be required if ``request_uuids`` is present in the payload.
The endpoint should be modified to update the corresponding License request records
with the UUID of the assigned license.

Consequences
============
Open considerations or questions:

* How to deal with requests from learners who have previously been
  assigned a license, but which license is now revoked?
