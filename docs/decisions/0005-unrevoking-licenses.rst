5. Unrevoking licenses
======================

Status
======

Accepted July 2021

Context
=======

When a learner's license is revoked, the current behavior transitions that license to the ``revoked`` state,
then adds a new, unassigned license to the available "pool" of licenses for the associated subscription plan.
The idea behind this is that revoked licenses shouldn't count against the total number of licenses allocated
for the subscription plan (to a point - this is where a revocation cap would come into play).

Currently, if an admin revokes a learner's license, and later re-assigns a license to that same learner,
we transition the "original" (revoked) license to the ``unassigned`` state, before a different unassigned
license from the plan's pool is assigned to the learner.  The original license thus re-enters
the pool of available unassigned licenses.

The net effect of this logic is that an additional unassigned license,
to which the plan is not entitled, is added to the plan.

The decision below describes how we will fix this defect.

Decision
========

When un-revoking a license for any to-be-assigned user email that's currently associated with a revoked license,
we'll do the following:

* We'll re-assign the currently associated revoked license to the user email.
* We'll set the ``lms_user_id`` to null and let it become populated during license activation (as it usually is).
* We'll switch its status back to ``assigned``.
* We'll set that license's ``assignment_date`` and ``last_remind_date`` to now
* We'll set the ``revoked_date`` and ``activation_date`` to null.
* The ``activation_key`` will remain the same.

Furthermore, we'll now delete an existing ``unassigned`` license from the plan's pool, to account
for the fact that we previously added an additional license to the pool during the revoke action.

This means that during the assign action, before doing any license assignment, we must
ensure that there are enough licenses in the plan's pool to assign to net-new users
while taking into account any deletions that occur due to unrevocation.  That is, we
must check that:
``num_emails_to_assign <= total_unassigned_licenses_for_plan + revoked_licenses_for_reassignment``

We'll modify the assign action to do the reads of license counts and all of the writes
in one atomic transaction.

Users for whom a licenses is unrevoked during an assign action will still receive
assignment notifications, as net-new users would.

Consequences
============

* We're changing data about unrevoked licenses (all of the dates mentioned above), which
  means we won't be able to see the original values (from the original assignment and/or activation of the license)
  without looking at the history table for the license model.  This history is not currently exposed
  to enterprise admins in the admin portal.

Alternatives Considered
=======================

Why not assign a new unassigned license as we currently do and delete the revoked license?

* License uuids are associated with enrollments in edx-enterprise for book-keeping.
  Deleting a license means that some licensed enrollment records would have no associated
  license record in license-manager, which would make our bookkeeping invalid.

Another proposal, which prevents the need to delete any records, would be to simply wipe all data from
license that is revoked rather than keeping the record and adding a new license to the pool.

* We can't do this because we associate a license's uuid with licensed-enrollments.  If a second
  learner came along with the same license uuid as the first user and enrolled in the same course,
  that could violate some data constraints.

If there is already a new license created when one is revoked, why not just assign
the new license and have the revoked license stay as it is?

* From a product perspective, doing this would make it appear in the admin portal
  as if the learner has multiple licenses in the same plan.
  From a data perspective, we have unique constraints on ``(subscription_plan, user_email)``
  and ``(subscription_plan, lms_user_id)`` on the ``License`` model, so we can't give a user/email
  two licenses in the same plan.
