const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('index.html','utf8');
// Parse the entire production script in addition to exercising display helpers.
new vm.Script(html.match(/<script>([\s\S]*?)<\/script>/)[1]
  .replaceAll('__SIZE__','5').replaceAll('__AREA__','25'));
const source = html.slice(html.indexOf('function stateCountValue('),html.indexOf('function currentCandidateResult('));
const context = {};
vm.createContext(context);
vm.runInContext(source,context);
const report = {heatmap:[[0,1,99]],complete_cells:[[false,true,false]]};
assert.equal(context.stateCountValue(0,0,report),'~0');
assert.equal(context.stateCountValue(0,1,report),'1');
assert.equal(context.stateCountValue(0,2,report),'~99');
assert.equal(context.stateCountValue(0,0,null),null);
assert.equal(context.stateCountColor(0,0,null),'#edf0f2');
assert.notEqual(context.stateCountColor(0,0,report),context.stateCountColor(0,2,report));
console.log('State count UI checks passed.');
