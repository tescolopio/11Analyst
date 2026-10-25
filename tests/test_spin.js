const test=require("node:test"),assert=require("node:assert/strict");
const spin=require("../dashboard/spin.js");
const vec=value=>[value.x,value.y,value.z];
const near=(a,b,tolerance=1e-10)=>a.forEach((value,i)=>assert.ok(Math.abs(value-b[i])<tolerance,`${a} != ${b}`));
const state=()=>({q:[1,0,0,0],time:0,distance:0,timeScale:1,mode:"travel",camera:"receiver"});

test("top/back and overhead side signs obey omega cross radius",()=>{
  near(spin.cross(vec(spin.record("top",1,0,2).angularVelocityRadPerSec),[0,1,0]),[0,0,2*Math.PI]);
  near(spin.cross(vec(spin.record("back",1,0,2).angularVelocityRadPerSec),[0,1,0]),[0,0,-2*Math.PI]);
  const basis=spin.camera("overhead");
  assert.ok(spin.project(spin.cross(vec(spin.record("clockwise",1,0,2).angularVelocityRadPerSec),[1,0,0]),basis)[1]>0);
  assert.ok(spin.project(spin.cross(vec(spin.record("counterclockwise",1,0,2).angularVelocityRadPerSec),[1,0,0]),basis)[1]<0);
});
test("all mixed balances preserve magnitude and physical-unit conversion",()=>{
  for(const name of ["topClockwise","topCounterclockwise","backClockwise","backCounterclockwise"])
    for(const balance of [0,.1,.5,.8,1])assert.ok(Math.abs(Math.hypot(...vec(spin.record(name,3,balance,2).angularVelocityRadPerSec))-6*Math.PI)<1e-12);
});
test("one revolution per second and frame-rate-independent integration",()=>{
  const omega=[2*Math.PI,0,0];
  near(spin.rotate(spin.integrate([1,0,0,0],omega,.25),[0,1,0]),[0,0,1]);
  near(spin.rotate(spin.integrate([1,0,0,0],omega,1),[0,1,0]),[0,1,0]);
  for(const frames of [30,60,144]){
    let q=[1,0,0,0];
    for(let i=0;i<frames;i++)q=spin.integrate(q,[2,3,-1],1/frames);
    near(q,spin.integrate([1,0,0,0],[2,3,-1],1));
    assert.ok(Math.abs(Math.hypot(...q)-1)<1e-12);
  }
});
test("cameras and handedness do not modify a physical record",()=>{
  const record=spin.record("topClockwise",2,.5,3),original=structuredClone(record);
  for(const name of ["receiver","side","overhead"]){
    const basis=spin.camera(name);
    spin.project(vec(record.angularVelocityRadPerSec),basis);
    near(spin.cross(basis.right,basis.up),basis.forward);
  }
  assert.deepEqual(record,original);
  assert.equal("handedness" in record,false);
});
test("playback scaling and travel speed are independent of physical spin",()=>{
  const record=spin.record("top",1,.5,2),original=structuredClone(record);
  const slow=spin.advance({...state(),timeScale:.25},record,1);
  const fast=spin.advance(state(),record,.25);
  near(slow.q,fast.q);assert.equal(slow.distance,.5);assert.deepEqual(record,original);
  const changed=spin.record("top",1,.5,4);
  const next=spin.advance(slow,changed,1);
  assert.equal(next.distance,1.5);
  near(next.q,spin.advance(slow,record,1).q);
  const inspected=spin.advance({...state(),mode:"inspect"},record,1);
  assert.equal(inspected.distance,0);
});
test("zero is static, missing is unknown and raw/unvalidated units are rejected",()=>{
  const zero=spin.record("zero",9,.5,2);
  assert.equal(spin.validate(zero).zero,true);
  near(spin.advance(state(),zero,10).q,[1,0,0,0]);
  const unknown={...zero,angularVelocityRadPerSec:null};
  assert.equal(spin.validate(unknown).unknown,true);
  assert.throws(()=>spin.advance(state(),unknown,1),/unknown/);
  assert.throws(()=>spin.validate({...zero,sourceKind:"logged"}),/Unsupported/);
  assert.throws(()=>spin.validate({...zero,angularVelocityRadPerSec:{x:NaN,y:0,z:0}}),/finite/);
  assert.throws(()=>spin.integrate([1,0,0,0],[0,0,0],-1),/Invalid/);
});
