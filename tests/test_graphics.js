"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const graphics = require("../dashboard/graphics.js");
const h = value => String(value ?? "").replace(/[&<>"']/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
}[char]));
const render = graphics.createRenderer(h);
const state = (position = [0, 1, 2], velocity = [3, 0, -4]) => ({
  position, velocity, rotation_rate: [-12, 0, 8],
});
const hit = (attempt = 1) => ({
  kind: "hit", actor_id: "1", phase: "rally", attempt, line: 10,
  before: state(), after: state([0, 1, 2], [-3, 0, 4]),
});
const point = () => ({
  telemetry: {status: "bounded", measurement_status: "no_detected_gaps"},
  events: [hit()],
});
const shot = (active = true, angle = "-17.5") => ({
  isActive: String(active ? "True" : "False"),
  position: {raw: {x: "-0.4", y: "-0.2", z: "0.18"}},
  direction: {raw: {horizontalAngle: angle, verticalAngle: "11.5"},
    spread: {horizontalAngle: "1.5", verticalAngle: "0"}},
  spin: {raw: {topBottom: "30", leftRight: "-4", screw: "0"}},
  speedAndRate: {raw: {speed: "10.35", secondsPerLaunch: "2", PostDelay: "0"}},
});
const candidate = () => ({
  recipe_id: "plan-shot-landing", recipe_ids: ["repeatable-contact", "controlled-variation"],
  stages: [{title: "Baseline", feeds: [1]}, {title: "Variation", feeds: [2]}],
  settings: {timeScale: "1", shots: {data: {A: shot(), B: shot(false)}}},
});

test("only complete finite three-component vectors are accepted", () => {
  for (const value of [null, [], [1,2], [1,2,3,4], ["1",2,3], [1,NaN,3], [1,Infinity,3]]) {
    assert.equal(graphics.vector(value), false);
  }
  assert.equal(graphics.vector([0,-1,2]), true);
});

test("recorded diagrams isolate attempts and do not mutate evidence", () => {
  const input = point();
  input.telemetry.status = "bounded_multiple_attempts";
  const other = hit(2);
  other.after.position = [999,999,999];
  input.events.push(other);
  const original = structuredClone(input);
  const model = graphics.recordedModel(input, 0, "1");
  assert.equal(model.plots[0].dots.length, 2);
  assert.ok(model.plots[0].dots.every(dot => dot.index === 0));
  assert.equal(model.choices.length, 2);
  assert.deepEqual(input, original);
  assert.ok(graphics.recordedModel(input, 1, "1").plots[0].dots.every(dot => dot.index === 1));
});

test("incoming arrows end at contact and outgoing arrows start at contact", () => {
  const model = graphics.recordedModel(point(), 0, "1");
  const [incoming, outgoing] = model.plots[0].arrows;
  assert.deepEqual(incoming.end, incoming.xy);
  assert.deepEqual(outgoing.start, outgoing.xy);
  assert.ok(incoming.start[0] < incoming.end[0]);
  assert.ok(outgoing.end[0] < outgoing.start[0]);
  for (const arrow of model.plots[0].arrows) {
    assert.ok(Math.abs(Math.hypot(arrow.end[0]-arrow.start[0], arrow.end[1]-arrow.start[1])-32)<1e-10);
  }
});

test("direction glyphs are normalized independently of speed", () => {
  const input = point();
  const original = graphics.recordedModel(input, 0, "1").plots[0].arrows[0];
  input.events[0].before.velocity = [3000,0,-4000];
  const faster = graphics.recordedModel(input, 0, "1").plots[0].arrows[0];
  assert.deepEqual(original.start, faster.start);
  assert.deepEqual(original.end, faster.end);
});

test("zero and out-of-plane velocities have no invented direction", () => {
  const input = point();
  input.events[0].before.velocity = [0,7,0];
  const model = graphics.recordedModel(input, 0, "1");
  assert.equal(model.plots[0].arrows[0].zero, true);
  assert.equal(model.plots[1].arrows[0].zero, false);
  input.events[0].before.velocity = [0,0,0];
  assert.equal(graphics.recordedModel(input, 0, "1").plots[1].arrows[0].zero, true);
});

test("missing states and measurement gaps are explicit without zero-filled measurements", () => {
  const input = point();
  input.events[0].before = null;
  input.events[0].after.position = [NaN,0,0];
  input.telemetry.measurement_status = "gaps_detected";
  const model = graphics.recordedModel(input, 0, "1");
  assert.equal(model.plots[0], null);
  assert.ok(model.notices.some(text => text.includes("Incoming position unavailable")));
  assert.ok(model.notices.some(text => text.includes("Measurement gaps")));
  const html = render.recorded(input, 0, "1");
  assert.ok(html.includes("No valid positions"));
  assert.ok(!html.includes("NaN"));
});

test("unbounded windows and empty points cannot present invented shot geometry", () => {
  const input = point();
  input.telemetry.status = "missing_start";
  assert.ok(graphics.recordedModel(input, 0, "1").unavailable);
  assert.ok(!render.recorded(input, 0, "1").includes("<svg"));
  input.events = [];
  assert.ok(render.pointBrowser(input, "1").includes("No bounded contact"));
  assert.throws(() => graphics.recordedModel(point(), 42, "1"), /unavailable/);
});

test("single-position projections and extreme finite vectors keep SVG coordinates finite", () => {
  const input = point();
  input.events[0].before = state([1e300,1e300,1e300], [1e300,-1e300,1e300]);
  input.events[0].after = null;
  const model = graphics.recordedModel(input, 0, "1");
  for (const plot of model.plots) {
    assert.ok(plot.dots.every(dot => dot.xy.every(Number.isFinite)));
    assert.ok(plot.arrows.every(arrow => [...arrow.start,...arrow.end].every(Number.isFinite)));
  }
  assert.ok(!/NaN|Infinity/.test(render.recorded(input, 0, "1")));
});

test("training models retain feed order, stages, active flags and exact settings", () => {
  const input = candidate(), original = structuredClone(input);
  const feeds = graphics.feedModels(input);
  assert.deepEqual(feeds.map(feed => [feed.number,feed.stage,feed.recipe,feed.active]), [
    [1,1,"repeatable-contact",true], [2,2,"controlled-variation",false],
  ]);
  assert.deepEqual(feeds[0].spin, [30,-4,0]);
  assert.deepEqual(feeds[0].position, [-.4,-.2,.18]);
  assert.equal(feeds[0].horizontal, -17.5);
  const html = render.training(input);
  assert.ok(html.includes("Inactive initially") && html.includes("Stage 2"));
  assert.ok(html.includes("not trajectory calculations"));
  assert.deepEqual(input, original);
});

test("combined collections preserve the serve then two rally roles", () => {
  const input = {recipe_id:"combined", settings:{timeScale:"1", shots:{data:{A:shot(),B:shot(),C:shot()}}}};
  const feeds = graphics.feedModels(input, {planned_sequence:["serve","rally","rally"]});
  assert.deepEqual(feeds.map(feed => [feed.recipe,feed.localFeed]), [
    ["serve-reception",1],["two-location-recovery",1],["two-location-recovery",2],
  ]);
});

test("serve schematics distinguish serving from receiving bounce order", () => {
  assert.match(render.intent("serve-legality"), /data-bounce="1" data-side="near"/);
  assert.match(render.intent("serve-legality"), /data-bounce="2" data-side="far"/);
  assert.match(render.intent("serve-reception"), /data-bounce="1" data-side="far"/);
  assert.match(render.intent("serve-reception"), /data-bounce="2" data-side="near"/);
  assert.ok(!render.intent("serve-legality").includes('data-action="publish"'));
});

test("graphics escape all evidence labels and stage titles", () => {
  const hostile = '<img src=x onerror="alert(1)">';
  const input = point();
  input.events[0].phase = hostile;
  const machine = candidate();
  machine.stages[0].title = hostile;
  for (const html of [render.pointBrowser(input,"1"), render.training(machine)]) {
    assert.ok(!html.includes(hostile));
    assert.ok(html.includes("&lt;img"));
  }
});

test("invalid machine numbers throw rather than produce success-shaped graphics", () => {
  for (const value of ["", "Infinity", "NaN", "oops", null]) {
    const input = candidate();
    input.settings.shots.data.A.direction.raw.horizontalAngle = value;
    assert.throws(() => graphics.feedModels(input), /invalid machine setting/);
  }
});

test("unsupported recipes do not silently receive a baseline target", () => {
  const html = render.intent("unknown");
  assert.ok(html.includes("No coaching schematic"));
  assert.ok(!html.includes("<svg"));
});

test("two-target overview shows both locations while individual feeds show one", () => {
  assert.equal((render.intent("two-location-recovery").match(/data-target=/g)||[]).length, 2);
  assert.equal((render.intent("two-location-recovery",1).match(/data-target=/g)||[]).length, 1);
  assert.match(render.intent("two-location-recovery",2), /data-target="B"/);
});

test("training illustrations use table-tennis geometry, net mesh and a raised frame", () => {
  assert.equal(graphics.tableGeometry.width,1.525);
  assert.equal(graphics.tableGeometry.length,2.74);
  const nearLeft=graphics.tablePoint(0,1),nearRight=graphics.tablePoint(1,1);
  const farLeft=graphics.tablePoint(0,0),farRight=graphics.tablePoint(1,0);
  assert.ok(nearLeft[1]>farLeft[1]);
  assert.ok(nearRight[0]-nearLeft[0]>farRight[0]-farLeft[0]);
  assert.ok(graphics.tablePoint(.5,.5,graphics.tableGeometry.netHeight)[1]<graphics.tablePoint(.5,.5)[1]);
  assert.throws(()=>graphics.tablePoint(NaN,0),/Invalid/);
  assert.throws(()=>graphics.tablePoint(1e308,0),/numeric range/);
  for(const recipe of ["repeatable-contact","two-location-recovery","controlled-variation","serve-reception","serve-legality"]){
    const html=render.intent(recipe);
    assert.match(html,/class="table-surface"/);
    assert.match(html,/class="table-net"/);
    assert.match(html,/class="table-frame"/);
    assert.match(html,/not measured or predicted landings/);
    assert.doesNotMatch(html,/NaN|Infinity/);
  }
});
