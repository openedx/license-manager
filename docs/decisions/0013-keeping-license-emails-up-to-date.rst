13. Keeping license emails up to date
=====================================

Status
======

Accepted

Context
=======

Currently, the `/learner-licenses/` endpoint returns licenses that match with the user's email provided in the JWT.
However a user's email could change, and the endpoint would fail to return the user's licenses if that occurs.

We want to return the correct licenses even if a user has changed their email and also update the `user_email` field
on their licenses to reflect the new email.

Decision
========

In an event driven architecture, an event would be dispatched by the LMS when a user changes their information. License
Manager would consume this event and update all of the licenses associated with the user. However we do not have
such an infrastructure set up yet and will have to rely on the JWT passed in with each request to determine if a user
has changed their email.

Whenever a user fetches their learner licenses, we will query for licenses that are associated with **both**
the email and the lms_user_id that is present in the JWT payload. This will ensure that even if a user has changed their email,
licenses associated with the lms_user_id will still be returned. We have to query by email as well because an assigned license might not have
an lms_user_id yet. If we detect that the user's email has changed (i.e. the `user_email` field on the licenses do not match with the one in the JWT),
we will update the `user_email` field on all of the user's licenses.

Consequences
============
* If a user has an assigned license but changes their email before activating their license, there is no way for us to update
  the unassigned license because the lms_user_id has not been set. Until we have access to a better solution (i.e. consuming an event), there is no workaround
  for this problem. The admin will have to reassign a new license in this case.

Alternatives Considered
=======================
* We could also set the lms_user_id on unassigned licenses whenever the user hits the `/learner-licenses/` endpoint.
  However it is unlikely that the user will visit the learner portal but change their email before activating their license in the same session.
