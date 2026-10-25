(() => {
  "use strict";
  const format = "11analyst.ball-machine-key-records";
  const maxBytes = 64 * 1024;
  const storageKey = (playerId) => `11analyst:ball-machine-keys:v1:${playerId}`;
  const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

  function parseKey(value, playerId, provider = "manual") {
    if (!["manual", "11hero"].includes(provider)) throw new Error("Unknown key provider");
    if (typeof value !== "string" || value.length > 100 || !/^[1-9]\d*\.\d+$/.test(value.trim())) {
      throw new Error("Enter a returned key as PlayerID.SettingsID, including the dot");
    }
    const key = value.trim();
    const owner = provider === "11hero" ? "54334" : playerId;
    if (key.split(".")[0] !== owner) {
      throw new Error(`The key must belong to player ${owner} for the selected provider, not a community example or another account`);
    }
    return key;
  }

  function validateManifest(value, playerId) {
    if (!object(value) || value.format !== format || value.version !== 1 || value.player_id !== playerId) {
      throw new Error("This is not a version-1 key-record backup for the current player");
    }
    if (!Array.isArray(value.records) || value.records.length > 100) {
      throw new Error("Key records must be an array with at most 100 entries");
    }
    const ids = new Set();
    const records = value.records.map((record) => {
      if (!object(record) || typeof record.collection_id !== "string"
        || !/^[a-z0-9][a-z0-9-]{0,63}$/.test(record.collection_id) || ids.has(record.collection_id)) {
        throw new Error("Each record needs a unique collection ID");
      }
      ids.add(record.collection_id);
      if (typeof record.candidate_sha256 !== "string" || !/^[a-f0-9]{64}$/.test(record.candidate_sha256)) {
        throw new Error("Each record needs its original candidate's SHA-256 revision");
      }
      if (typeof record.recorded_at !== "string" || !Number.isFinite(Date.parse(record.recorded_at))
        || new Date(record.recorded_at).toISOString() !== record.recorded_at) {
        throw new Error("Each record needs a valid ISO recording timestamp");
      }
      if (!object(record.confirmations) || ["backed_up", "calibrated", "uploaded"].some((name) => record.confirmations[name] !== true)) {
        throw new Error("Confirm backup, in-game calibration, and in-game upload before recording a key");
      }
      return {
        collection_id: record.collection_id, candidate_sha256: record.candidate_sha256,
        key: parseKey(record.key, playerId, record.provider === undefined ? "manual" : record.provider), recorded_at: record.recorded_at,
        ...(record.provider === undefined ? {} : {provider: record.provider}),
        confirmations: {backed_up: true, calibrated: true, uploaded: true}
      };
    });
    return {format, version: 1, player_id: playerId, records};
  }

  function readManifest(storage, playerId) {
    const text = storage.getItem(storageKey(playerId));
    return validateManifest(text === null ? {format, version: 1, player_id: playerId, records: []} : JSON.parse(text), playerId);
  }

  function writeManifest(storage, playerId, value) {
    const validated = validateManifest(value, playerId);
    const text = JSON.stringify(validated);
    if (new TextEncoder().encode(text).length > maxBytes) throw new Error("Key-record backup exceeds 64 KiB");
    storage.setItem(storageKey(playerId), text);
    return validated;
  }

  function statusFor(record, hash) {
    if (!record) return "No Ball Machine Key recorded";
    return record.candidate_sha256 === hash
      ? `Key ${record.key} - user-recorded; cloud unverified`
      : `Key ${record.key} - candidate changed or unavailable; recheck before use`;
  }

  function cloudStatusFor(receipt, hash) {
    if (!receipt) return "No cloud upload recorded for this collection.";
    const stale = receipt.candidate_sha256 !== hash ? "Older candidate revision. " : "";
    return receipt.status === "verified"
      ? `${stale}Key ${receipt.key} - exact cloud read-back matched at ${receipt.verified_at}. In-game testing still required.`
      : `${stale}Upload outcome uncertain: ${receipt.error || "verification incomplete"}. Use Recheck; do not re-upload.`;
  }

  function validateReceipt(receipt, collectionId, hash, playerId) {
    if (!object(receipt) || !["verified", "uncertain"].includes(receipt.status)
      || typeof receipt.id !== "string" || !/^[a-f0-9]{32}$/.test(receipt.id)
      || receipt.provider !== "11hero" || receipt.collection_id !== collectionId
      || receipt.candidate_sha256 !== hash || typeof receipt.published_sha256 !== "string"
      || !/^[a-f0-9]{64}$/.test(receipt.published_sha256)) {
      throw new Error("Invalid or mismatched publication receipt; reload and inspect the server journal");
    }
    if (receipt.status === "verified") {
      parseKey(receipt.key, playerId, "11hero");
      if (typeof receipt.verified_at !== "string" || !Number.isFinite(Date.parse(receipt.verified_at))) {
        throw new Error("Verified receipt has no valid verification timestamp");
      }
    } else if (receipt.key !== null) {
      throw new Error("An uncertain publication cannot assert a key");
    }
    return receipt;
  }

  function initialize({playerId, collections, candidates, hashes, downloadJson, onChange, renderPreview, service}) {
    const $ = (selector) => document.querySelector(selector);
    const select = $("#publish-collection");
    let manifest, readable = false, busy = false, cloudRecords = service?.publications || [];
    const candidate = () => candidates.find((item) => item.recipe_id === select.value);
    const recordFor = (id) => manifest?.records.find((record) => record.collection_id === id);
    const cloudFor = (id) => cloudRecords.find((item) => item.collection_id === id && item.candidate_sha256 === hashes[id])
      || cloudRecords.filter((item) => item.collection_id === id).at(-1);
    const status = (id) => cloudFor(id) ? cloudStatusFor(cloudFor(id), hashes[id])
      : readable ? statusFor(recordFor(id), hashes[id]) : "Local key records unavailable";

    function clearMessages() {
      $("#publishing-error").hidden = true;
      $("#publishing-message").textContent = "";
    }

    function error(exc) {
      console.error("11 Analyst publishing:", exc);
      $("#publishing-error").textContent = `${exc.message}. No game files were installed or changed. For cloud actions, check the publication status before retrying.`;
      $("#publishing-error").hidden = false;
      $("#publishing-message").textContent = "";
    }

    function refresh() {
      const item = candidate(), record = recordFor(select.value);
      $("#publish-download").disabled = !item;
      $("#publish-fields").disabled = !item || !readable;
      $("#publish-export").disabled = !readable;
      $("#publish-key-form").reset();
      $("#publish-key").value = record?.key || "";
      $("#publish-provider").value = record?.provider || "manual";
      $("#publish-key-help").textContent = `Choose your account (${playerId}) or 11 Hero (54334). Paste the returned key; do not invent a settings ID.`;
      $("#publish-key-status").textContent = readable ? statusFor(record, hashes[select.value]) : "Local key records unavailable";
      $("#publish-recorded").hidden = !record;
      $("#publish-recorded-key").value = record?.key || "";
      $("#publish-recorded-date").textContent = record ? `Recorded ${new Date(record.recorded_at).toLocaleString()}. Not checked against the cloud.` : "";
      $("#publish-revision").textContent = item ? hashes[item.recipe_id] : "Unavailable";
      $("#publish-summary").textContent = item
        ? `${Object.keys(item.settings.shots.data).length} feeds. General template-based return practice, NOT a reproduction of an opponent's ball. Stage 1 starts active; deactivate earlier feeds before activating a later stage. Calibrate in-game.`
        : "No eligible return plan with available settings in this match mode. Own-serve practice is coaching-only; player-specific reproduction is not validated.";
      $("#publish-stages").replaceChildren();
      for (const stage of item?.stages || []) {
        const row = document.createElement("li");
        row.textContent = `${stage.title}: feeds ${stage.feeds.join(", ")} (${stage.active_initially ? "active initially" : "inactive until you progress"}).`;
        $("#publish-stages").append(row);
      }
      $("#publish-graphic").innerHTML = renderPreview(item);
      $("#publish-record-count").textContent = readable
        ? `${manifest.records.length} locally recorded keys for player ${playerId}. Imported older or unavailable collections are retained in exports.`
        : "Local records could not be read. Export is disabled to avoid creating an empty, misleading backup. Import a valid backup or explicitly clear local records to recover.";
      refreshCloud();
    }

    function refreshCloud() {
      const item = candidate(), receipt = cloudFor(select.value);
      const current = Boolean(receipt && receipt.candidate_sha256 === hashes[select.value]);
      $("#cloud-selection").textContent = `Selected return training plan: ${item?.title || "Unavailable"}`;
      $("#cloud-upload").disabled = !service || !item || busy || !$("#cloud-consent").checked || Boolean(current);
      $("#cloud-upload").textContent = !item ? "Settings unavailable" : busy ? "Generating key..."
        : current ? receipt.status === "verified" ? "Key already generated" : "Recheck required" : "Generate Ball Machine Key";
      $("#cloud-recheck").disabled = !service || busy || !receipt || receipt.status === "verified" || !$("#cloud-consent").checked;
      $("#cloud-recheck").hidden = !service || !receipt || receipt.status === "verified";
      $("#cloud-export").disabled = !service || busy || !cloudRecords.length;
      $("#cloud-consent").disabled = !service || busy;
      select.disabled = busy;
      $("#cloud-status").textContent = busy ? "Working with 11 Hero. Do not close the server or submit another upload." : cloudStatusFor(receipt, hashes[select.value]);
      $("#cloud-key-box").hidden = !receipt || receipt.status !== "verified";
      $("#cloud-key").value = receipt?.status === "verified" ? receipt.key : "";
      $("#cloud-copy").disabled = busy || !receipt || receipt.status !== "verified";
      $("#cloud-history").replaceChildren();
      for (const saved of cloudRecords) {
        const row = document.createElement("li");
        const description = document.createElement("p");
        description.textContent = `${saved.collection_id}: ${cloudStatusFor(saved, hashes[saved.collection_id])}`;
        row.append(description);
        if (saved.status === "verified") {
          const key = document.createElement("input");
          key.type = "text";
          key.readOnly = true;
          key.value = saved.key;
          key.setAttribute("aria-label", `Saved key for ${saved.collection_id}`);
          key.addEventListener("click", (event) => event.target.select());
          row.append(key);
        } else {
          const recheck = document.createElement("button");
          recheck.type = "button";
          recheck.className = "button small secondary";
          recheck.textContent = `Recheck saved ${saved.collection_id}`;
          recheck.disabled = !service || busy;
          recheck.addEventListener("click", () => cloudAction(true, saved));
          row.append(recheck);
        }
        $("#cloud-history").append(row);
      }
      if (service) {
        $("#publishing-mode").textContent = item ? "Key generation ready" : "No eligible plan";
        $("#cloud-availability").textContent = item
          ? "Ready to generate a general-practice key through 11 Hero. Approve sharing below, then select Generate Ball Machine Key."
          : "No eligible return plan with settings in the selected match mode. Player-specific keys are withheld until reproduction is validated.";
      }
    }

    async function cloudAction(recheck, historical = null) {
      clearMessages();
      const item = candidate(), previous = historical || cloudFor(select.value);
      if (!service || busy || (!historical && !$("#cloud-consent").checked) || (recheck ? !previous : !item)) {
        error(new Error("A connected service, selected collection, and explicit sharing consent are required"));
        return;
      }
      if (historical && !globalThis.confirm(`Read 11 Hero to recheck saved ${historical.collection_id}? No settings will be uploaded. This does not change the selected training plan.`)) return;
      if (!recheck && !globalThis.confirm(`Publish ${item.title} through 11 Hero's shared account? The settings may be public and cannot be deleted here. This does not install or test them in Eleven.`)) return;
      busy = true;
      refreshCloud();
      try {
        const response = await fetch(recheck ? "/api/recheck" : "/api/publish", {
          method: "POST", headers: {"Content-Type": "application/json", "X-11Analyst-Token": service.token},
          body: JSON.stringify({
            collection_id: recheck ? previous.collection_id : item.recipe_id,
            candidate_sha256: recheck ? previous.candidate_sha256 : hashes[item.recipe_id], consent: true
          })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || `Local publishing service returned HTTP ${response.status}`);
        validateReceipt(result, recheck ? previous.collection_id : item.recipe_id,
          recheck ? previous.candidate_sha256 : hashes[item.recipe_id], playerId);
        cloudRecords = [...cloudRecords.filter((entry) => entry.id !== result.id), result];
        if (result.status === "uncertain") error(new Error(result.error || "Cloud upload is not verified"));
        else $("#publishing-message").textContent = `Key ${result.key} saved in the server's publication journal. Read-back matched; now test it in Eleven.`;
      } catch (exc) {
        error(new Error(`${exc.message}. The server may have uploaded settings. Reload to recover its journal; no automatic retry was made`));
      } finally {
        busy = false;
        $("#cloud-consent").checked = false;
        refreshCloud();
        onChange();
      }
    }

    function restore() {
      try {
        manifest = readManifest(globalThis.localStorage, playerId);
        readable = true;
      } catch (exc) {
        readable = false;
        manifest = undefined;
        error(exc);
      }
      refresh();
    }

    function save(value, message) {
      const saved = writeManifest(globalThis.localStorage, playerId, value);
      manifest = saved;
      readable = true;
      refresh();
      onChange();
      $("#publishing-message").textContent = message;
    }

    for (const collection of collections) {
      const option = document.createElement("option");
      option.value = collection.id;
      option.textContent = collection.title;
      select.append(option);
    }
    const first = collections.find((item) => candidates.some((entry) => entry.recipe_id === item.id));
    if (first) select.value = first.id;
    restore();

    select.addEventListener("change", () => { clearMessages(); $("#cloud-consent").checked = false; refresh(); });
    $("#cloud-consent").addEventListener("change", refreshCloud);
    $("#cloud-upload").addEventListener("click", () => cloudAction(false));
    $("#cloud-recheck").addEventListener("click", () => cloudAction(true));
    $("#cloud-key").addEventListener("click", (event) => event.target.select());
    $("#cloud-copy").addEventListener("click", async () => {
      clearMessages();
      try {
        if ($("#cloud-key-box").hidden || !$("#cloud-key").value) throw new Error("No verified key is available");
        await navigator.clipboard.writeText($("#cloud-key").value);
        $("#publishing-message").textContent = "Ball Machine Key copied. Paste it into Eleven's Download field.";
      } catch (exc) {
        $("#cloud-key").focus();
        $("#cloud-key").select();
        error(new Error(`Automatic copy failed: ${exc.message}. Select the key and use your browser's Copy command`));
      }
    });
    $("#cloud-export").addEventListener("click", () => {
      try { downloadJson(`11-analyst-${playerId}-cloud-key-receipts.json`, {
        format: "11analyst.cloud-key-receipts", version: 1, player_id: playerId, publications: cloudRecords
      }); } catch (exc) { error(exc); }
    });
    $("#publish-recorded-key").addEventListener("click", (event) => event.target.select());
    $("#publish-download").addEventListener("click", () => {
      clearMessages();
      try {
        const item = candidate();
        if (!item) throw new Error("No generated settings are available for this collection");
        downloadJson("BallLauncherSettings.json", item.settings);
        $("#publishing-message").textContent = "Download requested. Check your browser's downloads; nothing was installed or uploaded.";
      } catch (exc) { error(exc); }
    });
    $("#publish-key-form").addEventListener("submit", (event) => {
      event.preventDefault();
      clearMessages();
      try {
        const item = candidate();
        if (!item || !readable) throw new Error("Valid candidate settings and readable local records are required");
        const record = {
          collection_id: item.recipe_id, candidate_sha256: hashes[item.recipe_id],
          provider: $("#publish-provider").value,
          key: parseKey($("#publish-key").value, playerId, $("#publish-provider").value), recorded_at: new Date().toISOString(),
          confirmations: {
            backed_up: $("#publish-backed-up").checked, calibrated: $("#publish-calibrated").checked,
            uploaded: $("#publish-uploaded").checked
          }
        };
        const current = readManifest(globalThis.localStorage, playerId);
        const previous = current.records.find((entry) => entry.collection_id === record.collection_id);
        if (previous && !globalThis.confirm("Replace this collection's local key record? This does not change or remove anything in Eleven's cloud.")) return;
        save({...current, records: [...current.records.filter((entry) => entry.collection_id !== record.collection_id), record]},
          "Key recorded in this browser only. Cloud contents have not been verified. Export your key records for a portable backup.");
      } catch (exc) { error(exc); }
    });
    $("#publish-export").addEventListener("click", () => {
      clearMessages();
      try {
        const current = readManifest(globalThis.localStorage, playerId);
        downloadJson(`11-analyst-${playerId}-ball-machine-keys.json`, current);
        $("#publishing-message").textContent = "Key-record backup download requested. Keep it with your settings backups; it contains no settings payload or login credentials.";
      } catch (exc) { error(exc); }
    });
    $("#publish-import").addEventListener("change", async (event) => {
      const file = event.target.files[0];
      if (!file) return;
      clearMessages();
      try {
        if (file.size > maxBytes) throw new Error("Key-record backup exceeds 64 KiB");
        const imported = validateManifest(JSON.parse(await file.text()), playerId);
        if (!globalThis.confirm(`Replace this browser's key records with ${imported.records.length} records from this backup? Export your current records first if needed. This does not upload anything.`)) return;
        save(imported, "Key records imported into this browser. Keys and in-game confirmations are user-recorded, not cloud-verified.");
      } catch (exc) { error(exc); }
      finally { event.target.value = ""; }
    });
    $("#publish-reset").addEventListener("click", () => {
      clearMessages();
      if (!globalThis.confirm("Clear this player's key records from this browser? Export a backup first. This cannot be undone here and will not delete any settings or keys from Eleven.")) return;
      try {
        globalThis.localStorage.removeItem(storageKey(playerId));
        restore();
        onChange();
        if (readable) $("#publishing-message").textContent = "Local key records cleared. Eleven's cloud and your game files were not changed.";
      } catch (exc) { error(exc); }
    });
    globalThis.addEventListener("storage", (event) => {
      if (event.key === storageKey(playerId) || event.key === null) {
        clearMessages();
        restore();
        onChange();
      }
    });
    return {
      status,
      setPlans(next) {
        if (busy || JSON.stringify(collections.map((item) => item.id)) === JSON.stringify(next.map((item) => item.id))) return;
        const previous = select.value;
        collections = next;
        select.replaceChildren();
        for (const item of collections) {
          const option = document.createElement("option");
          option.value = item.id;
          option.textContent = item.title;
          select.append(option);
        }
        select.value = collections.some((item) => item.id === previous) ? previous : collections[0]?.id || "";
        if (select.value !== previous) {
          $("#cloud-consent").checked = false;
          clearMessages();
        }
        refresh();
      },
      select(id) {
        if (busy) throw new Error("Wait for the current cloud operation to finish");
        if (!collections.some((item) => item.id === id)) throw new Error("This return plan is not eligible in the selected match mode");
        select.value = id;
        $("#cloud-consent").checked = false;
        clearMessages();
        refresh();
        $("#publishing-workbench").scrollIntoView({block: "start"});
        select.focus({preventScroll: true});
      }
    };
  }

  const api = {parseKey, validateManifest, readManifest, writeManifest, storageKey, statusFor, cloudStatusFor, validateReceipt, initialize};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else globalThis.ElevenPublishing = api;
})();
