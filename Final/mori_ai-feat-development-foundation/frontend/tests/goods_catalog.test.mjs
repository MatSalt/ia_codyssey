import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
const {exampleImage}=await import(process.argv[2]||'../src/features/goods/design/catalog.ts');
test('examples map to local verified files for both products',async()=>{
 const root=new URL('../public',import.meta.url);const manifest=JSON.parse(await readFile(new URL('goods/manifest.json',new URL(root.href+'/'))));
 for(const product of ['keyring','magnet'])for(const id of ['photo','illustration','cutout','badge','book','free'])for(const card of [false,true]){
  const path=exampleImage(product,id,card);const asset=manifest.assets.find(a=>'/goods/'+a.file===path);assert.ok(asset);
  const bytes=await readFile(new URL('.'+path, new URL(root.href+'/')));assert.equal(createHash('sha256').update(bytes).digest('hex'),asset.sha256);
 }
});
test('unknown IDs cannot produce arbitrary URLs',()=>{
 assert.throws(()=>exampleImage('keyring','../private'));assert.throws(()=>exampleImage('other','book'));
});
