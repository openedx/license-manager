## Description

TODO: Include a detailed description of the changes in the body of the PR

## Manual Test Plan

TODO: Include instructions for any required manual tests, and any manual testing that has
already been performed.

## Testing Checklist
- TODO: Include unit, integration, acceptance tests as appropriate
- TODO: Include accessibility (a11y) tests
- TODO: Include tests that capture the external-query scaling properties
- [ ] Check that Database migrations are backwards-compatible
- [ ] Manually test right-to-left languages and i18n
  of the changes.

## Non-testing Checklist
- TODO: Tag DevOps on your PR (user `edx/devops`), either for review
  (more specific to devops = better) or just a general FYI.
- TODO: Consider any documentation your change might need, and which
  users will be affected by this change.
- TODO: Double-check that your commit messages will make a meaningful release note.

## Post-review
- TODO: Squash commits into discrete sets of changes (see the note about release notes above)

## Reviewers
If you've been tagged for review, please check your corresponding box once you've given the :+1:.
- [ ] Code review #1 (TODO: tag a specific user)
- [ ] Code review #2 (TODO: tag a specific user)
- [ ] Docs review (required for UI strings/error messages)
- [ ] UX review
- [ ] Accessibility review
- [ ] Product review

### Areas to Consider
- [ ] i18n 
    - Are all user-facing strings tagged?
- [ ] Right-to-left
    - Will the feature work for right-to-left languages?
- [ ] Analytics
    - Are any new events being emitted?
    - Have any events been changed?
    - Are there any new user actions that should be emitted as events?
- [ ] Performance
    - What dimensions does this change scale over? Users? Courses? Course size?
    - How does the feature scale over those dimensions? Sub-linear? Linear? Quadratic? Exponential?
    - How does the scaling affect the number of external calls (database queries,
      api requests, etc) that this code makes?
- [ ] Database migrations
    - Are they backwards compatible?
    - When they run on production, how long will they take? Will they lock the table?

