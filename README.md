# tap-github

This is a [Singer](https://singer.io) tap that produces JSON-formatted
data from the GitHub API following the [Singer
spec](https://github.com/singer-io/getting-started/blob/master/docs/SPEC.md).

This tap:
- Pulls raw data from the [GitHub REST API](https://developer.github.com/v3/)
- Extracts the following resources from GitHub for a single repository:
  - [Assignees](https://docs.github.com/en/rest/reference/issues#list-assigneess)
  - [Collaborators](https://docs.github.com/en/rest/reference/repos#list-repository-collaborators)
  - [Commits](https://docs.github.com/en/rest/reference/repos#list-commits)
  - [Commit Comments](https://docs.github.com/en/rest/reference/repos#list-commit-comments-for-a-repository)
  - [Events](https://docs.github.com/en/rest/reference/issues#events)
  - [Issues](https://docs.github.com/en/rest/reference/issues#list-repository-issues)
  - [Issue Events](https://docs.github.com/en/rest/reference/issues#list-issue-events-for-a-repository)
  - [Issue Milestones](https://docs.github.com/en/rest/reference/issues#list-milestones)
  - [Projects](https://docs.github.com/en/rest/reference/projects#list-repository-projects)
  - [Project Cards](https://docs.github.com/en/rest/reference/projects#list-project-cards)
  - [Project Columns](https://docs.github.com/en/rest/reference/projects#list-project-columns)
  - [Pull Requests](https://docs.github.com/en/rest/reference/pulls#list-pull-requests)
  - [PR Commits](https://docs.github.com/en/rest/reference/pulls#list-commits-on-a-pull-request)
  - [Releases](https://docs.github.com/en/rest/reference/repos#list-releases)
  - [Comments](https://docs.github.com/en/rest/reference/issues#list-issue-comments-for-a-repository)
  - [Reviews](https://docs.github.com/en/rest/reference/pulls#list-reviews-for-a-pull-request)
  - [Review Comments](https://docs.github.com/en/rest/reference/pulls#list-review-comments-in-a-repository)
  - [Stargazers](https://docs.github.com/en/rest/reference/activity#list-stargazers)
  - [Teams](https://docs.github.com/en/rest/reference/teams#list-teams)
  - [Team Members](https://docs.github.com/en/rest/reference/teams#list-team-members)
  - [Team Memberships](https://docs.github.com/en/rest/reference/teams#get-team-membership-for-a-user)
- Outputs the schema for each resource
- Incrementally pulls data based on the input state

## Quick start

1. Install

   We recommend using a virtualenv:

    ```bash
    > virtualenv -p python3 venv
    > source venv/bin/activate
    > pip install tap-github
    ```

2. Create a GitHub access token

    Login to your GitHub account, go to the
    [Personal Access Tokens](https://github.com/settings/tokens) settings
    page, and generate a new token with at least the `repo` scope. Save this
    access token, you'll need it for the next step.

3. Create the config file

    Create a JSON file containing the start date, access token you just created
    and the path to one or multiple repositories that you want to extract data from. Each repo path should be space delimited. The repo path is relative to
    `https://github.com/`. For example the path for this repository is
    `singer-io/tap-github`. You can also add request timeout to set the timeout for requests which is an optional parameter with default value of 300 seconds.

    ```json
    {"access_token": "your-access-token",
     "repository": "singer-io/tap-github singer-io/getting-started",
     "start_date": "2021-01-01T00:00:00Z",
     "request_timeout": 300}
    ```

    ### GitHub App: sync every installation automatically

    Instead of an access token and an explicit repository list, you can provide
    only your GitHub App's `app_id` and `private_key` (the `.pem`). The tap then
    authenticates as the app, discovers **every organization/account the app is
    installed on**, mints a scoped installation token for each, and syncs **all
    repositories** that installation can access — no `installation_id` or
    `repository` needed.

    ```json
    {"app_id": "123456",
     "private_key": "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----\n",
     "start_date": "2021-01-01T00:00:00Z",
     "request_timeout": 300}
    ```

    This mode activates automatically whenever `app_id` + `private_key` are
    present and `installation_id` is omitted. Supplying `installation_id` keeps
    the original single-installation behavior.

    `app_id` and `private_key` may also be provided via the `GITHUB_APP_ID` and
    `GITHUB_PRIVATE_KEY` environment variables instead of the config file (the
    config file takes precedence when both are set).

4. Run the tap in discovery mode to get properties.json file

    ```bash
    tap-github --config config.json --discover > properties.json
    ```
5. In the properties.json file, select the streams to sync

    Each stream in the properties.json file has a "schema" entry.  To select a stream to sync, add `"selected": true` to that stream's "schema" entry.  For example, to sync the pull_requests stream:
    ```
    ...
    "tap_stream_id": "pull_requests",
    "schema": {
      "selected": true,
      "properties": {
        "updated_at": {
          "format": "date-time",
          "type": [
            "null",
            "string"
          ]
        }
    ...
    ```

6. Run the application

    `tap-github` can be run with:

    ```bash
    tap-github --config config.json --properties properties.json
    ```

---

Copyright &copy; 2018 Stitch
