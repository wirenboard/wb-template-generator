// ВРЕМЕННО, снять при слиянии jenkins-pipeline-lib#191: библиотека подключается неявно
// с master, а нового шага там пока нет.
@Library('wbci@feature/CLOUD-622-docker-service-checks') _

dockerService(checks: ['ci-lint', 'ci-test'])
