(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ElevenGraphics = api;
})(globalThis, function () {
  "use strict";
  const vector = value => Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
  const finite = value => {
    const number = typeof value === "string" && value.trim() ? Number(value) : NaN;
    if (!Number.isFinite(number)) throw new Error("Cannot draw an invalid machine setting");
    return number;
  };
  const display = value => !Number.isFinite(value) ? "Unavailable"
    : value !== 0 && (Math.abs(value) < .001 || Math.abs(value) >= 10000) ? value.toExponential(2)
    : String(Number(value.toFixed(3)));
  const magnitude = value => vector(value) ? Math.hypot(...value) : null;
  const inks = {before: "#387d99", after: "#a85a28"};
  const tableGeometry = Object.freeze({width: 1.525, length: 2.74, height: .76, netHeight: .1525});

  function tablePoint(u, v, height = 0) {
    if (![u, v, height].every(Number.isFinite)) throw new Error("Invalid illustrated table coordinate");
    const pitch = 50 * Math.PI / 180, x = (u - .5) * tableGeometry.width, z = (v - .5) * tableGeometry.length;
    const depth = 5 - z * Math.cos(pitch) - height * Math.sin(pitch);
    if (depth <= 0) throw new Error("Illustrated table coordinate is behind the camera");
    const projected = [180 + 540 * x / depth, 152 + 540 * (z * Math.sin(pitch) - height * Math.cos(pitch)) / depth];
    if (!projected.every(Number.isFinite)) throw new Error("Illustrated table coordinate exceeds numeric range");
    return projected;
  }

  function eventsFor(point, playerId) {
    let hits = 0;
    return point.events.flatMap((event, index) => {
      if (!["hit", "collision"].includes(event.kind)) return [];
      const actor = event.actor_id === playerId ? "You" : event.actor_id ? "Opponent" : "Unattributed";
      const name = event.kind === "hit" ? `Hit ${++hits}: ${actor}, ${event.phase || "unknown phase"}`
        : `Collision: ${event.collision_type || "unknown type"}`;
      return [{index, event, label: `Attempt ${event.attempt} / ${name} / line ${event.line}`}];
    });
  }

  function projection(samples, selected, axes) {
    const positions = samples.filter(sample => vector(sample.state?.position));
    if (!positions.length) return null;
    // Normalize before fitting so very large but finite log coordinates cannot overflow a range subtraction.
    const unit = Math.max(1, ...positions.flatMap(sample => axes.map(axis => Math.abs(sample.state.position[axis]))));
    const xs = positions.map(sample => sample.state.position[axes[0]] / unit);
    const ys = positions.map(sample => sample.state.position[axes[1]] / unit);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const centerX = minX / 2 + maxX / 2, centerY = minY / 2 + maxY / 2;
    const scale = Math.min(222 / (maxX - minX || 1), 132 / (maxY - minY || 1));
    const project = position => [194 + (position[axes[0]] / unit - centerX) * scale,
      127 - (position[axes[1]] / unit - centerY) * scale];
    const dots = positions.map(sample => ({...sample, xy: project(sample.state.position), selected: sample.index === selected}));
    const arrows = dots.filter(sample => sample.selected && vector(sample.state.velocity)).map(sample => {
      const velocity = axes.map(axis => sample.state.velocity[axis]);
      const maximum = Math.max(...velocity.map(Math.abs));
      const length = maximum ? Math.hypot(...velocity.map(value => value / maximum)) : 0;
      const delta = length ? [32 * (velocity[0] / maximum) / length, -32 * (velocity[1] / maximum) / length] : [0, 0];
      const start = sample.side === "before" ? sample.xy.map((value, i) => value - delta[i]) : sample.xy;
      const end = sample.side === "before" ? sample.xy : sample.xy.map((value, i) => value + delta[i]);
      return {...sample, start, end, zero: !length};
    });
    return {
      axes, dots, arrows,
      xTicks: [82, 194, 306].map(pixel => ({pixel, value: ((pixel - 194) / scale + centerX) * unit})),
      yTicks: [61, 127, 193].map(pixel => ({pixel, value: ((127 - pixel) / scale + centerY) * unit})),
    };
  }

  function recordedModel(point, index, playerId) {
    const choices = eventsFor(point, playerId);
    const selected = index == null ? choices.find(item => item.event.kind === "hit") || choices[0]
      : choices.find(item => item.index === index);
    if (index != null && !selected) throw new Error("Recorded shot selection is unavailable");
    if (!selected || !["bounded", "bounded_multiple_attempts"].includes(point.telemetry.status)) {
      return {choices, selected, unavailable: "No bounded contact measurements are available for this point. No shot geometry is inferred."};
    }
    const samples = choices.filter(item => item.event.attempt === selected.event.attempt).flatMap(item =>
      ["before", "after"].filter(side => item.event[side]).map(side => ({
        index: item.index, side, state: item.event[side], label: `${item.label}, ${side}`,
      })));
    const notices = ["before", "after"].flatMap(side => {
      const state = selected.event[side];
      return ["position", "velocity", "rotation_rate"].filter(field => !vector(state?.[field]))
        .map(field => `${side === "before" ? "Incoming" : "Outgoing"} ${field.replaceAll("_", " ")} unavailable.`);
    });
    if (point.telemetry.measurement_status === "gaps_detected" || point.telemetry.parse_warning_count) {
      notices.push("Measurement gaps are present. Only retained samples are drawn.");
    }
    return {choices, selected, notices, plots: [[0, 2], [0, 1]].map(axes => projection(samples, selected.index, axes))};
  }

  function feedModels(candidate, collection) {
    if (!candidate) return [];
    const roles = {};
    return Object.values(candidate.settings.shots.data).map((shot, index) => {
      const stageIndex = candidate.stages?.findIndex(stage => stage.feeds.includes(index + 1)) ?? -1;
      const stage = candidate.stages?.[stageIndex];
      let recipe = stage ? candidate.recipe_ids[stageIndex] : candidate.recipe_id;
      if (collection) recipe = collection.planned_sequence[index] === "serve" ? "serve-reception" : "two-location-recovery";
      roles[recipe] = (roles[recipe] || 0) + 1;
      return {
        number: index + 1, recipe, localFeed: stage ? stage.feeds.indexOf(index + 1) + 1 : roles[recipe],
        stage: stageIndex + 1, stageTitle: stage?.title, active: shot.isActive === "True",
        horizontal: finite(shot.direction.raw.horizontalAngle), vertical: finite(shot.direction.raw.verticalAngle),
        position: ["x", "y", "z"].map(axis => finite(shot.position.raw[axis])),
        spin: ["topBottom", "leftRight", "screw"].map(axis => finite(shot.spin.raw[axis])),
        speed: finite(shot.speedAndRate.raw.speed), interval: finite(shot.speedAndRate.raw.secondsPerLaunch),
        delay: finite(shot.speedAndRate.raw.PostDelay),
        spread: [finite(shot.direction.spread.horizontalAngle), finite(shot.direction.spread.verticalAngle)],
      };
    });
  }

  function createRenderer(h) {
    const svg = (label, body, box = "0 0 360 270") => `<svg class="shot-svg" viewBox="${box}" role="img" aria-label="${h(label)}">${body}</svg>`;
    const arrow = (start, end, color) => {
      const angle = Math.atan2(end[1] - start[1], end[0] - start[0]);
      const wing = offset => [end[0] - 8 * Math.cos(angle + offset), end[1] - 8 * Math.sin(angle + offset)].join(",");
      return `<line x1="${start[0]}" y1="${start[1]}" x2="${end[0]}" y2="${end[1]}" stroke="${color}" stroke-width="2.5"/><polygon points="${end.join(",")} ${wing(.5)} ${wing(-.5)}" fill="${color}"/>`;
    };
    const notice = text => `<p class="graphic-note">${h(text)}</p>`;

    function plot(model) {
      if (!model) return notice("No valid positions were recorded for this attempt.");
      const [a, b] = model.axes.map(axis => "XYZ"[axis]);
      return svg(`Measured ball positions in raw ${a}/${b} coordinates; velocity arrows show direction only`,
        `<rect x="46" y="26" width="296" height="201" rx="8" fill="#f5f7f4"/>
        ${model.xTicks.map(tick => `<line x1="${tick.pixel}" x2="${tick.pixel}" y1="26" y2="227" stroke="#dce5df"/><text x="${tick.pixel}" y="246" text-anchor="middle">${h(display(tick.value))}</text>`).join("")}
        ${model.yTicks.map(tick => `<line x1="46" x2="342" y1="${tick.pixel}" y2="${tick.pixel}" stroke="#dce5df"/><text x="40" y="${tick.pixel + 4}" text-anchor="end">${h(display(tick.value))}</text>`).join("")}
        <text x="194" y="265" text-anchor="middle">Raw ${a}</text><text x="48" y="17">Raw ${b}</text>
        ${model.dots.filter(dot => !dot.selected).map(dot => `<circle cx="${dot.xy[0]}" cy="${dot.xy[1]}" r="3" fill="#a9b6ad"><title>${h(dot.label)}</title></circle>`).join("")}
        ${model.arrows.filter(item => !item.zero).map(item => arrow(item.start, item.end, inks[item.side])).join("")}
        ${model.dots.filter(dot => dot.selected).map(dot => `<circle cx="${dot.xy[0]}" cy="${dot.xy[1]}" r="${dot.side === "before" ? 7 : 3.5}" fill="${dot.side === "before" ? "white" : inks.after}" stroke="${inks[dot.side]}" stroke-width="2"><title>${h(dot.label)}</title></circle>`).join("")}`);
    }

    function bars(values, labels, title, maxValue) {
      if (!vector(values)) return notice(`${title}: no valid measurements.`);
      const maximum = maxValue || Math.max(...values.map(Math.abs)) || 1;
      return svg(title, values.map((value, index) => {
        const length = Math.abs(value) / maximum * 74, y = 20 + index * 29;
        return `<text x="4" y="${y + 4}">${h(labels[index])}</text>
          <line x1="143" x2="291" y1="${y}" y2="${y}" stroke="#dce5df" stroke-width="10"/>
          <rect x="${value < 0 ? 217 - length : 217}" y="${y - 5}" width="${length}" height="10" fill="${value < 0 ? inks.after : inks.before}"/>
          <line x1="217" x2="217" y1="${y - 9}" y2="${y + 9}" stroke="#203630"/>
          <text x="356" y="${y + 4}" text-anchor="end">${h(display(value))}</text>`;
      }).join("") + '<text x="217" y="107" text-anchor="middle">0 (signed components)</text>', "0 0 360 116");
    }

    function recorded(point, index, playerId) {
      const model = recordedModel(point, index, playerId);
      if (model.unavailable) return notice(model.unavailable);
      const event = model.selected.event;
      const maximum = Math.max(0, ...["before", "after"].flatMap(side =>
        vector(event[side]?.rotation_rate) ? event[side].rotation_rate.map(Math.abs) : []));
      return `<p class="graphic-title">${h(model.selected.label)}</p>
        ${model.notices.length ? `<div class="notice">${model.notices.map(h).join(" ")}</div>` : ""}
        <div class="shot-legend"><span class="incoming">IN: incoming, open circle</span><span class="outgoing">OUT: outgoing, filled circle</span><span>Grey: other samples in this attempt</span></div>
        <div class="shot-plot-grid">${model.plots.map(plot).join("")}</div>
        ${notice("Raw log coordinates, not a calibrated table view. No samples are joined into a flight path. Velocity arrows have equal display length: direction only, not distance or speed. A zero projection has no arrow.")}
        <div class="shot-plot-grid">${["before", "after"].map(side => `<div><h4>${side === "before" ? "Incoming" : "Outgoing"} ball</h4>
          <p>Speed magnitude (raw): <strong>${h(display(magnitude(event[side]?.velocity)))}</strong></p>
          <p class="graphic-note">Position X/Y/Z: ${vector(event[side]?.position) ? event[side].position.map(display).map(h).join(" / ") : "Unavailable"}</p>
          ${bars(event[side]?.rotation_rate, ["X", "Y", "Z"], `${side} rotation rate in raw log axes`, maximum)}</div>`).join("")}</div>
        ${notice("Rotation-rate bars use raw log axes, not top/side-spin labels or launcher spin settings. Paddle pose and swing paths are not available.")}`;
    }

    function pointBrowser(point, playerId, index) {
      const model = recordedModel(point, index, playerId);
      return `<section class="shot-explorer"><h3>Shot graphics</h3>
        ${model.choices.length ? `<label for="shot-event">Choose an observed hit or collision</label><select id="shot-event">${model.choices.map(item => `<option value="${item.index}" ${item.index === model.selected.index ? "selected" : ""}>${h(item.label)}</option>`).join("")}</select>` : ""}
        <div id="recorded-shot-graphic" aria-live="polite">${recorded(point, index, playerId)}</div></section>`;
    }

    function intent(recipe, feed) {
      if (!["serve-legality", "serve-reception", "two-location-recovery", "controlled-variation", "repeatable-contact"].includes(recipe)) {
        return notice("No coaching schematic is defined for this recipe.");
      }
      const manual = recipe === "serve-legality", serve = recipe === "serve-reception";
      const two = recipe === "two-location-recovery", variable = recipe === "controlled-variation";
      const u = two ? feed % 2 ? .24 : .76 : .5;
      const targets = two && feed == null ? [{u: .24, label: "A"}, {u: .76, label: "B"}]
        : [{u, label: two ? feed % 2 ? "A" : "B" : "Target"}];
      const text = manual ? "Own-serve practice: two legal bounces" : two ? feed == null ? "Alternate targets A / B" : `Proposed target ${feed % 2 ? "A" : "B"}` : variable ? "Small placement variation" : serve ? "Receive one familiar serve" : "Repeat a manageable target";
      const point = (u, v, height = 0) => tablePoint(u, v, height).join(",");
      const line = (a, b, color, width = 1) => `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="${color}" stroke-width="${width}"/>`;
      const polygon = (points, fill) => `<polygon points="${points.join(" ")}" fill="${fill}"/>`;
      const surface = [point(0, 0), point(1, 0), point(1, 1), point(0, 1)];
      const legs = [.12, .88].flatMap(x => [.08, .95].map(z =>
        line(tablePoint(x, z, -.03), tablePoint(x, z, -tableGeometry.height), "#344b58", 6))).join("");
      const net = `<g class="table-net">
        ${polygon([point(-.1, .5), point(1.1, .5), point(1.1, .5, tableGeometry.netHeight), point(-.1, .5, tableGeometry.netHeight)], "#263e47")}
        ${Array.from({length: 23}, (_, i) => {
          const x = -.1 + 1.2 * i / 22;
          return line(tablePoint(x, .5), tablePoint(x, .5, tableGeometry.netHeight), "#b8cdd0", .55);
        }).join("")}
        ${[1 / 3, 2 / 3].map(f => line(tablePoint(-.1, .5, f * tableGeometry.netHeight), tablePoint(1.1, .5, f * tableGeometry.netHeight), "#b8cdd0", .55)).join("")}
        ${line(tablePoint(-.1, .5, tableGeometry.netHeight), tablePoint(1.1, .5, tableGeometry.netHeight), "#f7faf8", 2.5)}
        ${[-.1, 1.1].map(x => line(tablePoint(x, .5, -.025), tablePoint(x, .5, tableGeometry.netHeight + .015), "#233c49", 3)).join("")}
        <text x="290" y="145">NET</text></g>`;
      const bounces = [
        {u: .4, v: .25, side: "far", order: manual ? 2 : 1},
        {u: .6, v: .78, side: "near", order: manual ? 1 : 2},
      ];
      const overlay = manual || serve ? bounces.map(bounce => {
        const [x, y] = tablePoint(bounce.u, bounce.v);
        return `<g data-bounce="${bounce.order}" data-side="${bounce.side}"><circle cx="${x}" cy="${y}" r="14" fill="#d5ee9b" stroke="#fff" stroke-width="1.5"/><text x="${x}" y="${y + 4}" text-anchor="middle">${bounce.order}</text></g>`;
      }).join("") : targets.map(target => {
        const [x, y] = tablePoint(target.u, .78);
        return `<g data-target="${target.label}"><ellipse cx="${x}" cy="${y}" rx="${variable ? 45 : 22}" ry="17" fill="#d5ee9b" fill-opacity=".85" stroke="white" stroke-dasharray="4 4"/><text x="${x}" y="${y + 4}" text-anchor="middle">${target.label}</text></g>`;
      }).join("");
      return `<figure class="training-intent">${svg(text + ". Coaching schematic, not predicted landing or flight.",
        `<ellipse cx="180" cy="305" rx="123" ry="20" fill="#203630" opacity=".07"/>
        <g class="table-frame">${legs}${line(tablePoint(.12, .95, -.5), tablePoint(.88, .95, -.5), "#344b58", 4)}</g>
        <g class="table-surface">${polygon(surface, "#246d96")}
        ${polygon([point(0, .5), point(1, .5), point(1, 1), point(0, 1)], "#2b789f")}
        <polygon points="${[point(.006, .004), point(.994, .004), point(.994, .996), point(.006, .996)].join(" ")}" fill="none" stroke="#f6faf8" stroke-width="2"/>
        ${line(tablePoint(.5, .005), tablePoint(.5, .995), "#f6faf8", .8)}</g>
        ${polygon([point(0, 1), point(1, 1), point(1, 1, -.035), point(0, 1, -.035)], "#173e58")}
        ${overlay}${net}
        <text x="180" y="27" text-anchor="middle">${manual ? "FAR SIDE" : "FEED SIDE"}</text><text x="180" y="342" text-anchor="middle">YOUR SIDE</text>
        <text x="180" y="369" text-anchor="middle">${h(text)}</text>`, "0 0 360 382")}
        <figcaption>Perspective table-tennis illustration. Targets and bounce markers are coaching schematics, not measured or predicted landings.</figcaption></figure>`;
    }

    function aim(feed) {
      const hAngle = (feed.horizontal % 360) * Math.PI / 180, vAngle = (feed.vertical % 360) * Math.PI / 180;
      return svg("Configured launcher angle gauges; diagram zero directions are not calibrated table axes",
        `<circle cx="94" cy="60" r="33" fill="none" stroke="#dce5df"/><line x1="94" x2="94" y1="20" y2="98" stroke="#dce5df"/>
        ${arrow([94, 60], [94 + 31 * Math.sin(hAngle), 60 - 31 * Math.cos(hAngle)], inks.before)}
        <circle cx="267" cy="60" r="33" fill="none" stroke="#dce5df"/><line x1="226" x2="307" y1="60" y2="60" stroke="#dce5df"/>
        ${arrow([267, 60], [267 + 31 * Math.cos(vAngle), 60 - 31 * Math.sin(vAngle)], inks.after)}
        <text x="94" y="15" text-anchor="middle">Horizontal</text><text x="267" y="15" text-anchor="middle">Vertical</text>
        <text x="94" y="115" text-anchor="middle">${h(display(feed.horizontal))}&#176;</text><text x="267" y="115" text-anchor="middle">${h(display(feed.vertical))}&#176;</text>`, "0 0 360 127");
    }

    function training(candidate, collection) {
      if (!candidate) return notice("No machine feeds are available for this selection.");
      const feeds = feedModels(candidate, collection);
      const maximum = Math.max(0, ...feeds.flatMap(feed => feed.spin.map(Math.abs)));
      return `<div class="training-feed-grid">${feeds.map(feed => `<article class="training-feed">
        <div class="panel-heading"><h4>Feed ${feed.number}</h4><span class="chip ${feed.active ? "" : "neutral"}">${feed.active ? "Active initially" : "Inactive initially"}</span></div>
        ${feed.stageTitle ? `<p class="graphic-title">Stage ${feed.stage}: ${h(feed.stageTitle)}</p>` : ""}
        ${intent(feed.recipe, feed.localFeed)}${aim(feed)}
        <dl class="feed-values"><div><dt>Speed setting</dt><dd>${h(display(feed.speed))}</dd></div><div><dt>Launch interval</dt><dd>${h(display(feed.interval))} s</dd></div><div><dt>PostDelay</dt><dd>${h(display(feed.delay))} s</dd></div><div><dt>Aim spread H / V</dt><dd>${feed.spread.map(display).map(h).join(" / ")}&#176;</dd></div></dl>
        <p class="graphic-note">Launcher position X/Y/Z (settings coordinates): ${feed.position.map(display).map(h).join(" / ")}</p>
        <h4>Configured spin controls</h4>${bars(feed.spin, ["Top / bottom", "Left / right", "Screw"], "Machine spin settings, not measured ball rotation", maximum)}
      </article>`).join("")}</div>
      ${notice("Gauges show configured angles: horizontal zero points up on the gauge; vertical zero points right. These conventions are not a calibration to table axes. Targets are coaching illustrations, not trajectory calculations. Displayed settings are rounded; original precision is retained in the key payload.")}
      ${notice(`Time-scale setting: ${candidate.settings.timeScale}. Feed intervals and PostDelay are settings, not a measured cadence. These graphics do not change settings, activate feeds, or publish anything.`)}`;
    }

    function lossSplit(item) {
      return `<div class="opportunity-bars" aria-label="Breakdown of observed return losses">${[
        ["Missed", item.missed_returns], ["Failed landing", item.failed_landings],
      ].map(([label, count]) => `<div><span>${h(label)} (${h(count)})</span><span class="loss-split-track"><i style="width:${item.losses ? 100 * count / item.losses : 0}%"></i></span></div>`).join("")}</div>`;
    }
    return {recorded, pointBrowser, intent, training, lossSplit};
  }
  return {vector, projection, recordedModel, eventsFor, feedModels, tableGeometry, tablePoint, createRenderer};
});
