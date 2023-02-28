14. Linearizable license assignment
###################################


Status
******

Accepted (March 2023)


Context
*******
The ``/assign`` API endpoint assigns unassigned licenses for a list of user emails
provided as input - it works "in bulk" by default. The core components of this operation
are currently synchronous, so for large inputs, the operation can take quite a long time
to complete (perhaps several minutes).  For large inputs, clients of this endpoint
may see a browser-level timeout before the operation actually completes in the backend.
This opens up a fairly high risk of race-conditions occuring.

We don’t set a unique constraint on ``(user_email, status)`` in the ``License`` model.
The best validation we have is via the ``License.clean()`` method,
which checks for existing assigned or activated licenses for a given email.
We updated ``License.save()`` to call ``full_clean()`` to do this validation.
However, ``License.bulk_update()`` relies on (the simple-history version of) Django's bulk_update ,
which does not call ``save()`` on each instance, and therefore, skips this validation.  The ``/assign``
endpoint uses ``License.bulk_update()`` to assign licenses to the provided list of user emails.
See https://github.com/openedx/license-manager/blob/master/docs/decisions/0012-assigning-new-license-to-revoked-user.rst
for more context on the decision to design our constrains in this way.

The ``/assign`` endpoint `does` have logic to find email addresses
that already have a license associated with the subscription plan from which licenses are assigned.
However, due to the high risk of race-conditions mentioned above, this logic is currently
not strong enough to prevent subsequent, long-running assignment operations from over-writing
state between concurrent requests.

Decision
********
We'll make license assignment `Linearizable`_ by introducing a lock at the ``SubscriptionPlan``
level.  The lock is currently only considered during the assignment operation.

.. _Linearizable: https://en.wikipedia.org/wiki/Linearizability


Consequences
************
Multiple requests to assign licenses from the same subscription plan cannot operate concurrently - the first
such request will acquire the lock, and all following requests will fail.  The first request will
release the lock when it returns, successfully or not.
This means that assignment operations for which the lock cannot be acquired will fail, and clients
should eventually handle this failure with grace.

Alternatives Considered
***********************
We should, in the future, wrap the entire license assignment operation in an asynchronous task,
because this operation can be quite long-running.
It'd be even better to constrain License ``(user_email, status)`` at the database level, but
we can't currently do that in a way that meets our usage requirements (see linked ADR above).

Additionally, we considered using Redis to implement the lock mechanism, via the
https://github.com/brainix/pottery#redlock, but at the time of this writing, we don't
yet have a good "paved road" for using Redis as a store of application-level data; it's only
well-supported within the edX ecosystem as a Celery broker.
