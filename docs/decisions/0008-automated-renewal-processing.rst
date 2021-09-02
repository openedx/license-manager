8. Automated Subscription Plan Renewals
======================

Status
======

* Accepted September 2021

Context
=======

Currently, subscription renewals must be processed manually by an administrator through the Django Admin using the "Process selected renewal records" action.
We'd like to automate this process so that renewals with an upcoming effective date are automatically processed. 
The decision below describes the automated process. Refer to ADR 0004 for more details on the renewal process itself.

Decision
========

A renewal with an upcoming (within the next 12 hours by default) effective date will be in its renewal processing window.
Subscription plans with a renewal within its renewal processing window will be locked, and admins will not be able to take
actions related to the plan (i.e. invite learners, revoke licenses). 
A cron job will run every 6 hours to execute the process_renewals command, which will fetch and process renewals.
Failure to process a renewal will trigger an OpsGenie P1 Alert, but the job will continue to process other renewals normally.
The subscription renewal process itself is atomic, and changes will not be commited in the event of a failure.

Consequences
============

* We assume that a renewal record will not be created until business approval is granted. 
  The prescence of a renewal record indicates that it can be automatically processed.
