import test from 'node:test';import assert from 'node:assert/strict';import {build} from 'esbuild';
await build({entryPoints:['src/features/generation/steps.ts'],bundle:true,platform:'node',format:'esm',outfile:'steps-check.mjs'});
const {generationSteps}=await import('../steps-check.mjs');
const view=tasks=>({pages:[{tasks:tasks.map(([stage,status])=>({stage,status}))}]});
test('unknown and failed are attention, never decorative completion',()=>{for(const status of ['unknown','failed','cancelled'])assert.equal(generationSteps(view([['caption',status],['image_transform','succeeded'],['optimize','queued']]))[1].status,'attention');});
test('finalization does not start until server optimize work starts',()=>{const steps=generationSteps(view([['caption','succeeded'],['image_transform','succeeded'],['optimize','queued']]));assert.equal(steps[1].status,'complete');assert.equal(steps[2].status,'pending');});
