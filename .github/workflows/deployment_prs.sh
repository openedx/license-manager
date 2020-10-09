#! /usr/bin/env bash

set -e

export GITHUB_USER='edx-deployment'
export GITHUB_TOKEN=$GH_ACCESS_TOKEN
export REPO_NAME='license-manager'
export GITHUB_EMAIL='edx-deployment@edx.org'

export GITHUB_UPSTREAM_PR_NUMBER=${PR_NUMBER}
export GITHUB_UPSTREAM_PR_TITLE=${PR_TITLE}
export GITHUB_WORKFLOW_URL=https://github.com/edx/${REPO_NAME}/actions/runs/$GITHUB_RUN_ID
cd ..
git clone https://edx-deployment:${GITHUB_TOKEN}@github.com/edx/edx-internal

# install hub
curl -L -o hub.tgz https://github.com/github/hub/releases/download/v2.14.2/hub-linux-amd64-2.14.2.tgz
tar -zxvf hub.tgz

hub-linux*/bin/hub api repos/edx/${REPO_NAME}/issues/${GITHUB_UPSTREAM_PR_NUMBER}/comments -f body="GitHub Actions has started building this code into a docker file.  Check status at ${GITHUB_WORKFLOW_URL}" 

cd -
make docker_push
cd ..

hub-linux*/bin/hub api repos/edx/${REPO_NAME}/issues/${GITHUB_UPSTREAM_PR_NUMBER}/comments -f body="A docker container including this PR has been built and shipped to docker hub.  Check it out at https://hub.docker.com/r/openedx/${REPO_NAME}/tags?page=1&name=${GITHUB_SHA}"

cd edx-internal

git config --global user.name "${GITHUB_USER}"
git config --global user.email "${GITHUB_EMAIL}"

# stage
git checkout -b edx-deployment/stage/$GITHUB_SHA
sed -i -e "s/newTag: .*/newTag: $GITHUB_SHA-newrelic/" argocd/applications/${REPO_NAME}/stage/kustomization.yaml
git commit -a -m "${REPO_NAME} stage deploy: $GITHUB_UPSTREAM_PR_TITLE" --author "GitHub Actions CI Deployment automation <admin@edx.org>"
git push --set-upstream origin edx-deployment/stage/$GITHUB_SHA
../hub-linux*/bin/hub pull-request -m "${REPO_NAME} stage deploy: $GITHUB_UPSTREAM_PR_TITLE" -m "Staging environment deployment of https://github.com/edx/${REPO_NAME}/pull/$GITHUB_UPSTREAM_PR_NUMBER" -m "Review and merge this PR to deploy your code to stage.edx.org" -l staging-deployment -l automerge

# prod
git checkout master
git checkout -b edx-deployment/prod/$GITHUB_SHA
sed -i -e "s/newTag: .*/newTag: $GITHUB_SHA-newrelic/" argocd/applications/${REPO_NAME}/prod/kustomization.yaml
git commit -a -m "${REPO_NAME} prod deploy: $GITHUB_UPSTREAM_PR_TITLE" --author "GitHub Actions CI Deployment automation <admin@edx.org>"
git push --set-upstream origin edx-deployment/prod/$GITHUB_SHA
../hub-linux*/bin/hub pull-request -m "${REPO_NAME} prod deploy: $GITHUB_UPSTREAM_PR_TITLE" -m "Production environment deployment of https://github.com/edx/${REPO_NAME}/pull/$GITHUB_UPSTREAM_PR_NUMBER" -m "Review and merge this PR to deploy your code to edx.org"

