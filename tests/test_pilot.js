const test=require("node:test"),assert=require("node:assert/strict");
const pilot=require("../dashboard/pilot.js");
const report=()=>({version:1,player_id:"1909208",protocol:"repeatable-serve-20-v1",evidence_status:"self_reported",
  key:"54334.340",agreed:true,target:"Receiving half",feed_id:"ANLY01",candidate_sha256:null,pace:"comfortable",spin:"unknown",
  handedness:"right",recorded_at:"2026-10-24T00:00:00Z",legal_feeds:20,target_hits:18,legal_returns:12});
test("proposed protocol checks exact thresholds, not player return skill",()=>{
  const value=pilot.validate(report(),"1909208");
  assert.equal(pilot.meetsProtocol(value),true);
  assert.equal(pilot.meetsProtocol({...value,target_hits:17}),false);
  assert.equal(pilot.meetsProtocol({...value,legal_feeds:19}),false);
  assert.equal(pilot.meetsProtocol({...value,pace:"not_checked"}),false);
  assert.equal(pilot.meetsProtocol({...value,legal_returns:0}),true);
});
test("reports require consent, player scope, feed identity and consistent counts",()=>{
  for(const change of [{agreed:false},{player_id:"2"},{legal_feeds:21},{target_hits:19,legal_feeds:18},
    {legal_returns:21},{legal_returns:1.5},{feed_id:""},{candidate_sha256:"invalid"},{recorded_at:"bad"},
    {evidence_status:"verified"},{key:"garbage"},{target:""}])
    assert.throws(()=>pilot.validate({...report(),...change},"1909208"),/Invalid/);
});
