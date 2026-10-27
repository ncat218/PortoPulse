// Pure geometry selection checks; browser/protocol integration has a separate harness.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {makeIndex}=require('../app/map_frontend/map.js');

test('viewport index retains long crossing edges and exact opposite directions',()=>{
  const roads=[[[[-8.7,41.1],[-8.5,41.3]]],[[[-8.5,41.3],[-8.7,41.1]]],[[[-9,40],[-9.01,40]]]];
  const index=makeIndex(roads);
  assert.deepEqual([...index.query([-8.631,41.159,-8.629,41.161])].sort(),[0,1]);
  assert.equal(index.query([-8.3,41,-8.2,41.1]).size,0);
  assert.equal(index.query([-180,-85,180,85]).size,3);
});

test('viewport query agrees with brute-force bounding boxes on synthetic roads',()=>{
  const {boundsOf,intersects}=require('../app/map_frontend/map.js');
  const roads=Array.from({length:1000},(_,i)=>[[[-8.7+(i%30)*.003,41.1+Math.floor(i/30)*.003],[-8.695+(i%30)*.003,41.105+Math.floor(i/30)*.003]]]);
  const index=makeIndex(roads);
  for(let i=0;i<20;i++) {
    const q=[-8.7+i*.002,41.12,-8.68+i*.002,41.15];
    const expected=roads.map((r,i)=>intersects(boundsOf(r[0]),q)?i:null).filter(i=>i!==null);
    assert.deepEqual([...index.query(q)].sort((a,b)=>a-b),expected);
  }
});
