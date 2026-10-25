const test=require("node:test"),assert=require("node:assert/strict");
const {execFileSync}=require("node:child_process"),path=require("node:path");
const api=require("../dashboard/catalogue.js"),spin=require("../dashboard/spin.js");
const catalogue=JSON.parse(execFileSync("python",["-c","import json,shot_catalogue; print(json.dumps(shot_catalogue.build()))"],{
  cwd:path.resolve(__dirname,".."),encoding:"utf8"
}));
const h=text=>String(text).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

test("browser descriptions match the persisted Python taxonomy exactly",()=>{
  for(const category of catalogue.categories){
    const {milestone_example,...expected}=category;
    assert.deepEqual(api.describe(catalogue,category.facets),expected);
  }
});
test("all valid name-builder combinations are explicit definitions with no invented evidence",()=>{
  let count=0;
  for(const context of catalogue.facets.context.values)
    for(const length of catalogue.context_lengths[context.id])
      for(const placement of catalogue.facets.placement.values)
        for(const family of catalogue.facets.spin.values)
          for(const direction of family.side?["unspecified","clockwise","counterclockwise"]:["not_applicable"])
            for(const pace of catalogue.facets.pace.values){
              const facets={context:context.id,length,placement:placement.id,spin:family.id,direction,pace:pace.id};
              const item=api.describe(catalogue,facets);
              assert.ok(item.name&&!item.name.includes("undefined"));
              assert.equal(item.observed_attempts,null);
              assert.equal(item.machine_key_eligible,false);
              for(const preset of api.presetsFor(catalogue,facets))assert.ok(spin.presets[preset]);
              count++;
            }
  assert.equal(count,2688);
});
test("invalid combinations cannot silently become a different category",()=>{
  const facets=catalogue.categories[0].facets;
  for(const change of [{context:"unknown"},{length:"deep"},{spin:"top"},{direction:"not_applicable"},{pace:"invalid"}])
    assert.throws(()=>api.describe(catalogue,{...facets,...change}));
  assert.throws(()=>api.describe(catalogue,{}));
});
test("sidespin examples preserve explicit directions instead of guessing from handedness",()=>{
  const facets=catalogue.categories[0].facets;
  assert.deepEqual(api.presetsFor(catalogue,facets),["clockwise","counterclockwise"]);
  assert.deepEqual(api.presetsFor(catalogue,{...facets,direction:"counterclockwise"}),["counterclockwise"]);
  assert.deepEqual(api.presetsFor(catalogue,{...facets,spin:"side_back",direction:"clockwise"}),["backClockwise"]);
});
test("placement illustrations mirror for handedness without implying a stroke or calibrated bounds",()=>{
  assert.equal(api.placementSide("backhand","right"),"left");
  assert.equal(api.placementSide("backhand","left"),"right");
  assert.equal(api.placementSide("wide_forehand","right"),"right");
  assert.equal(api.placementSide("middle","unknown"),"middle");
  assert.equal(api.placementSide("backhand","unknown"),null);
  assert.equal(api.placementSide("backhand","varies"),null);
  const graphic=api.placementGraphic(catalogue.categories[0],"right",h);
  assert.match(graphic,/Illustrative target side only/);
  assert.match(graphic,/Not measured bounce positions/);
  assert.doesNotMatch(api.placementGraphic(catalogue.categories[0],"unknown",h),/<svg/);
});
test("library filters intersect without changing categories",()=>{
  const before=JSON.stringify(catalogue), first=catalogue.categories[0];
  assert.equal(api.matches(catalogue,first,"serve","side"," BACKHAND "),true);
  assert.equal(api.matches(catalogue,first,"rally","side","backhand"),false);
  assert.equal(api.matches(catalogue,first,"serve","top","backhand"),false);
  assert.equal(api.matches(catalogue,first,"serve","side","forehand"),false);
  assert.equal(JSON.stringify(catalogue),before);
});
