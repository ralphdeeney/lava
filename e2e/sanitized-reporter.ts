import type { FullConfig, FullResult, Reporter, TestCase, TestResult } from '@playwright/test/reporter';
import { execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

type Entry = {
  name: string;
  status: 'passed' | 'failed' | 'skipped';
  project: string;
  viewport: { width: number; height: number } | null;
};

function xml(value: string): string {
  return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&apos;');
}

/** Intentionally discards raw errors, assertion values, source excerpts and worker logs. */
export default class SanitizedReporter implements Reporter {
  private sourceCommit = '';
  private clean = false;
  private begun = false;
  private entries: Entry[] = [];
  private failures: { name: string; project: string; diagnostic: string }[] = [];

  private redact(value: string): string {
    const file = process.env.LAVA_E2E_ACCOUNTS_FILE;
    if (!file) return 'Private diagnostic withheld: account-redaction fixture unavailable';
    try {
      const users = JSON.parse(readFileSync(file, 'utf8')).users as { password: string }[];
      for (const { password } of users) {
        for (const secret of [password, encodeURIComponent(password), JSON.stringify(password).slice(1, -1)]) {
          if (secret) value = value.split(secret).join('[REDACTED]');
        }
      }
    } catch { return 'Private diagnostic withheld: account-redaction fixture unavailable'; }
    return value
      .replace(/lavabs_[A-Za-z0-9_-]+/g, '[SESSION REDACTED]')
      .replace(/lava_(?:token_)?[A-Za-z0-9_-]{20,}/g, '[CREDENTIAL REDACTED]')
      .replace(/\b[0-9a-fA-F]{64}\b/g, '[CSRF REDACTED]')
      .replace(/postgres(?:ql)?(?:\+psycopg)?:\/\/[^\s]+/gi, '[DATABASE URL REDACTED]')
      .replace(/(authorization|password|cookie)\s*[:=]\s*[^\n]+/gi, '$1=[REDACTED]')
      .slice(0, 16_384);
  }

  onBegin(_config: FullConfig): void {
    this.sourceCommit = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
    this.clean = execFileSync('git', ['status', '--porcelain'], { encoding: 'utf8' }).trim() === '';
    this.begun = true;
  }

  onTestEnd(test: TestCase, result: TestResult): void {
    const project = test.parent.project();
    if (result.status !== 'passed' && result.status !== 'skipped') {
      this.failures.push({
        name: test.title,
        project: project?.name ?? 'unknown',
        diagnostic: this.redact(result.errors.map(error => error.message ?? 'Unknown assertion failure').join('\n')),
      });
    }
    this.entries.push({
      name: test.title,
      status: result.status === 'passed' ? 'passed' : result.status === 'skipped' ? 'skipped' : 'failed',
      project: project?.name ?? 'unknown',
      viewport: project?.use.viewport ?? null,
    });
  }

  onEnd(result: FullResult): void {
    const directory = process.env.LAVA_E2E_REPORT_DIR ?? 'test-results/e2e/public';
    mkdirSync(directory, { recursive: true, mode: 0o700 });
    const privateDirectory = 'test-results/e2e/private';
    mkdirSync(privateDirectory, { recursive: true, mode: 0o700 });
    writeFileSync(join(privateDirectory, 'failures.json'), JSON.stringify(this.failures, null, 2) + '\n', { mode: 0o600 });
    const totals = {
      total: this.entries.length,
      passed: this.entries.filter(entry => entry.status === 'passed').length,
      failed: this.entries.filter(entry => entry.status === 'failed').length,
      skipped: this.entries.filter(entry => entry.status === 'skipped').length,
    };
    const report = {
      schema_version: 1,
      source_commit: this.sourceCommit,
      source_tree_clean: this.clean,
      test_environment: 'real-browser-postgresql',
      executed: this.begun && this.entries.length > 0,
      simulated: false,
      tests: this.entries,
      totals,
      runner_status: result.status,
    };
    writeFileSync(join(directory, 'report.json'), JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
    const tests = this.entries.map(entry => {
      const outcome = entry.status === 'failed'
        ? '<failure message="Functional browser assertion failed; raw diagnostics withheld for credential safety" />'
        : entry.status === 'skipped' ? '<skipped />' : '';
      return `<testcase classname="${xml(entry.project)}" name="${xml(entry.name)}">${outcome}</testcase>`;
    }).join('');
    const junit = `<?xml version="1.0" encoding="UTF-8"?><testsuite name="LAVA real browser journeys" tests="${totals.total}" failures="${totals.failed}" errors="${result.status === 'passed' || totals.failed > 0 ? 0 : 1}" skipped="${totals.skipped}"><properties><property name="source_commit" value="${xml(this.sourceCommit)}" /></properties>${tests}</testsuite>\n`;
    writeFileSync(join(directory, 'junit.xml'), junit, { mode: 0o600 });
    // No passwords, cookies, error messages or captured browser/network content reach stdout.
    console.log(JSON.stringify({ source_commit: this.sourceCommit, ...totals, status: result.status }));
  }
}
