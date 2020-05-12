#! /usr/bin/env bash

export GITHUB_USER='edx-deployment'
export GITHUB_TOKEN=$GITHUB_ACCESS_TOKEN

cd ..
git clone https://edx-deployment:${GITHUB_ACCESS_TOKEN}@github.com/edx/edx-internal

# install hub
curl -L -o hub.tgz https://github.com/github/hub/releases/download/v2.14.2/hub-linux-amd64-2.14.2.tgz
tar -zxvf hub.tgz

cd edx-internal

# stage
git checkout -b edx-deployment/stage/$TRAVIS_COMMIT
sed -i -e "s/newTag: .*/newTag: $TRAVIS_COMMIT-newrelic/" argocd/applications/license-manager/stage/kustomization.yaml
git commit -a -m "license-manager stage deploy: $TRAVIS_COMMIT_MESSAGE" --author "Travis CI Deployment automation <admin@edx.org>"
git push --set-upstream origin edx-deployment/stage/$TRAVIS_COMMIT
../hub-linux*/bin/hub pull-request -m "license-manager stage deploy: $TRAVIS_COMMIT_MESSAGE"

# prod
git checkout master
git checkout -b edx-deployment/prod/$TRAVIS_COMMIT
sed -i -e "s/newTag: .*/newTag: $TRAVIS_COMMIT-newrelic/" argocd/applications/license-manager/prod/kustomization.yaml
git commit -a -m "license-manager prod deploy: $TRAVIS_COMMIT_MESSAGE" --author "Travis CI Deployment automation <admin@edx.org>"
git push --set-upstream origin edx-deployment/prod/$TRAVIS_COMMIT
../hub-linux*/bin/hub pull-request -m "license-manager prod deploy: $TRAVIS_COMMIT_MESSAGE"

