Thank you for submitting a pull request to Nova! Here are some guidelines for submitting that will help get your addition merged as soon as possible:

-   Use the pull request title to summarize what the pull request does. Example: "Add Resource Create and Update Changes to ActionResource", or "Fix Regression in Clicking Pagination 'Next Page' Link".
-   Refrain from add extra information to the pull request title. This includes text such as the version number you're targeting, or the type of pull request (bug fix, feature request, etc). Use the pull request description to convey this. All pull requests should be submitted to the current major version anyways, so it just clogs up the list.
-   Make sure the pull request description contains a complete explanation of what the pull request does. This includes any behavior it changes or fixes, and what other pieces it may affect. PRs without this will be closed.
-   Bug fix pull requests should include any relevant issues from [laravel/nova-issues](http://github.com/laravel/nova-issues) that they fix.
-   In general, we do not merge pull requests that only attempt to "clean up" the codebase or update dependencies. These types of PRs tend to introduce hard-to-track-down bugs and are mostly subjective. We prioritize merging provable bugs above all else.
-   Pull requests that are indicated as "work in progress" in their description will be closed after 15 days if there is no further progress on the feature.
-   Make sure to add tests for any new features you're adding, bug fixes, or other behavior changes. Pull requests without these will be closed. If a certain feature makes sense to test only in the browser, submit the test as a pull request to [laravel/nova-dusk-suite](http://github.com/laravel/nova-dusk-suite) and link to this pull request in your pull request's description.

Thank you!
Nova Team
