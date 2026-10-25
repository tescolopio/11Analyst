(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;else root.ElevenCatalogue=api;
})(globalThis,function(){
  "use strict";
  function describe(catalogue,facets) {
    const keys=Object.keys(catalogue.facets), selected={};
    if(!facets||Object.keys(facets).length!==keys.length||Object.keys(facets).some(key=>!keys.includes(key)))throw new Error("Shot category requires exactly the supported facets");
    for(const key of keys){
      selected[key]=catalogue.facets[key].values.find(item=>item.id===facets[key]);
      if(!selected[key])throw new Error(`Unknown ${key} category`);
    }
    if(!catalogue.context_lengths[facets.context].includes(facets.length))throw new Error("Length/depth category does not apply to this context");
    if(selected.spin.side===(facets.direction==="not_applicable"))throw new Error("Sidespin direction does not apply to this spin family");
    const name=catalogue.name_template.replace(/\{(\w+)\}/g,(_,key)=>selected[key].name).replace(/\s+/g," ").trim();
    return {
      id:keys.map(key=>facets[key]).join("--"),name:name[0].toUpperCase()+name.slice(1),
      facets:{...facets},taxonomy_version:catalogue.taxonomy_version,
      source_kind:"category_definition",evidence_status:"not_classified",
      observed_attempts:null,observed_failures:null,observed_matches:null,machine_key_eligible:false,
      recognition:keys.map(key=>selected[key].definition),
      counter_play:Object.keys(catalogue.guidance).flatMap(key=>catalogue.guidance[key][facets[key]]),
      success_criteria:[...catalogue.categories[0].success_criteria],
    };
  }
  function presetsFor(catalogue,facets) {
    describe(catalogue,facets);
    const spin=catalogue.facets.spin.values.find(item=>item.id===facets.spin);
    if(spin.side&&facets.direction!=="unspecified")return [spin.presets[facets.direction==="clockwise"?0:1]];
    return [...spin.presets];
  }
  function matches(catalogue,category,context,spin,query) {
    const labels=Object.entries(category.facets).map(([key,id])=>catalogue.facets[key].values.find(value=>value.id===id).label);
    return (context==="all"||category.facets.context===context)
      &&(spin==="all"||category.facets.spin===spin)
      &&`${category.name} ${labels.join(" ")}`.toLowerCase().includes(query.trim().toLowerCase());
  }
  function placementSide(placement,hand) {
    if(placement==="middle")return "middle";
    if(!["left","right"].includes(hand)||placement==="unknown")return null;
    const back=placement.endsWith("backhand");
    if(!back&&!placement.endsWith("forehand"))throw new Error("Unknown placement");
    return (hand==="right")===back?"left":"right";
  }
  function placementGraphic(category,hand,h) {
    const side=placementSide(category.facets.placement,hand);
    if(side===null)return '<p class="notice">Placement illustration unavailable: a fixed playing hand and a known target side are needed. No side is guessed.</p>';
    const wide=category.facets.placement.startsWith("wide_"),width=wide?22:46;
    const x=side==="middle"?77:side==="left"?30:170-width;
    return `<figure class="catalogue-placement"><svg viewBox="0 0 200 210" role="img" aria-label="${h(`Illustrative ${category.facets.placement.replaceAll("_"," ")} target; ${hand} handed reference`)}">
      <rect x="30" y="25" width="140" height="150" rx="3" fill="#426a51"/><path d="M100 25 V175 M30 100 H170" stroke="#fff" stroke-width="2"/>
      <rect x="${x}" y="104" width="${width}" height="67" fill="#d5ee9b" opacity=".85"/>
      <text x="100" y="16" text-anchor="middle" fill="#203630" font-size="11">Opponent</text><text x="100" y="192" text-anchor="middle" fill="#203630" font-size="11">Receiver</text>
      </svg><figcaption>Illustrative target side only${["left","right"].includes(hand)?` (${h(hand)}-handed reference)`:""}. Not measured bounce positions, length, or classification boundaries.</figcaption></figure>`;
  }
  function initialize({catalogue,player,scope,h,downloadJson,onError}) {
    const $=id=>document.getElementById(id);
    if(catalogue.format!=="11analyst.shot-catalogue"||catalogue.version!==1||!catalogue.categories.length)throw new Error("Unsupported shot catalogue");
    let selected=catalogue.categories[0], currentScope=scope;
    const choices=(key,allowed)=>catalogue.facets[key].values.filter(value=>!allowed||allowed.includes(value.id));
    function options(key,allowed){
      $(`catalogue-${key}`).replaceChildren(...choices(key,allowed).map(item=>{
        const option=document.createElement("option");option.value=item.id;option.textContent=item.label;return option;
      }));
    }
    for(const key of Object.keys(catalogue.facets))options(key);
    for(const item of catalogue.facets.spin.values){
      const option=document.createElement("option");option.value=item.id;option.textContent=item.label;$("catalogue-filter-spin").append(option);
    }
    function setControls(facets) {
      options("length",catalogue.context_lengths[facets.context]);
      const side=catalogue.facets.spin.values.find(item=>item.id===facets.spin).side;
      options("direction",side?["unspecified","clockwise","counterclockwise"]:["not_applicable"]);
      $("catalogue-direction").disabled=!side;
      for(const key of Object.keys(catalogue.facets))$(`catalogue-${key}`).value=facets[key];
    }
    const list=items=>`<ul>${items.map(text=>`<li>${h(text)}</li>`).join("")}</ul>`;
    function renderSelection() {
      $("catalogue-selected-name").textContent=selected.name;
      $("catalogue-selected-tag").textContent=selected.milestone_example?"Milestone-one example / definition only":"Category definition / not a diagnosis";
      $("catalogue-recognition").innerHTML=list(selected.recognition);
      $("catalogue-counter").innerHTML=list(selected.counter_play);
      $("catalogue-success").innerHTML=list(selected.success_criteria);
      $("catalogue-placement").innerHTML=placementGraphic(selected,player.handedness,h);
      $("catalogue-spin-links").innerHTML=presetsFor(catalogue,selected.facets).map(id=>`<button class="button small secondary" data-catalogue-spin="${h(id)}">Illustrate ${h(ElevenSpin.presets[id].name)}</button>`).join("")||'<p class="caption">Spin is unknown; no spin illustration is selected.</p>';
      $("catalogue-status").textContent=`Selected definition: ${selected.name}. Observed category counts are unknown, not zero.`;
    }
    function renderLibrary() {
      const rows=catalogue.categories.filter(item=>matches(catalogue,item,$("catalogue-filter-context").value,$("catalogue-filter-spin").value,$("catalogue-search").value));
      $("catalogue-count").textContent=`${rows.length} of ${catalogue.categories.length} starter categories`;
      $("catalogue-cards").innerHTML=rows.length?rows.map(item=>`<article class="training-card"><span class="chip">${item.milestone_example?"Milestone example":"Definition"}</span><h3>${h(item.name)}</h3><p class="caption">Recognize it, choose a response, and define success. Log matches not classified yet.</p><button class="button secondary" data-catalogue-id="${h(item.id)}">View category &amp; counter-play</button></article>`).join(""):'<p class="empty-state">No starter categories match these filters. Use the name builder to explore other combinations.</p>';
    }
    function updateScope(next) {
      currentScope=next;
      const pilot=currentScope.serve_reception_pilot;
      $("catalogue-available-evidence").textContent=`Available broad serve evidence in the selected match mode: ${pilot.receiving_attempts} observed first-return attempts, ${pilot.confirmed_failures} confirmed failures, ${pilot.distinct_matches} matches. These counts are NOT assigned to the selected named category. Specific spin, length and placement remain unclassified.`;
    }
    function guard(action){return event=>{try{action(event);}catch(error){onError(error);}};}
    for(const key of Object.keys(catalogue.facets)){
      $(`catalogue-${key}`).addEventListener("change",guard(()=>{
        const facets={...selected.facets,[key]:$(`catalogue-${key}`).value};
        let adjustment="";
        if(key==="context"&&!catalogue.context_lengths[facets.context].includes(facets.length)){
          facets.length=catalogue.default_lengths[facets.context];adjustment="Length/depth was reset for the new incoming-ball context. ";
        }
        if(key==="spin"){
          const side=catalogue.facets.spin.values.find(item=>item.id===facets.spin).side;
          facets.direction=side?(facets.direction==="not_applicable"?"unspecified":facets.direction):"not_applicable";
          adjustment="Sidespin-direction choices were updated for this family. ";
        }
        selected=describe(catalogue,facets);setControls(facets);renderSelection();
        $("catalogue-status").textContent=adjustment+$("catalogue-status").textContent;
      }));
    }
    $("catalogue-search").addEventListener("input",guard(renderLibrary));
    for(const id of ["catalogue-filter-context","catalogue-filter-spin"])$(id).addEventListener("change",guard(renderLibrary));
    $("shot-catalogue").addEventListener("click",guard(event=>{
      const categoryButton=event.target.closest("[data-catalogue-id]");
      const spinButton=event.target.closest("[data-catalogue-spin]");
      if(categoryButton){
        selected=catalogue.categories.find(item=>item.id===categoryButton.dataset.catalogueId);
        if(!selected)throw new Error("Category not found");
        setControls(selected.facets);renderSelection();
        $("catalogue-selected-name").focus();$("catalogue-selection").scrollIntoView({block:"start"});
      }else if(spinButton){
        const preset=spinButton.dataset.catalogueSpin;
        if(!presetsFor(catalogue,selected.facets).includes(preset))throw new Error("This spin illustration does not belong to the selected category");
        if(preset==="axial"){
          $("spin-advanced").checked=true;$("spin-advanced").dispatchEvent(new Event("change",{bubbles:true}));
        }
        $("spin-preset").value=preset;$("spin-preset").dispatchEvent(new Event("change",{bubbles:true}));
        location.hash="spin-guide";$("spin-preset").focus();
      }
    }));
    $("catalogue-export").addEventListener("click",guard(()=>downloadJson("11-analyst-shot-catalogue.json",catalogue)));
    $("catalogue-export-selected").addEventListener("click",guard(()=>downloadJson("11-analyst-shot-definition.json",{
      format:"11analyst.shot-definition",version:1,category:selected,classification_gates:catalogue.classification_gates,
    })));
    $("catalogue-gates").innerHTML=list(catalogue.classification_gates);
    $("catalogue-limits").innerHTML=list(catalogue.limits);
    setControls(selected.facets);renderSelection();renderLibrary();updateScope(scope);
    return {updateScope};
  }
  return {describe,presetsFor,matches,placementSide,placementGraphic,initialize};
});
