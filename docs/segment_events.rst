WARNING: THIS DOCUMENT IS A PROPOSAL AT THIS TIME, NONE OF THESE EVENTS ARE IMPLEMENTED YET.

Segment events
==============

``license-manager`` emits several Segment events.

edx.bi.user.enterprise.license-status-change.<new-status>
---------------------------------

The possible values of the **new status** event name match the subscriptions.License lifecycle and include: 
edx.bi.user.enterprise.license-status-change.assigned
edx.bi.user.enterprise.license-status-change.activated
edx.bi.user.enterprise.license-status-change.unassigned
edx.bi.user.enterprise.license-status-change.revoked

Emitted when a new ``subscriptions.License`` record's status field changes from a previous value. 

The event contains these properties:

- **lms_user_id**: The latest LMS User Id of this license if it exists, for use in event triggering/personalization based on this event. 
  Note that because licenses can be assigned ahead by admins, this field may be empty. As a result, the user_email field will have to be used 
  be used for transaction-triggered communications if no lms_user_id is present.
- **assigned_date**: Date this license was assigned to a particular user email. May be empty.
- **activation_date**: Date this license was activated. May be empty.
- **user_email**: The email assigned to this license. May be empty if this license is not assigned to a user yet.
- **enterprise_uuid**: The Enterprise UUID associated with this license. 



