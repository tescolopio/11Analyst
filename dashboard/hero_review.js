(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;else root.ElevenHeroReview=api;
})(globalThis,function(){
  "use strict";
  const version=1;
  const outcomes=["unknown","missed_contact","failed_landing","legal_return"];
  const gates=["coordinate_transform","event_timing","bounce_reconstruction","spin_axes_units"];
  const unknown=()=>({placement:"unknown",length:"unknown",spin:"unknown",milestone_category:null,machine_key_eligible:false});
  function vector(value,name){
    if(!Array.isArray(value)||value.length!==3||!value.every(Number.isFinite))throw new Error(`Invalid ${name} vector`);
    return value;
  }
  function classifySynthetic(input){
    if(input.source_kind!=="synthetic")throw new Error("This geometry prototype accepts synthetic fixtures only; real reconstruction is not implemented");
    const result={...unknown(),evidence_status:"synthetic_only"};
    if(!gates.every(gate=>input.validation?.[gate]===true)||!input.reference?.trim())return result;
    if(!["positive_z","negative_z"].includes(input.receiver_end)||!["right","left"].includes(input.handedness))return result;
    const tolerance=input.position_tolerance,spinTolerance=input.spin_tolerance;
    if(!Number.isFinite(tolerance)||tolerance<0||tolerance>=0.7625||!Number.isFinite(spinTolerance)||spinTolerance<0)
      throw new Error("Explicit finite nonnegative geometry/spin tolerances are required");
    const center=vector(input.table_center,"table center"),sign=input.receiver_end==="positive_z"?1:-1;
    // A 180-degree rotation around +Y at the opposite end transforms positions AND axial spin vectors.
    const rotate=v=>[sign*v[0],v[1],sign*v[2]];
    const position=v=>rotate(vector(v,"bounce").map((n,i)=>n-center[i]));
    const first=position(input.first_receiver_bounce),next=position(input.hypothetical_next_bounce);
    const spin=rotate(vector(input.angular_velocity,"angular velocity"));
    const insideWidth=Math.abs(first[0])<0.7625-tolerance;
    const receiverHalf=first[2]>tolerance&&first[2]<1.37-tolerance;
    if(Math.abs(first[1]-0.76)>tolerance||Math.abs(next[1]-0.76)>tolerance||!insideWidth||!receiverHalf)return result;
    const side=Math.abs(first[0])<=tolerance?"centre":first[0]<0?"left":"right";
    result.placement=side==="centre"?"centre":side===(input.handedness==="right"?"left":"right")?"backhand_side":"forehand_side";
    if(Math.abs(next[0])<0.7625-tolerance&&next[2]>tolerance){
      result.length=next[2]>=1.37-tolerance&&next[2]<=1.37+tolerance?"boundary":next[2]>1.37?"long":"short";
    }
    const lateral=Math.abs(spin[1])<=spinTolerance?"none":spin[1]<0?"clockwise":"counterclockwise";
    const vertical=Math.abs(spin[0])<=spinTolerance?"none":spin[0]>0?"topspin":"backspin";
    result.spin={side:lateral,vertical,axial:Math.abs(spin[2])<=spinTolerance?"none":"present"};
    if(result.length!=="unknown"&&result.length!=="boundary"&&result.placement!=="centre")
      result.milestone_category=result.length==="long"&&result.placement==="backhand_side"&&lateral!=="none";
    return result;
  }
  function syntheticExamples(){
    return ["right","left"].flatMap(handedness=>["positive_z","negative_z"].map(receiver_end=>{
      const sign=receiver_end==="positive_z"?1:-1,x=handedness==="right"?-0.3:0.3;
      const input={source_kind:"synthetic",reference:"Fabricated geometry, not a recorded shot",handedness,receiver_end,
        validation:Object.fromEntries(gates.map(gate=>[gate,true])),position_tolerance:0.01,spin_tolerance:0.1,
        table_center:[0,0,0],first_receiver_bounce:[sign*x,0.76,sign*0.9],
        hypothetical_next_bounce:[sign*x,0.76,sign*1.7],angular_velocity:[-sign*5,-10,sign*2]};
      return {input,result:classifySynthetic(input)};
    }));
  }
  function queue(revision,playerId){
    if(!["imported","imported_with_diagnostics"].includes(revision.status))return [];
    const points=new Map();
    for(const row of [...revision.records].sort((a,b)=>a.row_index-b.row_index)){
      if(!points.has(row.point_id))points.set(row.point_id,[]);
      points.get(row.point_id).push(row);
    }
    const candidates=[];
    for(const rows of points.values()){
      const hits=rows.filter(row=>row.contact_type==="Hit");
      const serves=hits.filter(row=>row.provider_annotations.isServe===true||row.provider_labels.shotType==="Serve");
      for(const serve of serves.filter(row=>row.player_id!==playerId)){
        const following=hits[hits.indexOf(serve)+1]??null;
        const warnings=[];
        if(serve.provider_annotations.isServe!==true||serve.provider_labels.shotType!=="Serve")warnings.push("Provider serve labels disagree or are missing.");
        if(serves.length!==1||hits[0]!==serve)warnings.push("Multiple serves or preceding Hits in this point group; sequence unresolved.");
        if(following&&following.player_id!==playerId)warnings.push("Following recorded Hit is not by the receiver.");
        if(rows.some((row,i)=>i>0&&Date.parse(row.begin_at)<Date.parse(rows[i-1].begin_at)))warnings.push("Timestamps run backwards in file order.");
        if(revision.rejected_rows.length)warnings.push("This revision has quarantined rows; the accepted sequence may have gaps.");
        if(serve.provider_annotations.isServeAce===true&&following?.player_id===playerId)warnings.push("Provider ace flag coexists with a recorded return contact; do not interpret it as a missed contact.");
        candidates.push({serve,following,warnings,geometry:unknown(),receiving_attempt:null,return_outcome:null});
      }
    }
    return candidates.sort((a,b)=>a.serve.row_index-b.serve.row_index);
  }
  function identity(revision,playerId){
    return {player_id:playerId,revision_id:revision.revision_id,source_sha256:revision.sha256,provider_match_id:revision.provider_match_id};
  }
  function validateReport(report,revision,playerId){
    const scope=identity(revision,playerId),candidate=queue(revision,playerId).find(item=>item.serve.id===report?.shot_id);
    if(!report||report.version!==version||report.evidence_status!=="user_review"||!candidate
      ||Object.entries(scope).some(([key,value])=>report[key]!==value)
      ||report.point_id!==candidate.serve.point_id||report.row_index!==candidate.serve.row_index
      ||!outcomes.includes(report.return_observation)||!["pending","replay","in_game","other"].includes(report.reference_kind)
      ||!["notes","reference"].every(key=>typeof report[key]==="string"&&report[key].length<=4000)
      ||typeof report.recorded_at!=="string"||!Number.isFinite(Date.parse(report.recorded_at))
      ||(report.return_observation!=="unknown"&&(report.reference_kind==="pending"||!report.reference.trim()))
      ||(report.reference_kind!=="pending"&&!report.reference.trim())
      ||report.geometry!==null||report.machine_key_eligible!==false)throw new Error("Invalid or mismatched Hero review; stored data has not been overwritten");
    return report;
  }
  function readReports(storage,key,revision,playerId){
    const raw=storage.getItem(key),reports=raw===null?[]:JSON.parse(raw);
    if(!Array.isArray(reports))throw new Error("Invalid stored Hero review history");
    reports.forEach(report=>validateReport(report,revision,playerId));
    return reports;
  }
  function initialize({player,h,downloadJson,onError}){
    const $=id=>document.getElementById(id);
    let revision,candidates=[],selected=null,readable=false;
    const storageKey=()=>`11analyst:hero-review:v1:${player.id}:${revision.revision_id}`;
    const read=()=>readReports(localStorage,storageKey(),revision,player.id);
    const safe=action=>event=>{try{action(event);}catch(error){onError(error);}};
    const brief=row=>row?{
      export_row:row.row_index+1,shot_id:row.id,point_id:row.point_id,player_id:row.player_id,
      begin_at:row.begin_at,provider_labels:row.provider_labels,provider_annotations:row.provider_annotations,
      provider_fields:row.provider_fields,
    }:null;
    function select(){
      selected=candidates.find(item=>item.serve.id===$("hero-review-shot").value)??null;
      $("hero-review-form").hidden=!selected;
      $("hero-review-detail").textContent=selected?JSON.stringify({
        incoming_serve:brief(selected.serve),following_hit_in_file_order:brief(selected.following),
        warnings:selected.warnings,analyst_geometry:selected.geometry,
        receiving_attempt:selected.receiving_attempt,return_outcome:selected.return_outcome,
      },null,2):"No opponent serve candidates in this revision.";
      $("hero-review-form").reset();
      $("hero-review-feedback").textContent="";
      $("hero-review-history").replaceChildren();
      if(!selected)return;
      try{
        const reports=read().filter(report=>report.shot_id===selected.serve.id);
        for(const report of reports.slice().reverse()){
          const li=document.createElement("li");
          li.textContent=`${report.recorded_at} | ${report.return_observation} (user observation only) | ${report.reference_kind}: ${report.reference||"No reference yet"} | ${report.notes}`;
          $("hero-review-history").append(li);
        }
        readable=true;
      }catch(error){readable=false;onError(error);}
      $("hero-review-save").disabled=!readable;
      $("hero-review-export").disabled=!readable;
    }
    function showRevision(value){
      revision=value;candidates=queue(revision,player.id);
      $("hero-review-shot").replaceChildren();
      for(const item of candidates){
        const option=document.createElement("option");option.value=item.serve.id;
        option.textContent=`Export row ${item.serve.row_index+1} | player ${item.serve.player_id} | ${item.serve.id}`;
        $("hero-review-shot").append(option);
      }
      const following=candidates.filter(item=>item.following?.player_id===player.id);
      const unsuccessful=candidates.filter(item=>item.serve.provider_annotations.isServeSuccess===false);
      const flagged=following.filter(item=>item.following.provider_annotations.isSuccess===false);
      $("hero-review-summary").textContent=`${candidates.length} opponent serve Hit candidates; ${unsuccessful.length} provider-marked unsuccessful serves; ${following.length} with a following target-player Hit in file order, of which ${flagged.length} are provider-marked unsuccessful. These are export annotations, NOT validated receiving attempts or errors. Long/backhand category attempts, errors, match counts and error rate: unknown.`;
      $("hero-review-player").textContent=`Player ${player.id}: ${player.handedness}-handed (${player.handedness_source}). Backhand side means ${player.handedness==="right"?"receiver's left":player.handedness==="left"?"receiver's right":"unknown until handedness is confirmed"}; it does not identify the stroke used.`;
      $("hero-review-shot").disabled=!candidates.length;
      $("hero-review-export").disabled=!candidates.length;
      select();
    }
    $("hero-review-shot").addEventListener("change",safe(select));
    $("hero-review-form").addEventListener("submit",safe(event=>{
      event.preventDefault();
      $("hero-review-feedback").textContent="";
      if(!readable||!selected)throw new Error("Review storage is unavailable; nothing was saved");
      const report=validateReport({version,...identity(revision,player.id),shot_id:selected.serve.id,
        point_id:selected.serve.point_id,row_index:selected.serve.row_index,recorded_at:new Date().toISOString(),
        evidence_status:"user_review",return_observation:$("hero-review-outcome").value,
        reference_kind:$("hero-review-reference-kind").value,reference:$("hero-review-reference").value.trim(),
        notes:$("hero-review-notes").value.trim(),geometry:null,machine_key_eligible:false,
      },revision,player.id);
      if(report.return_observation==="unknown"&&!report.notes&&!report.reference)throw new Error("Add a review note or evidence reference before saving");
      const next=[...read(),report];localStorage.setItem(storageKey(),JSON.stringify(next));
      select();
      $("hero-review-feedback").textContent="Saved in this browser only. Export a backup. Placement remains unknown; no diagnosis or key was unlocked.";
    }));
    $("hero-review-export").addEventListener("click",safe(()=>downloadJson(`hero-reviews-${player.id}-${revision.revision_id.slice(0,12)}.json`,{
      format:"11analyst.hero-reviews",version,...identity(revision,player.id),reports:read(),
      candidates:candidates.map(item=>({shot_id:item.serve.id,point_id:item.serve.point_id,row_index:item.serve.row_index,
        following_shot_id:item.following?.id??null,warnings:item.warnings,geometry:item.geometry,receiving_attempt:null,return_outcome:null})),
      category_attempts:null,category_errors:null,category_matches:null,machine_key_eligible:false,
    })));
    window.addEventListener("storage",safe(event=>{if(revision&&(event.key===storageKey()||event.key===null))select();}));
    $("hero-review-synthetic").innerHTML=syntheticExamples().map(({input,result})=>
      `<li>${h(input.handedness)}-handed, receiver at ${h(input.receiver_end)}: ${h(result.placement)}, ${h(result.length)}, ${h(result.spin.vertical)} + ${h(result.spin.side)} sidespin. Synthetic only.</li>`).join("");
    return {showRevision};
  }
  return {classifySynthetic,syntheticExamples,queue,validateReport,readReports,initialize};
});
