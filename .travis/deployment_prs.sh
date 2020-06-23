#! /usr/bin/env bash

export GITHUB_USER='edx-deployment'
export GITHUB_TOKEN=$GITHUB_ACCESS_TOKEN
export REPO_NAME='license-manager'

export GITHUB_UPSTREAM_PR_NUMBER=$(echo $TRAVIS_COMMIT_MESSAGE | sed -e 's/.*#//' -e 's/ .*//');

cd ..
git clone https://edx-deployment:${GITHUB_ACCESS_TOKEN}@github.com/edx/edx-internal

# install hub
curl -L -o hub.tgz https://github.com/github/hub/releases/download/v2.14.2/hub-linux-amd64-2.14.2.tgz
tar -zxvf hub.tgz

hub-linux*/bin/hub api repos/edx/${REPO_NAME}/issues/${GITHUB_UPSTREAM_PR_NUMBER}/comments -f body="travis has started building this code into a docker file.  Check status at ${TRAVIS_BUILD_WEB_URL}" 

cd -
make travis_docker_push
cd ..

hub-linux*/bin/hub api repos/edx/${REPO_NAME}/issues/${GITHUB_UPSTREAM_PR_NUMBER}/comments -f body="A docker container including this PR has been built and shipped to docker hub.  Check it out at https://hub.docker.com/r/openedx/${REPO_NAME}/tags?page=1&name=${TRAVIS_COMMIT}" 

cd edx-internal

# stage
git checkout -b edx-deployment/stage/$TRAVIS_COMMIT
sed -i -e "s/newTag: .*/newTag: $TRAVIS_COMMIT-newrelic/" argocd/applications/${REPO_NAME}/stage/kustomization.yaml
git commit -a -m "${REPO_NAME} stage deploy: $TRAVIS_COMMIT_MESSAGE" --author "Travis CI Deployment automation <admin@edx.org>"
git push --set-upstream origin edx-deployment/stage/$TRAVIS_COMMIT
../hub-linux*/bin/hub pull-request -m "${REPO_NAME} stage deploy: $TRAVIS_COMMIT_MESSAGE" -m "Staging environment deployment of https://github.com/edx/${REPO_NAME}/pull/$GITHUB_UPSTREAM_PR_NUMBER" -m "Review and merge this PR to deploy your code to stage.edx.org" -l staging-deployment -l automerge

# prod
git checkout master
git checkout -b edx-deployment/prod/$TRAVIS_COMMIT
sed -i -e "s/newTag: .*/newTag: $TRAVIS_COMMIT-newrelic/" argocd/applications/${REPO_NAME}/prod/kustomization.yaml
git commit -a -m "${REPO_NAME} prod deploy: $TRAVIS_COMMIT_MESSAGE" --author "Travis CI Deployment automation <admin@edx.org>"
git push --set-upstream origin edx-deployment/prod/$TRAVIS_COMMIT
../hub-linux*/bin/hub pull-request -m "${REPO_NAME} prod deploy: $TRAVIS_COMMIT_MESSAGE" -m "Production environment deployment of https://github.com/edx/${REPO_NAME}/pull/$GITHUB_UPSTREAM_PR_NUMBER" -m "Review and merge this PR to deploy your code to edx.org"

