// Regression checks for the heatmap's actual display helpers; no browser dependency.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('index.html', 'utf8');
const helpers = html.slice(html.indexOf('function currentCandidateResult('), html.indexOf('function renderCandidates('));
const context = {
  candidateResult: {heatmap: [[999, 1000, 0]], frequency: [[.999, 1, 0]], survivor_count: 1000, exhaustive: true},
  candidateSignature: 'before', candidateFingerprint: () => 'before',
  candidatePreview: null, candidatePreviewRejected: false, activeTarget: () => 'candidateheat',
};
vm.createContext(context);
vm.runInContext(helpers, context);
assert.equal(context.candidateCellValue(0, 0), '<100%', 'Near-unanimous membership must not round to unanimity');
assert.equal(context.candidateCellValue(0, 1), '100%');
assert.equal(context.candidateCellValue(0, 2), null);
context.candidateResult.exhaustive = false;
assert.equal(context.candidateCellValue(0, 1), '~100%', 'Bounded results must not appear exhaustive');
context.candidateFingerprint = () => 'after';
assert.equal(context.currentCandidateResult(), null);
assert.equal(context.candidateCellValue(0, 1), null, 'Changed constraints must hide old percentages');
assert.equal(context.candidateColor(0, 1), '#fff', 'Changed constraints must hide old colors');
context.candidateFingerprint = () => 'before';
context.candidatePreview = [[0, 2]];
assert.equal(context.candidateCellValue(0, 1), null, 'Individual previews must not retain aggregate percentages');
assert.equal(context.candidateColor(0, 2), '#c6dbf5', 'A preview must override the aggregate heatmap');
assert.equal(context.candidateColor(0, 1), '#f3f4f5');
console.log('Candidate UI regression checks passed.');

context.candidatePreviewRejected = true;
assert.equal(context.candidateColor(0, 2), '#f2b5b5', 'Rejected previews must be visually distinct from survivors');

const emptyPartial = {survivor_count: 0, truncated: true, exhaustive: false};
assert.match(context.candidateSearchStatus(emptyPartial), /No candidates found before the search limit/);
assert.match(context.candidateSearchStatus(emptyPartial), /No heatmap to display/);
assert.doesNotMatch(context.candidateSearchStatus(emptyPartial), /All survivors|No candidates satisfy/);
assert.match(context.candidateSearchStatus({...emptyPartial, truncated: false}), /area limit/);
assert.match(context.candidateSearchStatus({...emptyPartial, truncated: false, exhaustive: true}), /No candidates satisfy/);
assert.match(context.candidateSearchStatus({...emptyPartial, rejection_examples: {'Border check': {reason: 'Route costs 45, below 77.'}}}), /Route costs 45/);
assert.match(context.candidateSearchStatus({survivor_count: 2, truncated: false}), /2 candidates found/);
