(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;else root.ElevenHero=api;
})(globalThis,function(){
  "use strict";
  const flag=value=>value===true?"True (provider)":value===false?"False (provider)":"Unknown";
  function filterRows(revision,contact,actor,query,playerId) {
    const search=query.trim().toLowerCase();
    return revision.records.filter(row=>{
      const contactMatches=contact==="all"||(contact==="other"?!["Hit","Toss"].includes(row.contact_type):row.contact_type===contact);
      const actorMatches=actor==="all"||(actor==="target"?row.player_id===playerId:row.player_id!==playerId);
      const labelText=Object.values(row.provider_labels).filter(value=>value!==null).join(" ");
      return contactMatches&&actorMatches&&`${row.id} ${row.point_id} ${row.player_id} ${labelText}`.toLowerCase().includes(search);
    });
  }
  function initialize({evidence,player,h,downloadJson,onError}) {
    const $=id=>document.getElementById(id), pageSize=15;
    if(evidence.format!=="11analyst.hero-evidence"||evidence.version!==1||!Array.isArray(evidence.revisions))throw new Error("Unsupported Hero evidence snapshot");
    const review=ElevenHeroReview.initialize({player,h,downloadJson,onError});
    let revision=evidence.revisions[0],page=0;
    const list=items=>`<ul>${items.map(text=>`<li>${h(text)}</li>`).join("")}</ul>`;
    const table=(headers,rows)=>`<table><thead><tr>${headers.map(text=>`<th scope="col">${h(text)}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(text=>`<td>${text}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    function renderRows(){
      const rows=filterRows(revision,$("hero-contact").value,$("hero-actor").value,$("hero-search").value,evidence.player_id);
      page=Math.min(page,Math.max(0,Math.ceil(rows.length/pageSize)-1));
      const shown=rows.slice(page*pageSize,(page+1)*pageSize);
      $("hero-rows").innerHTML=table(["Export row","Contact","Player ID","Point ID","Provider shot / spin","Provider serve / success",""],shown.map(row=>[
        h(row.row_index+1),h(row.contact_type),h(row.player_id),h(row.point_id),
        `${h(row.provider_labels.shotType??"Unknown")} / ${h(row.provider_labels.spinDirection??"Unknown")}`,
        `${h(flag(row.provider_annotations.isServe))} / ${h(flag(row.provider_annotations.isSuccess))}`,
        `<button class="button small secondary" data-hero-row="${row.row_index}">Inspect row</button>`,
      ]));
      $("hero-page").textContent=`${rows.length} matching accepted rows; showing ${rows.length?page*pageSize+1:0}-${Math.min((page+1)*pageSize,rows.length)}. Source-file order, not inferred rally order.`;
      $("hero-prev").disabled=page===0;$("hero-next").disabled=(page+1)*pageSize>=rows.length;
    }
    function renderRevision(){
      page=0;
      $("hero-row-detail").hidden=true;
      const counts=revision.counts;
      $("hero-counts").textContent=counts?`${revision.input_rows} input rows; ${counts.accepted_rows} accepted (${counts.hits} Hits, ${counts.tosses} Tosses, ${counts.other_contacts} other); ${counts.point_groups} provider point groups. ${counts.target_rows} target-player rows and ${counts.opponent_rows} other-player rows. ${counts.rejected_rows} rejected; ${revision.duplicate_rows} identical duplicate rows.`:"Export could not be parsed. Original bytes and diagnostics are retained in the archive.";
      $("hero-provenance").textContent=JSON.stringify({
        source_kind:revision.source_kind,importer_version:revision.importer_version,provider_match_id:revision.provider_match_id,
        revision_number:revision.revision_number,revision_id:revision.revision_id,status:revision.status,
        original_filename:revision.original_filename,sha256:revision.sha256,imported_at:revision.imported_at,
        retrieved_at:revision.retrieved_at,source_url:revision.source_url,discovery_name:revision.discovery_name,
        declared_participant_ids:revision.declared_participant_ids,observed_participant_ids:revision.observed_participant_ids??[],
        metadata_provenance:revision.metadata_provenance,declared_metadata:revision.declared_metadata,
        frame_status:revision.frame_status,units_status:revision.units_status,event_timing_status:revision.event_timing_status,
        completeness:revision.completeness,outcome_evidence:revision.outcome_evidence,crosswalk:revision.crosswalk,
      },null,2);
      $("hero-source").replaceChildren();
      const expected=`https://11hero.com/matches/${revision.provider_match_id}`;
      if(revision.source_url===expected){
        const link=document.createElement("a");link.href=expected;link.textContent="Open source match on 11 Hero (external)";
        link.target="_blank";link.rel="noopener noreferrer";$("hero-source").append(link);
      }
      const diagnostics=[...revision.diagnostics,...revision.rejected_rows.map(row=>({...row,level:"rejected"}))];
      $("hero-diagnostics").innerHTML=diagnostics.length?`<p>${diagnostics.length} diagnostics; showing the first 100. Export retains all.</p>${table(["Severity","Export row","Diagnostic"],diagnostics.slice(0,100).map(item=>[
        h(item.level),item.row_index===null?"File":h(item.row_index+1),h(item.message),
      ]))}`:"No import diagnostics. This does not establish complete telemetry or correct provider labels.";
      renderRows();
      review.showRevision(revision);
    }
    function guard(action){return event=>{try{action(event);}catch(error){onError(error);}};}
    $("hero-limits").innerHTML=list(evidence.limits);
    $("hero-summary").textContent=`${new Set(evidence.revisions.map(row=>row.provider_match_id)).size} provider match IDs; ${evidence.revisions.length} retained revisions. Revisions are alternatives, not additional matches. Independent of the local match-mode filter.`;
    $("hero-empty").hidden=!!revision;$("hero-workspace").hidden=!revision;$("hero-export").disabled=!revision;
    if(!revision)return;
    for(const item of evidence.revisions){
      const option=document.createElement("option");option.value=item.revision_id;
      option.textContent=`${item.provider_match_id} / revision ${item.revision_number} / ${item.status}`;
      $("hero-revision").append(option);
    }
    $("hero-revision").addEventListener("change",guard(()=>{
      revision=evidence.revisions.find(item=>item.revision_id===$("hero-revision").value);
      if(!revision)throw new Error("Hero revision unavailable");
      renderRevision();
    }));
    for(const id of ["hero-contact","hero-actor"])$(id).addEventListener("change",guard(()=>{page=0;renderRows();}));
    $("hero-search").addEventListener("input",guard(()=>{page=0;renderRows();}));
    $("hero-prev").addEventListener("click",guard(()=>{page--;renderRows();}));
    $("hero-next").addEventListener("click",guard(()=>{page++;renderRows();}));
    $("hero-rows").addEventListener("click",guard(event=>{
      const button=event.target.closest("[data-hero-row]");
      if(!button)return;
      const row=revision.records.find(item=>item.row_index===Number(button.dataset.heroRow));
      if(!row)throw new Error("Hero row unavailable");
      $("hero-row-json").textContent=JSON.stringify(row,null,2);
      $("hero-row-title").textContent=`Export row ${row.row_index+1}: ${row.contact_type} / player ${row.player_id}`;
      $("hero-row-detail").hidden=false;$("hero-row-title").focus();$("hero-row-detail").scrollIntoView({block:"nearest"});
    }));
    $("hero-export").addEventListener("click",guard(()=>downloadJson(`hero-evidence-${evidence.player_id}.json`,evidence)));
    renderRevision();
  }
  return {flag,filterRows,initialize};
});
