import test from "node:test";
import assert from "node:assert/strict";

import {
  clamp,
  defaultPreset,
  formatDuration,
  keywordsFromText,
  mergePreset,
  sentenceCount,
  uniqueValues,
  wordCount,
} from "../../app/static/videodesign/utils.js";


test("text helpers preserve existing workflow semantics", () => {
  assert.equal(wordCount("one two three"), 3);
  assert.equal(sentenceCount("One. Two? Three!"), 3);
  assert.deepEqual(keywordsFromText("cat, japan life, cat"), ["cat", "japan life", "cat"]);
  assert.deepEqual(uniqueValues(["Cat", "cat", "Japan"]), ["Cat", "Japan"]);
});


test("format and preset helpers preserve defaults", () => {
  assert.equal(formatDuration(65), "1:05");
  assert.equal(clamp(12, 0, 10), 10);
  const preset = mergePreset(defaultPreset(), { voiceover: { voice_speed: 1.2 } });
  assert.equal(preset.voiceover.voice_speed, 1.2);
  assert.equal(preset.voiceover.voice_id, "en-US-AriaNeural");
});
