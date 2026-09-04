// ВРЕМЕННО, снять при слиянии jenkins-pipeline-lib#183
@Library('wbci@feature/docker-service-deploy') _

checksDockerService(
    pushBranchImages: false,   // ВРЕМЕННО, до выдачи кред реестра
    checkEnvironments: [
        [image:   'python:3.12-slim',
         prepare: 'apt-get update && apt-get install -y --no-install-recommends make poppler-utils curl && pip install --no-cache-dir -r backend/requirements.txt',
         targets: ['lint-backend', 'test-backend']],
        [image:   'node:20-alpine',
         prepare: 'apk add --no-cache make && cd frontend && npm ci',
         targets: ['lint-frontend', 'test-frontend']],
    ],
    imageRepo: 'ghcr.io/wirenboard/wb-template-generator-backend',
    images: [
        [imageRepo: 'ghcr.io/wirenboard/wb-template-generator-backend',  dockerfile: 'backend/Dockerfile',  context: '.'],
        [imageRepo: 'ghcr.io/wirenboard/wb-template-generator-frontend', dockerfile: 'frontend/Dockerfile', context: 'frontend'],
    ],
)
