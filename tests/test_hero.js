const test=require("node:test"),assert=require("node:assert/strict");
const hero=require("../dashboard/hero.js");
const revision={records:[
  {id:"a",point_id:"p1",player_id:"1",contact_type:"Hit",provider_labels:{shotType:"Serve",spinDirection:"BottomLeft"}},
  {id:"b",point_id:"p1",player_id:"2",contact_type:"Toss",provider_labels:{shotType:"Toss",spinDirection:"None"}},
  {id:"c",point_id:"p2",player_id:"2",contact_type:"FutureContact",provider_labels:{shotType:null,spinDirection:null}},
]};
test("Hero filtering retains opponents and does not count a serve toss as a hit",()=>{
  const original=structuredClone(revision);
  assert.equal(hero.filterRows(revision,"all","all","","1").length,3);
  assert.deepEqual(hero.filterRows(revision,"Hit","all","","1").map(row=>row.id),["a"]);
  assert.deepEqual(hero.filterRows(revision,"Toss","opponent","","1").map(row=>row.id),["b"]);
  assert.deepEqual(hero.filterRows(revision,"other","all","","1").map(row=>row.id),["c"]);
  assert.equal(hero.filterRows(revision,"all","target","bottomleft","1").length,1);
  assert.equal(hero.filterRows(revision,"all","all","p1","1").length,2);
  assert.deepEqual(revision,original);
});
test("Provider booleans display unknown separately from false without inferring an outcome",()=>{
  assert.equal(hero.flag(false),"False (provider)");
  assert.equal(hero.flag(true),"True (provider)");
  for(const value of [null,undefined,"false",0])assert.equal(hero.flag(value),"Unknown");
});
