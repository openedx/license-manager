5. Unrevoking licenses
======================

Status
======

Accepted July 2021

Context
=======

When a license is revoked, the current behavior transitions that license to the ``revoked`` state,
then adds a new license to the available "pool" of licenses for the associated subscription plan.
If an admin then re-invites that learner, the revoked license will transition to the ``unassigned`` state
and re-enter the pool of available unassigned licenses, before grabbing an unassigned
license from the plan's pool to assign to the learner.
The net effect of this logic is to add an additional unassigned license for the plan, to
which the plan is not entitled.

Decision
========

We'll do the follow for license assignment actions that involve un-revoking a license.  For any
to-be-assigned user email that's associated with a currently revoked license:

* We'll re-assign the currently revoked license to the email/user.
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

We'll modify the assign action to do model writes atomically.

Users for whom a licenses is unrevoked during an assign action will still receive
assignment notifications, as net-new users would.

Consequences
============

* We're changing data about unrevoked licenses (all of the dates mentioned above), which
  means we won't be able to see the original values (from the original assignment and/or activation of the license)
  without looking at the history table for the license model.  This history is not currently exposed
  to enterprise admins in the admin portal.
