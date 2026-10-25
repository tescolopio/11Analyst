const test=require("node:test"),assert=require("node:assert/strict");
const review=require("../dashboard/hero_review.js");
const fixture=()=>structuredClone(review.syntheticExamples()[0].input);
const world=(point,input)=>point.map((n,i)=>(i===1||input.receiver_end==="positive_z"?n:-n)+input.table_center[i]);

test("Both hands and receiver ends use a proper receiver-frame rotation, not camera orientation",()=>{
  for(const handedness of ["right","left"])for(const receiver_end of ["positive_z","negative_z"]){
    const input={...fixture(),handedness,receiver_end,table_center:[3,0.5,-2]};
    const sign=receiver_end==="positive_z"?1:-1;
    input.angular_velocity=[-sign*5,-10,sign*2];
    for(const x of [-0.3,0.3]){
      input.first_receiver_bounce=world([x,0.76,0.9],input);
      input.hypothetical_next_bounce=world([x,0.76,1.7],input);
      const result=review.classifySynthetic(input),backhand=(handedness==="right")=== (x<0);
      assert.equal(result.placement,backhand?"backhand_side":"forehand_side");
      assert.equal(result.milestone_category,backhand);
      assert.deepEqual(result.spin,{side:"clockwise",vertical:"backspin",axial:"present"});
      assert.equal(result.evidence_status,"synthetic_only");
      assert.equal(result.machine_key_eligible,false);
      assert.equal(Object.hasOwn(result,"stroke"),false);
    }
  }
});
test("Long uses the hypothetical next bounce, never depth of the first bounce",()=>{
  for(const handedness of ["right","left"])for(const receiver_end of ["positive_z","negative_z"]){
    const input={...fixture(),handedness,receiver_end},x=handedness==="right"?-0.3:0.3;
    input.first_receiver_bounce=world([x,0.76,1.3],input);
    input.hypothetical_next_bounce=world([x,0.76,1.32],input);
    assert.equal(review.classifySynthetic(input).length,"short");
    assert.equal(review.classifySynthetic(input).milestone_category,false);
    input.hypothetical_next_bounce=world([x,0.76,1.6],input);
    assert.equal(review.classifySynthetic(input).length,"long");
  }
});
test("Centre, end-line tolerance, table edges and invalid bounce locations stay uncertain",()=>{
  const input=fixture();
  for(const z of [1.36,1.37,1.38,1.365,1.375]){
    input.hypothetical_next_bounce[2]=z;
    assert.equal(review.classifySynthetic(input).length,"boundary");
    assert.equal(review.classifySynthetic(input).milestone_category,null);
  }
  for(const [z,length] of [[1.359,"short"],[1.381,"long"]]){
    input.hypothetical_next_bounce[2]=z;
    assert.equal(review.classifySynthetic(input).length,length);
  }
  input.hypothetical_next_bounce[2]=1.7;
  for(const x of [0,0.005,-0.005,0.01,-0.01]){
    input.first_receiver_bounce[0]=x;
    assert.equal(review.classifySynthetic(input).placement,"centre");
    assert.equal(review.classifySynthetic(input).milestone_category,null);
  }
  for(const point of [[0.7625,0.76,1],[-0.7625,0.76,1],[0,0.76,-0.5],[0,0.9,1],[0,0.76,1.37]]){
    input.first_receiver_bounce=point;
    assert.equal(review.classifySynthetic(input).placement,"unknown");
  }
  input.first_receiver_bounce=[-0.3,0.76,0.9];
  input.hypothetical_next_bounce=[1,0.76,1.7];
  assert.equal(review.classifySynthetic(input).length,"unknown");
});
test("Pure and mixed spin use the receiver-frame axes with explicit spin tolerance",()=>{
  const input=fixture();
  for(const [spin,side,vertical,member] of [
    [[5,-10,0],"clockwise","topspin",true],
    [[-5,10,3],"counterclockwise","backspin",true],
    [[0,10,0],"counterclockwise","none",true],
    [[5,0,0],"none","topspin",false],
    [[0,0,5],"none","none",false],
    [[0,0,0],"none","none",false],
    [[0,0.1,0],"none","none",false],
  ]){
    input.angular_velocity=spin;
    const result=review.classifySynthetic(input);
    assert.equal(result.spin.side,side);assert.equal(result.spin.vertical,vertical);
    assert.equal(result.milestone_category,member);
  }
});
test("Every validation gate is required; real exports cannot enter the synthetic prototype",()=>{
  for(const key of Object.keys(fixture().validation))for(const value of [false,null,undefined,"true"]){
    const input=fixture();input.validation[key]=value;
    assert.equal(review.classifySynthetic(input).placement,"unknown");
    assert.equal(review.classifySynthetic(input).milestone_category,null);
  }
  for(const patch of [{reference:""},{handedness:"unknown"},{receiver_end:"camera_left"}]){
    assert.equal(review.classifySynthetic({...fixture(),...patch}).placement,"unknown");
  }
  assert.throws(()=>review.classifySynthetic({...fixture(),source_kind:"hero"}),/synthetic fixtures only/);
  for(const patch of [{position_tolerance:-1},{spin_tolerance:NaN},{position_tolerance:undefined},{angular_velocity:[0,Infinity,0]},{hypothetical_next_bounce:null}]){
    assert.throws(()=>review.classifySynthetic({...fixture(),...patch}));
  }
});

function row(id,index,actor,contact="Hit",serve=false){
  return {id,point_id:"point",row_index:index,player_id:actor,contact_type:contact,begin_at:`2026-01-01T00:00:0${index}Z`,
    provider_fields:{rallyCount:index},provider_labels:{shotType:serve?"Serve":"Drive",direction:"Mid",distance:"Mid"},
    provider_annotations:{isServe:serve,isSuccess:true,isServeSuccess:serve,isServeAce:false}};
}
function revision(){
  return {revision_id:"revision-a",sha256:"sha-a",provider_match_id:"match-a",status:"imported",rejected_rows:[],
    records:[row("toss",0,"2","Toss",true),row("serve",1,"2","Hit",true),row("return",2,"1")]};
}
function report(rev=revision()){
  return {version:1,player_id:"1",revision_id:rev.revision_id,source_sha256:rev.sha256,provider_match_id:rev.provider_match_id,
    shot_id:"serve",point_id:"point",row_index:1,evidence_status:"user_review",recorded_at:"2026-01-02T00:00:00Z",
    reference_kind:"pending",reference:"",return_observation:"unknown",notes:"Await replay",geometry:null,machine_key_eligible:false};
}
test("Review queue excludes Tosses and own serves; all real geometry/outcomes stay unknown",()=>{
  const rev=revision(),original=structuredClone(rev);
  const items=review.queue(rev,"1");
  assert.equal(items.length,1);assert.equal(items[0].serve.id,"serve");
  assert.equal(items[0].following.id,"return");
  assert.equal(items[0].geometry.placement,"unknown");assert.equal(items[0].geometry.length,"unknown");
  assert.equal(items[0].geometry.milestone_category,null);
  assert.equal(items[0].return_outcome,null);assert.equal(items[0].receiving_attempt,null);
  assert.deepEqual(rev,original);
  assert.equal(review.queue(rev,"2").length,0);
  rev.status="rejected";assert.equal(review.queue(rev,"1").length,0);
});
test("Missing contact, ace flags and unsuccessful serves do not imply a receiving error",()=>{
  const rev=revision();rev.records[1].provider_annotations.isServeAce=true;
  rev.records[2].provider_annotations.isSuccess=false;
  let item=review.queue(rev,"1")[0];
  assert.match(item.warnings.join(" "),/ace flag/);assert.equal(item.return_outcome,null);
  rev.records.pop();rev.records[1].provider_annotations.isServeSuccess=false;
  item=review.queue(rev,"1")[0];
  assert.equal(item.following,null);assert.equal(item.receiving_attempt,null);assert.equal(item.return_outcome,null);
});
test("Ambiguous and partial point sequences are exposed, not repaired",()=>{
  const rev=revision();
  rev.records.push(row("serve2",3,"2","Hit",true));
  rev.records[2].player_id="2";rev.records[2].begin_at="2025-01-01T00:00:00Z";
  rev.rejected_rows=[{row_index:4}];rev.records.reverse();
  const items=review.queue(rev,"1");
  assert.equal(items.length,2);
  assert.match(items[0].warnings.join(" "),/Multiple serves/);
  assert.match(items[0].warnings.join(" "),/not by the receiver/);
  assert.match(items[0].warnings.join(" "),/backwards/);
  assert.match(items[0].warnings.join(" "),/quarantined/);
  assert.equal(items[0].serve.id,"serve");
});
test("Review notes are strictly revision/shot scoped and known outcomes require an explicit reference",()=>{
  const rev=revision(),value=report();
  assert.deepEqual(review.validateReport(value,rev,"1"),value);
  for(const patch of [{player_id:"2"},{revision_id:"other"},{source_sha256:"other"},{provider_match_id:"other"},
    {shot_id:"toss"},{point_id:"other"},{row_index:0},{geometry:{placement:"backhand_side"}},
    {machine_key_eligible:true},{return_observation:"legal_return"},{reference_kind:"replay"},{recorded_at:"bad"}]){
    assert.throws(()=>review.validateReport({...value,...patch},rev,"1"),/Invalid or mismatched/);
  }
  const known={...value,reference_kind:"replay",reference:"Example synthetic video 00:02, exact shot",return_observation:"failed_landing"};
  assert.equal(review.validateReport(known,rev,"1").return_observation,"failed_landing");
});
test("Stored reports survive parsing; corrupt, foreign or unavailable storage fails explicitly",()=>{
  const rev=revision(),raw=JSON.stringify([report()]);
  assert.deepEqual(review.readReports({getItem:()=>raw},"key",rev,"1"),[report()]);
  assert.deepEqual(review.readReports({getItem:()=>null},"key",rev,"1"),[]);
  for(const value of ["broken","{}",JSON.stringify([null]),JSON.stringify([{...report(),revision_id:"other"}])]){
    assert.throws(()=>review.readReports({getItem:()=>value},"key",rev,"1"));
  }
  assert.throws(()=>review.readReports({getItem:()=>{throw new Error("Storage denied");}},"key",rev,"1"),/Storage denied/);
});
