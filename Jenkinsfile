
dockerService(
    checks: ['ci-lint', 'ci-test'],
    images: [
        backend:  [dockerfile: 'backend/Dockerfile'],
        frontend: [dockerfile: 'frontend/Dockerfile', context: 'frontend'],
    ],
)
