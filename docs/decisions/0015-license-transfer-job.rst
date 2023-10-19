15. License Transfer Jobs
#########################

Status
******
Accepted (October 2023)

Context
*******
There are some customer agreements for which we want to support transferring
licenses between Subscription Plans, particularly in the following scenario:

* A learner is assigned (and activates) a license in Plan A.
* By some threshold date for Plan A, like a "lock" or "cutoff" time,
  the plan is closed (meaning no more licenses will be assigned from that plan).
* There’s a new, rolling Subscription Plan B that starts directly
  after the lock time of Plan A.

In this scenario, We want to give the learner an opportunity to
continue learning via a subscription license under Plan B.
Furthermore, we want the enrollment records to continue to be associated
with the original license, but for the license to now be associated with plan B
(which may be necessary for back-office reporting purposes).

Decision
********
We've introuduced a ``LicenseTransferJob`` model that, given a set of
activated or assigned license UUIDs, will transfer the licenses from
an old plan to a new plan via a ``process()`` method.  This method
has several important properties:

1. It support dry-runs, so that we can see which licenses **would** be
   transferred without actually transferring them.
2. It's idempotent: calling ``process()`` twice on the same input
   will leave the licenses in the same output state (provided no other
   rouge process has mutated the licenses outside of these ``process()`` calls.).
3. It's reversible: If you transfer licenses from plan A to plan B, you
   can reverse that action by creating a new job to transfer from plan B
   back to plan A.

The Django Admin site supports creation, management, and processing of
``LicenseTransferJobs``.

Consequences
************
Supporting the scenario above via LicenseTransferJobs allows us
to some degree to satisfy agreements for rolling-window subscription access;
that is, subscriptions where the license expiration time is determined
from the perspective of the license's activation time, **not** the plan's
effective date.

Alternatives Considered
***********************
None in particular.
