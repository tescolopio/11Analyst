(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;else root.ElevenPilot=api;
})(globalThis,function(){
  "use strict";
  const protocol="repeatable-serve-20-v1";
  function validate(value,playerId){
    if(!value || value.version!==1 || value.player_id!==playerId || value.protocol!==protocol
      || value.evidence_status!=="self_reported" || !/^[1-9]\d*\.[1-9]\d*$/.test(value.key)
      || value.agreed!==true || typeof value.target!=="string" || !value.target.trim() || value.target.length>500
      || typeof value.feed_id!=="string" || !value.feed_id.trim() || value.feed_id.length>100
      || (value.candidate_sha256!==null&&!/^[a-f0-9]{64}$/.test(value.candidate_sha256))
      || !["comfortable","too_fast","too_slow","not_checked"].includes(value.pace)
      || !["unknown","top","back","clockwise","counterclockwise","mixed"].includes(value.spin)
      || !["right","left","varies","unknown"].includes(value.handedness)
      || typeof value.recorded_at!=="string" || !Number.isFinite(Date.parse(value.recorded_at))
      || ![value.legal_feeds,value.target_hits,value.legal_returns].every(n=>Number.isInteger(n)&&n>=0&&n<=20)
      || value.target_hits>value.legal_feeds || value.legal_returns>value.legal_feeds)throw new Error("Invalid self-reported pilot check");
    return value;
  }
  function meetsProtocol(value){return value.legal_feeds===20&&value.target_hits>=18&&value.pace==="comfortable";}
  function initialize(data,downloadJson,onError){
    const $=id=>document.getElementById(id), storageKey=`11analyst:serve-pilot:v1:${data.player.id}`;
    const receipt=(data.publishing.service?.publications||[]).filter(r=>r.status==="verified"&&["serve-returns","plan-serve-reception"].includes(r.collection_id)).at(-1);
    $("pilot-key").value=receipt?.key||"";
    $("pilot-hand").value=data.player.handedness;
    let reports=[],readable=false;
    function render(){
      $("pilot-saved").replaceChildren();
      for(const report of [...reports].reverse()){
        const row=document.createElement("li");
        row.textContent=`${report.recorded_at.slice(0,10)} | ${report.key}, feed ${report.feed_id} | ${report.legal_feeds}/20 legal feeds; ${report.target_hits}/20 target hits; ${report.legal_returns}/${report.legal_feeds} legal returns. Target: ${report.target}. Pace: ${report.pace}. Spin: ${report.spin}. Hand: ${report.handedness}. Revision: ${report.candidate_sha256?report.candidate_sha256.slice(0,12):"not linked to a cloud receipt"}. ${meetsProtocol(report)?"User reports that the repeatability protocol was met.":"Protocol not met or pace not checked."} Self-reported only; no spin/trajectory fidelity or opponent reproduction is established.`;
        $("pilot-saved").append(row);
      }
      $("pilot-save").disabled=!readable;$("pilot-export").disabled=!readable||!reports.length;
    }
    function read(){
      const raw=localStorage.getItem(storageKey);
      const values=raw===null?[]:JSON.parse(raw);
      if(!Array.isArray(values))throw new Error("Invalid stored pilot history");
      values.forEach(value=>validate(value,data.player.id));
      return values;
    }
    function restore(){
      try{reports=read();readable=true;}catch(error){readable=false;onError(error);}
      render();
    }
    $("pilot-form").addEventListener("submit",event=>{
      event.preventDefault();
      try{
        if(!readable)throw new Error("Pilot storage is unavailable; no result was saved");
        const key=$("pilot-key").value.trim();
        ElevenPublishing.parseKey(key,data.player.id,key.startsWith("54334.")?"11hero":"manual");
        const report=validate({version:1,player_id:data.player.id,protocol,evidence_status:"self_reported",
          feed_id:$("pilot-feed").value.trim(),
          candidate_sha256:(data.publishing.service?.publications||[]).find(r=>r.status==="verified"&&r.key===key)?.candidate_sha256||null,
          key,recorded_at:new Date().toISOString(),agreed:$("pilot-agreed").checked,target:$("pilot-target").value.trim(),
          legal_feeds:Number($("pilot-legal").value),target_hits:Number($("pilot-target-hits").value),
          legal_returns:Number($("pilot-returns").value),pace:$("pilot-pace").value,spin:$("pilot-spin").value,
          handedness:$("pilot-hand").value},data.player.id);
        const next=[...read(),report];
        localStorage.setItem(storageKey,JSON.stringify(next));reports=next;render();
        $("pilot-feedback").textContent="Your observations were saved in this browser. Export a backup; this does not validate the classifier or unlock player-specific keys.";
      }catch(error){onError(error);}
    });
    $("pilot-export").addEventListener("click",()=>{
      try{downloadJson(`11-analyst-${data.player.id}-serve-pilot.json`,{format:"11analyst.serve-pilot",version:1,player_id:data.player.id,reports:read()});}
      catch(error){onError(error);}
    });
    window.addEventListener("storage",event=>{if(event.key===storageKey||event.key===null)restore();});
    restore();
  }
  return {validate,meetsProtocol,initialize};
});
