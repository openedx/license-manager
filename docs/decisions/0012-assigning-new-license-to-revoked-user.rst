12. Assigning new license to revoked Users
=======================

Status
======

Supersedes 0005-unrevoking-licenses.rst


Context
=======

As documented in `adr 0005 <https://github.com/openedx/license-manager/blob/master/docs/decisions/0005-unrevoking-licenses.rst>`_, when a user whose license has been revoked
is assigned a license within the same subscription plan, the previously revoked license is reassigned to the user.
An unassigned license is then removed from the plan to account for the license that was added during the revocation process.

Unrevoking a license involves changing data for a license and deleting a license; we would like to simplify this process
and preserve the state of revoked licenses.
Assigning a new license rather than unrevoking was an alternative that was considered, and we want to move
forward with this behavior in the future.


Decision
========

The concept of `unrevoking` a license will be deprecated and a new license will always be assigned to a user.

The following addresses the points that were brought up previously:

1. It would look like a learner has multiple licenses in the same plan if we assign a new license.

Proposed solutions:
  * We will return all of the license and let the UI handle the logic of hiding revoked licenses if needed.

2. We have unique constraints on ``(subscription_plan, user_email)`` and ``(subscription_plan, lms_user_id)``.

Proposed solution:
  * We will drop the unique constraint and instead rely on application logic to prevent multiple active/assigned licenses.
    The `/assign` endpoint already validates that a user does not have an activated license before assigning a new license.
    Unfortunately MySQL does not support conditional indexes and thus we can't just add a constraint similar to

    ```
    models.UniqueConstraint(
        fields=('subscription_plan', 'user_email',),
        condition=Q(status__in=[ASSIGNED, ACTIVATED]),
        name='unique_email_if_assigned_or_activated'
    )
    ```

Consequences
============

* We will no longer `unrevoke` any licenses.
* A user can have multiple declined licenses within a subscription plan.
* Admins will be able to maintain a more accurate history of an individual's license states in the admin portal.
* Revoked licenses will be unmodified and we won't need to dig through the history table to see the original license state.
* There will never be the scenario where some LicensedEnterpriseCourseEnrollments are revoked
  but others are not for the same license UUID. This can occur today if a user enrolls in a course with a license that was unrevoked.